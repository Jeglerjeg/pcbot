import asyncio
import logging
import traceback
from datetime import datetime, timezone, timedelta
from discord.ext import tasks

import aiohttp
import discord

import bot
import plugins
from plugins.osulib import api, enums, pp
from plugins.osulib.constants import cache_user_profiles, not_playing_skip, event_repeat_interval, notify_empty_scores,\
    score_request_limit, use_mentions_in_scores, update_interval, osu_tracking, osu_profile_cache
from plugins.osulib.enums import UpdateModes, Mods
from plugins.osulib.formatting import embed_format, score_format, misc_format, beatmap_format
from plugins.osulib.utils import user_utils, score_utils, misc_utils
from plugins.osulib.config import osu_config

client = plugins.client  # type: bot.Client


class MapEvent:
    """ Store userpage map events so that we don't send multiple updates. """

    def __init__(self, text):
        self.text = text

        self.time_created = datetime.utcnow()
        self.count = 1
        self.messages = []

    def __repr__(self):
        return f"MapEvent(text={self.text}, time_created={self.time_created.ctime()}, count={self.count})"

    def __str__(self):
        return repr(self)


class OsuTracker:
    def __init__(self):
        self.previous_update = None
        self.time_elapsed = 0
        self.started = None
        self.previous_score_updates = []
        self.recent_map_events = []

        # Notify the owner when they have not set their API key
        if osu_config.data["client_secret"] == "change to your client secret" or \
                osu_config.data["client_id"] == "change to your client ID":
            logging.warning("osu! functionality is unavailable until a "
                            "client ID and client secret is provided (config/osu.json)")
        else:
            self.__tracking_loop.start()

    @tasks.loop(seconds=update_interval)
    async def __tracking_loop(self):
        if not api.access_token:
            await api.get_access_token(osu_config.data.get("client_id"), osu_config.data.get("client_secret"))
            client.loop.create_task(api.refresh_access_token(osu_config.data.get("client_id"),
                                                             osu_config.data.get("client_secret")))
        self.started = datetime.now()

        for member_id, profile in list(osu_config.data["profiles"].items()):
            # First, update the user's data
            await self.__update_user_data(member_id, profile)
            if str(member_id) in osu_tracking:
                data = osu_tracking[str(member_id)]
                # Next, check for any differences in pp between the "old" and the "new" subsections
                # and notify any guilds
                if misc_utils.check_for_pp_difference(data):
                    client.loop.create_task(self.__notify_pp(str(member_id), data))
                # Check for any differences in the users' events and post about map updates
                if misc_utils.check_for_new_recent_events(data):
                    client.loop.create_task(self.__notify_recent_events(str(member_id), data))
        if cache_user_profiles:
            await osu_profile_cache.asyncsave()
        self.time_elapsed = (datetime.now() - self.started).total_seconds()
        self.previous_update = datetime.now(tz=timezone.utc)

    @__tracking_loop.before_loop
    async def wait_for_ready(self):
        await client.wait_until_ready()

    @staticmethod
    async def __update_user_data(member_id: str, profile: str):
        """ Go through all registered members playing osu!, and update their data. """
        # Go through each member playing and give them an "old" and a "new" subsection
        # for their previous and latest user data
        # Skip members who disabled tracking

        if user_utils.get_update_mode(member_id) is enums.UpdateModes.Disabled:
            return

        member = discord.utils.get(client.get_all_members(), id=int(member_id))
        if user_utils.user_exists(member, member_id, profile) \
                or user_utils.user_unlinked_during_iteration(member_id, osu_tracking):
            if member_id in osu_tracking:
                del osu_tracking[member_id]
            if member_id in osu_profile_cache.data:
                del osu_profile_cache.data[member_id]
            return

        # Check if the member is tracked, add to cache and tracking if not
        if member_id not in osu_tracking:
            osu_tracking[member_id] = {}
            if cache_user_profiles:
                osu_profile_cache.data[member_id] = {}

        if "schedule_wipe" not in osu_tracking[member_id]:
            osu_tracking[member_id]["schedule_wipe"] = False
        elif osu_tracking[member_id]["schedule_wipe"] is True:
            osu_tracking[member_id] = {}
            osu_profile_cache.data[member_id] = {}

        # Add update ticks to member tracking
        if "ticks" not in osu_tracking[member_id]:
            osu_tracking[member_id]["ticks"] = -1

        osu_tracking[member_id]["member"] = member
        osu_tracking[member_id]["ticks"] += 1

        # Only update members not tracked ingame every nth update
        if not user_utils.is_playing(member) and osu_tracking[member_id]["ticks"] % not_playing_skip > 0:
            # Update their old data to match their new one in order to avoid duplicate posts
            if "new" in osu_tracking[member_id]:
                osu_tracking[member_id]["old"] = osu_tracking[str(member_id)]["new"]
            return

        # Get the user data for the player
        current_time = datetime.now(tz=timezone.utc).isoformat()
        mode = user_utils.get_mode(member_id)
        try:
            user_data = await user_utils.retrieve_user_proile(profile, mode, current_time)
            if user_data is None:
                logging.info("Could not retrieve osu! info from %s (%s)", member, profile)
                return
            params = {
                "limit": 20
            }
            if user_utils.get_leaderboard_update_status(member_id) or user_utils.get_beatmap_update_status(member_id):
                recent_events = await api.get_user_recent_activity(profile, params=params)
                if recent_events is not None:
                    user_data["events"] = recent_events
                else:
                    logging.info("Could not retrieve osu! info from %s (%s)", member, profile)
                    return
            else:
                user_data["events"] = []
            # User is already tracked
            if "scores" not in osu_tracking[member_id]:
                fetched_scores = await score_utils.retrieve_osu_scores(profile, mode, current_time)
                if fetched_scores:
                    osu_tracking[member_id]["scores"] = fetched_scores
                    if cache_user_profiles:
                        osu_profile_cache.data[member_id]["scores"] = fetched_scores
        except aiohttp.ServerDisconnectedError:
            return
        except asyncio.TimeoutError:
            logging.warning("Timed out when retrieving osu! info from %s (%s)", member, profile)
            return
        except ValueError:
            logging.info("Could not retrieve osu! info from %s (%s)", member, profile)
            return
        # Update the "new" data
        if "new" in osu_tracking[member_id]:
            # Move the "new" data into the "old" data of this user
            osu_tracking[member_id]["old"] = osu_tracking[member_id]["new"]

        osu_tracking[member_id]["new"] = user_data
        if cache_user_profiles:
            osu_profile_cache.data[member_id]["new"] = osu_tracking[member_id]["new"]
            osu_profile_cache.data[member_id]["ticks"] = osu_tracking[member_id]["ticks"]

    async def __notify_recent_events(self, member_id: str, data: dict):
        """ Notify any map updates, such as update, resurrect and qualified. """

        old, new = data["old"]["events"], data["new"]["events"]

        # Get the new events
        events = []
        for event in new:
            if event in old:
                break

            # Since the events are displayed on the profile from newest to oldest, we want to post the oldest first
            events.insert(0, event)

        # Format and post the events
        status_format = None
        beatmap_info = None
        leaderboard_enabled = user_utils.get_leaderboard_update_status(member_id)
        for event in events:
            # Get and format the type of event
            if event["type"] == "beatmapsetUpload":
                status_format = "<name> has submitted a new beatmap <title>"
            elif event["type"] == "beatmapsetUpdate":
                status_format = "<name> has updated the beatmap <title>"
            elif event["type"] == "beatmapsetRevive":
                status_format = "<title> has been revived from eternal slumber by <name>"
            elif event["type"] == "beatmapsetApprove" and event["approval"] == "qualified":
                status_format = "<title> by <name> has been qualified!"
            elif event["type"] == "beatmapsetApprove" and event["approval"] == "ranked":
                status_format = "<title> by <name> has been ranked!"
            elif event["type"] == "beatmapsetApprove" and event["approval"] == "loved":
                status_format = "<title> by <name> has been loved!"
            elif event["type"] == "rank" and event["rank"] <= 50 and leaderboard_enabled:
                beatmap_info = api.parse_beatmap_url("https://osu.ppy.sh" + event["beatmap"]["url"])
            else:  # We discard any other events
                continue

            # Replace shortcuts with proper formats and add url formats
            if status_format:
                status_format = status_format.replace("<name>", "[**{name}**]({host}users/{user_id})")
                status_format = status_format.replace("<title>", "[**{artist} - {title}**]({host}beatmapsets/{id})")

                # We'll sleep for a long while to let the beatmap API catch up with the change
                await asyncio.sleep(45)

                # Try returning the beatmap info 6 times with a span of a minute
                # This might be needed when new maps are submitted
                for _ in range(6):
                    beatmapset = await api.beatmapset_from_url(
                        "".join(["https://osu.ppy.sh", event["beatmapset"]["url"]]),
                        force_redownload=True)
                    if beatmapset:
                        break
                    await asyncio.sleep(60)
                else:
                    # well shit
                    continue

                # Calculate (or retrieve cached info) the pp for every difficulty of this mapset
                try:
                    await pp.calculate_pp_for_beatmapset(beatmapset, osu_config, ignore_osu_cache=True)
                except ValueError:
                    logging.error(traceback.format_exc())

                event_text = [event["beatmapset"]["title"], event["type"],
                              (event["approval"] if event["type"] == "beatmapsetApprove" else "")]
                new_event = MapEvent(text=str("".join(event_text)))
                prev = discord.utils.get(self.recent_map_events, text="".join(event_text))
                to_delete = []

                if prev:
                    self.recent_map_events.remove(prev)

                    if prev.time_created + timedelta(hours=event_repeat_interval) > new_event.time_created:
                        to_delete = prev.messages
                        new_event.count = prev.count + 1
                        new_event.time_created = prev.time_created

                # Always append the new event to the recent list
                self.recent_map_events.append(new_event)

                # Send the message to all guilds
                member = data["member"]
                if not member:
                    continue
                for guild in member.mutual_guilds:
                    channels = misc_utils.get_notify_channels(guild, "map")  # type: list

                    if not channels:
                        continue

                    member = guild.get_member(int(member_id))

                    for channel in channels:
                        # Do not format difficulties when minimal (or pp) information is specified
                        update_mode = user_utils.get_update_mode(member_id)
                        embed = await beatmap_format.format_map_status(member, status_format, beatmapset,
                                                                       update_mode is not UpdateModes.Full)

                        if new_event.count > 1:
                            embed.set_footer(text=f"updated {new_event.count} times since")
                            embed.timestamp = new_event.time_created.replace(tzinfo=timezone.utc)

                        # Delete the previous message if there is one
                        if to_delete:
                            delete_msg = discord.utils.get(to_delete, channel=channel)
                            await client.delete_message(delete_msg)
                            to_delete.remove(delete_msg)

                        try:
                            msg = await client.send_message(channel, embed=embed)
                        except discord.errors.Forbidden:
                            pass
                        else:
                            new_event.messages.append(msg)
            elif beatmap_info is not None:
                user_id = osu_config.data["profiles"][member_id]
                mode = beatmap_info.gamemode

                params = {
                    "mode": mode.name,
                }
                osu_scores = await api.get_user_beatmap_score(beatmap_info.beatmap_id, user_id, params=params)
                if osu_scores is None:
                    continue

                osu_score = osu_scores["score"]
                position = osu_scores["position"]

                if osu_score["best_id"] in self.previous_score_updates:
                    continue

                top100_best_id = []
                for old_score in data["scores"]["score_list"]:
                    top100_best_id.append(old_score["best_id"])

                if osu_score["best_id"] in top100_best_id:
                    continue

                self.previous_score_updates.append(osu_score["best_id"])

                params = {
                    "beatmap_id": osu_score["beatmap"]["id"],
                }
                beatmap = (await api.beatmap_lookup(params=params, map_id=beatmap_info.beatmap_id, mode=mode.name))
                # Send the message to all guilds
                member = data["member"]
                if not member:
                    continue
                for guild in member.mutual_guilds:
                    channels = misc_utils.get_notify_channels(guild, "score")
                    if not channels:
                        continue
                    member = guild.get_member(int(member_id))

                    embed = await embed_format.create_score_embed_with_pp(member, osu_score, beatmap, mode,
                                                                          osu_tracking,
                                                                          position, twitch_link=True)
                    embed.set_author(name=f"{data['new']['username']} set a new leaderboard score",
                                     icon_url=data["new"]["avatar_url"], url=user_utils.get_user_url(str(member.id)))

                    for channel in channels:
                        try:
                            await client.send_message(channel, embed=embed)
                        except discord.Forbidden:
                            pass

    async def __notify_pp(self, member_id: str, data: dict):
        """ Notify any differences in pp and post the scores + rank/pp gained. """

        old, new = data["old"], data["new"]

        member = data["member"]
        mode = user_utils.get_mode(member_id)
        update_mode = user_utils.get_update_mode(member_id)
        m = []
        score_pp = None
        thumbnail_url = ""
        osu_score = None
        osu_scores = []  # type: list
        # Since the user got pp they probably have a new score in their own top 100
        # If there is a score, there is also a beatmap
        if update_mode is not UpdateModes.PP:
            for i in range(3):
                osu_scores = await score_utils.get_new_score(member_id, osu_tracking, osu_profile_cache)
                if osu_scores:
                    break
                await asyncio.sleep(osu_config.data["score_update_delay"])
            else:
                logging.info("%s (%s) gained PP, but no new score was found.", member.name, member_id)
        for osu_score in list(osu_scores):
            if osu_score["best_id"] in self.previous_score_updates:
                osu_scores.remove(osu_score)
                continue
            self.previous_score_updates.append(osu_score["best_id"])

        if not osu_scores and not notify_empty_scores:
            return

        # If a new score was found, format the score(s)
        if len(osu_scores) == 1:
            osu_score = osu_scores[0]
            params = {
                "beatmap_id": osu_score["beatmap"]["id"],
            }
            beatmap = (await api.beatmap_lookup(params=params, map_id=osu_score["beatmap"]["id"], mode=mode.name))
            thumbnail_url = beatmap["beatmapset"]["covers"]["list@2x"]
            author_text = f"{data['new']['username']} set a new best (#{osu_score['pos']}/{score_request_limit} " \
                          f"+{osu_score['diff']:.2f}pp)"

            # There might not be any events
            scoreboard_rank = None
            if new["events"]:
                scoreboard_rank = api.rank_from_events(new["events"], str(osu_score["beatmap"]["id"]), osu_score)
            # Calculate PP and change beatmap SR if using a difficult adjusting mod
            score_pp = await pp.get_score_pp(osu_score, mode, beatmap)
            mods = Mods.format_mods(osu_score["mods"])
            beatmap["difficulty_rating"] = pp.get_beatmap_sr(score_pp, beatmap, mods)
            if ("max_combo" not in beatmap or not beatmap["max_combo"]) and score_pp.max_combo:
                beatmap["max_combo"] = score_pp.max_combo
            if update_mode is UpdateModes.Minimal:
                m.append("".join([await score_format.format_minimal_score(osu_score, beatmap, scoreboard_rank, member),
                                  "\n"]))
            else:
                m.append(await score_format.format_new_score(mode, osu_score, beatmap, scoreboard_rank, member))
        elif len(osu_scores) > 1:
            for osu_score in list(osu_scores):
                # There might not be any events
                osu_score["scoreboard_rank"] = None
                if new["events"]:
                    osu_score["scoreboard_rank"] = api.rank_from_events(new["events"],
                                                                        str(osu_score["beatmap"]["id"]), osu_score)
            m.append(await score_format.get_formatted_score_list(mode, osu_scores,
                                                                 limit=len(osu_scores) if len(osu_scores) <= 5 else 5,
                                                                 no_time=True))
            thumbnail_url = data["new"]["avatar_url"]
            author_text = f"""{data["new"]["username"]} set new best scores"""
        else:
            author_text = data["new"]["username"]

        # Always add the difference in pp along with the ranks
        m.append(misc_format.format_user_diff(mode, old, new))

        # Send the message to all guilds
        for guild in member.mutual_guilds:
            channels = misc_utils.get_notify_channels(guild, "score")
            if not channels:
                continue
            member = guild.get_member(int(member_id))

            primary_guild = user_utils.get_primary_guild(str(member.id))
            is_primary = True if primary_guild is None else bool(primary_guild == str(guild.id))
            potential_string = score_format.format_potential_pp(score_pp if score_pp is not None
                                                                and not bool(osu_score["legacy_perfect"]
                                                                             and osu_score["passed"])
                                                                else None,
                                                                osu_score)
            embed = embed_format.get_embed_from_template("".join(m), member.color, author_text,
                                                         user_utils.get_user_url(str(member.id)),
                                                         data["new"]["avatar_url"], thumbnail_url,
                                                         potential_string=potential_string)
            for i, channel in enumerate(channels):
                try:
                    await client.send_message(channel, embed=embed)

                    # In the primary guild and if the user sets a score, send a mention and delete it
                    # This will only mention in the first channel of the guild
                    if use_mentions_in_scores and osu_score and i == 0 and is_primary \
                            and update_mode is not UpdateModes.No_Mention:
                        mention = await client.send_message(channel, member.mention)
                        await client.delete_message(mention)
                except discord.Forbidden:
                    pass

    def get_time_elapsed(self):
        return self.time_elapsed

    def get_previous_time(self):
        return self.previous_update
