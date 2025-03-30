import asyncio
import logging
import traceback
from datetime import datetime, timezone, timedelta

import aiohttp
import discord
from discord.ext import tasks

import bot
import plugins
from dateutil import parser
from plugins.osulib import api, enums, pp, db, scores_ws
from plugins.osulib.config import osu_config
from plugins.osulib.constants import not_playing_skip, event_repeat_interval, update_interval, host, \
    use_mentions_in_scores, score_request_limit
from plugins.osulib.enums import UpdateModes, Mods
from plugins.osulib.formatting import embed_format, beatmap_format, misc_format, score_format
from plugins.osulib.models.score import OsuScore
from plugins.osulib.models.user import OsuUser
from plugins.osulib.utils import user_utils, misc_utils, score_utils

client = plugins.client  # type: bot.Client


class MapEvent:
    """ Store userpage map events so that we don't send multiple updates. """

    def __init__(self, text):
        self.text = text

        self.time_created = datetime.now(timezone.utc)
        self.count = 1
        self.messages = []

    def __repr__(self):
        return f"MapEvent(text={self.text}, time_created={self.time_created.ctime()}, count={self.count})"

    def __str__(self):
        return repr(self)


async def wipe_user(member_id: int):
    """ Deletes user data from tracking. """
    old_user = db.get_osu_user(member_id)
    if db.get_recent_events(member_id):
        db.delete_recent_events(member_id)
    if db.get_osu_user(member_id):
        db.delete_osu_user(member_id)
    if old_user and old_user.id in scores_ws.tracked_users:
        if len(scores_ws.tracked_users[old_user.id]) == 1:
            scores_ws.tracked_users.pop(old_user.id, None)
        else:
            scores_ws.tracked_users[old_user.id].remove(member_id)


async def add_new_user(member_id: int, profile: int):
    # Wipe user data to make sure things aren't duplicated
    await wipe_user(member_id)

    current_time = datetime.now(tz=timezone.utc)
    mode = user_utils.get_mode(str(member_id))
    api_user_data = await user_utils.retrieve_user_profile(str(profile), mode, current_time)
    if api_user_data:
        params = {
            "mode": mode.name,
            "limit": score_request_limit,
        }
        api_user_scores = await api.get_user_scores(str(profile), "best", params=params)
        sorted_scores = score_utils.get_sorted_scores(api_user_scores, "pp")
        api_user_data.min_pp = sorted_scores[len(sorted_scores) - 1].pp
        db.insert_osu_user(api_user_data, member_id)
        if not db.get_recent_events(member_id):
            db.insert_recent_events(member_id)
        if profile in scores_ws.tracked_users:
            scores_ws.tracked_users[profile].append(member_id)
        else:
            scores_ws.tracked_users[profile] = [member_id]
    else:
        logging.info("Could not retrieve osu! info from %s (%s)", member_id, profile)
        return
    return


async def update_osu_user(member_id: int, profile: int, member: discord.Member, osu_user: OsuUser):
    # Get the user data for the player
    try:
        current_time = datetime.now(tz=timezone.utc)
        mode = user_utils.get_mode(str(member_id))
        api_user_data = await user_utils.retrieve_user_profile(str(profile), mode, current_time)
        if api_user_data is None:
            logging.info("Could not retrieve osu! info from %s (%s)", member, profile)
            return
        params = {
            "mode": mode.name,
            "limit": score_request_limit,
        }
        api_user_scores = await api.get_user_scores(str(profile), "best", params=params)
        sorted_scores = score_utils.get_sorted_scores(api_user_scores, "pp")
        api_user_data.min_pp = sorted_scores[len(sorted_scores) - 1].pp
        db.update_osu_user(api_user_data, member_id, osu_user.ticks)
    except aiohttp.ServerDisconnectedError:
        return
    except asyncio.TimeoutError:
        logging.warning("Timed out when retrieving osu! info from %s (%s)", member, profile)
        return
    except ValueError:
        logging.info("Could not retrieve osu! info from %s (%s)", member, profile)
        return


class OsuTracker:
    def __init__(self):
        self.previous_update = None
        self.time_elapsed = 0
        self.started = None
        self.previous_score_updates = {}
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

        try:
            member_list = db.get_linked_osu_profiles()
            for linked_profile in member_list:
                # Update the user's data
                await self.__update_user_data(linked_profile.id, linked_profile.osu_id)
        except Exception as e:
            logging.exception(e)
        finally:
            self.time_elapsed = (datetime.now() - self.started).total_seconds()
            self.previous_update = datetime.now(tz=timezone.utc)

    @__tracking_loop.before_loop
    async def wait_for_ready(self):
        await client.wait_until_ready()

    async def __update_user_data(self, member_id: int, profile: int):
        """ Go through all registered members playing osu!, and update their data. """
        # Go through each member playing and give them an "old" and a "new" subsection
        # for their previous and latest user data
        # Skip members who disabled tracking

        if user_utils.get_update_mode(str(member_id)) is enums.UpdateModes.Disabled:
            return

        member = discord.utils.get(client.get_all_members(), id=member_id)
        if user_utils.user_exists(member, str(member_id), str(profile)) \
                or user_utils.user_unlinked_during_iteration(member_id):
            await wipe_user(member_id)
            return

        # Check if the member is tracked, add to cache and tracking if not
        db_user = db.get_osu_user(member_id)
        if not db_user:
            await add_new_user(member_id, profile)
            return

        osu_user = OsuUser(db_user)
        osu_user.add_tick()

        if osu_user.ticks > not_playing_skip:
            osu_user.reset_ticks()
            db.update_osu_user(osu_user, member_id, osu_user.ticks)
            return

        # Only update members not tracked ingame every nth update
        if not user_utils.is_playing(member) and osu_user.ticks != not_playing_skip:
            db.update_osu_user(osu_user, member_id, osu_user.ticks)
            return

        db.update_osu_user(osu_user, member_id, osu_user.ticks)

        client.loop.create_task(self.__notify_recent_events(str(member_id), osu_user))

    async def __notify_recent_events(self, member_id: str, new_osu_user: OsuUser):
        """ Notify any map updates, such as update, resurrect and qualified. """
        leaderboard_enabled = user_utils.get_leaderboard_update_status(member_id)
        beatmap_enabled = user_utils.get_beatmap_update_status(member_id)
        if not leaderboard_enabled and not beatmap_enabled:
            return

        # Get the new events
        api_events = await api.get_user_recent_activity(new_osu_user.id)
        if api_events is None:
            logging.info(f"Failed to fetch recent events for {member_id}")
            return
        last_user_events = db.get_recent_events(int(member_id))
        if not last_user_events:
            logging.info(f"DB recent events is missing for {member_id}")
            db.insert_recent_events(int(member_id))
            return
        events = []
        for event in api_events:
            try:
                if parser.isoparse(event["created_at"]).replace(tzinfo=timezone.utc).timestamp() \
                        < last_user_events.last_recent_notification:
                    break

                # Since the events are displayed on the profile from newest to oldest, we want to post the oldest first
                events.insert(0, event)
            except TypeError:
                logging.info(f"Failed to parse event: {event}")
                continue
            except KeyError:
                logging.info(f"Failed to parse event: {event}")
                continue

        # Format and post the events
        status_format = None
        beatmap_info = None

        for event in events:
            # Get and format the type of event
            if event["type"] == "beatmapsetUpload":
                status_format = "\N{GLOBE WITH MERIDIANS} <name> has submitted a new beatmap <title>"
            elif event["type"] == "beatmapsetUpdate":
                status_format = "\N{UP-POINTING SMALL RED TRIANGLE} <name> has updated the beatmap <title>"
            elif event["type"] == "beatmapsetRevive":
                status_format = "\N{PERSON WITH FOLDED HANDS} <title> has been revived from eternal slumber by <name>"
            elif event["type"] == "beatmapsetApprove" and event["approval"] == "qualified":
                status_format = "\N{GROWING HEART} <title> by <name> has been qualified!"
            elif event["type"] == "beatmapsetApprove" and event["approval"] == "ranked":
                status_format = "\N{SPORTS MEDAL} <title> by <name> has been ranked!"
            elif event["type"] == "beatmapsetApprove" and event["approval"] == "loved":
                status_format = "\N{HEAVY BLACK HEART} <title> by <name> has been loved!"
            elif event["type"] == "rank" and event["rank"] <= 50 and leaderboard_enabled:
                beatmap_info = api.parse_beatmap_url(host + event["beatmap"]["url"])
            else:  # We discard any other events
                continue

            # Replace shortcuts with proper formats and add url formats
            if status_format:
                if not beatmap_enabled:
                    continue
                status_format = status_format.replace("<name>", "[**{name}**]({host}/users/{user_id})")
                status_format = status_format.replace("<title>", "[**{artist} - {title}**]({host}/beatmapsets/{id})")

                # We'll sleep for a long while to let the beatmap API catch up with the change
                await asyncio.sleep(45)

                # Try returning the beatmap info 6 times with a span of a minute
                # This might be needed when new maps are submitted
                for _ in range(6):
                    beatmapset = await api.beatmapset_from_url(
                        "".join([host, event["beatmapset"]["url"]]),
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

                db.update_recent_events(int(member_id), last_user_events, recent=True)

                # Send the message to all guilds
                member = discord.utils.get(client.get_all_members(), id=int(member_id))
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
                user_id = new_osu_user.id
                mode = beatmap_info.gamemode

                params = {
                    "mode": mode.name,
                }
                osu_scores = await api.get_user_beatmap_score(beatmap_info.beatmap_id, user_id, params=params)
                if osu_scores is None:
                    continue

                osu_score = osu_scores["score"]  # type: OsuScore
                osu_score.rank_global = osu_scores["position"]

                if member_id not in self.previous_score_updates:
                    self.previous_score_updates[member_id] = []

                db.update_recent_events(int(member_id), last_user_events, recent=True)
                if osu_score.id in self.previous_score_updates[member_id]:
                    continue

                self.previous_score_updates[member_id].append(osu_score.id)

                beatmap = await api.beatmap_lookup(map_id=beatmap_info.beatmap_id)

                # Send the message to all guilds
                member = discord.utils.get(client.get_all_members(), id=int(member_id))
                if not member:
                    continue
                for guild in member.mutual_guilds:
                    channels = misc_utils.get_notify_channels(guild, "score")
                    if not channels:
                        continue
                    member = guild.get_member(int(member_id))

                    embed = await embed_format.create_score_embed_with_pp(member, osu_score, beatmap, mode,
                                                                          twitch_link=True)
                    embed.set_author(name=f"{new_osu_user.username} set a new leaderboard score",
                                     icon_url=new_osu_user.avatar_url,
                                     url=user_utils.get_user_url(str(new_osu_user.id)))

                    for channel in channels:
                        try:
                            await client.send_message(channel, embed=embed)
                        except discord.Forbidden:
                            pass


async def notify_pp(member_id: str, osu_score: OsuScore, old_osu_user: OsuUser = None, last_user_events = None):
    """ Notify any differences in pp and post the scores + rank/pp gained. """
    member = discord.utils.get(client.get_all_members(), id=int(member_id))
    if not member:
        return

    mode = user_utils.get_mode(member_id)
    update_mode = user_utils.get_update_mode(member_id)
    m = []
    # Since the user got pp they probably have a new score in their own top 100
    # If there is a score, there is also a beatmap

    await update_osu_user(int(member_id), old_osu_user.id, member, old_osu_user)

    new_osu_user = db.get_osu_user(int(member_id))

    beatmap = await api.beatmap_lookup(map_id=osu_score.beatmap_id)
    thumbnail_url = beatmap.beatmapset.covers.list2x
    author_text = f"{new_osu_user.username} set a new best!"

    # Calculate PP and change beatmap SR if using a difficult adjusting mod
    score_pp = await pp.get_score_pp(osu_score, mode, beatmap)
    mods = Mods.format_mods(osu_score.mods)
    beatmap.difficulty_rating = pp.get_beatmap_sr(score_pp, beatmap, mods)
    beatmap.max_combo = score_pp.max_combo
    if (not hasattr(beatmap, "max_combo") or not beatmap.max_combo) and score_pp.max_combo:
        beatmap.add_max_combo(score_pp.max_combo)
    if update_mode is UpdateModes.Minimal:
        m.append("".join([await score_format.format_minimal_score(osu_score, beatmap, member), "\n"]))
    else:
        m.append(await score_format.format_new_score(mode, osu_score, beatmap, member))

    # Always add the difference in pp along with the ranks
    m.append(misc_format.format_user_diff(mode, new_osu_user, old_osu_user))

    # Send the message to all guilds
    for guild in member.mutual_guilds:
        channels = misc_utils.get_notify_channels(guild, "score")
        if not channels:
            continue
        member = guild.get_member(int(member_id))

        primary_guild = db.get_linked_osu_profile(int(member_id)).home_guild
        is_primary = True if primary_guild is None else bool(primary_guild == str(guild.id))
        potential_string = score_format.format_potential_pp(score_pp if score_pp is not None
                                                            and not bool(osu_score.legacy_perfect
                                                                         and osu_score.passed)
                                                            else None,
                                                            osu_score)
        embed = embed_format.get_embed_from_template("".join(m), member.color, author_text,
                                                     user_utils.get_user_url(str(new_osu_user.id)),
                                                     new_osu_user.avatar_url, thumbnail_url,
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
    db.update_recent_events(int(member_id), last_user_events, score_id=osu_score.id)