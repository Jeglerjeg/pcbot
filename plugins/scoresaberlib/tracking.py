import asyncio
import logging
from datetime import datetime, timezone

import aiohttp
import discord

import bot
import plugins

from discord.ext import tasks

from plugins.scoresaberlib import db, api
from plugins.scoresaberlib import config
from plugins.scoresaberlib.formatting import score_format, user_format, embed_format
from plugins.scoresaberlib.models.player import ScoreSaberPlayer
from plugins.scoresaberlib.models.score import ScoreSaberScore
from plugins.scoresaberlib.utils import user_utils, misc_utils, score_utils

client = plugins.client  # type: bot.Client

update_interval = config.scoresaber_config.data.get("update_interval", 30)
not_playing_skip = config.scoresaber_config.data.get("update_interval", 5)
score_update_delay = config.scoresaber_config.data.get("score_update_delay", 5)
notify_empty_score = config.scoresaber_config.data.get("notify_empty_score", False)


async def wipe_user(member_id: int):
    """ Deletes user data from tracking. """
    if db.get_scoresaber_user(member_id):
        db.delete_scoresaber_user(member_id)


async def add_new_user(member_id: int, profile: int):
    # Wipe user data to make sure things aren't duplicated
    await wipe_user(member_id)

    current_time = datetime.now(tz=timezone.utc)
    api_user_data = await api.get_full_user_by_id(profile)
    api_user_data.time_cached = current_time
    if api_user_data:
        db.insert_scoresaber_user(api_user_data, member_id)
    else:
        logging.info("Could not retrieve scoresaber info from %s (%s)", member_id, profile)
        return
    return


async def update_scoresaber_user(member_id: int, profile: int, member: discord.Member,
                                 scoresaber_user: ScoreSaberPlayer):
    # Get the user data for the player
    try:
        current_time = datetime.now(tz=timezone.utc)
        api_user_data = await api.get_full_user_by_id(profile)
        api_user_data.time_cached = current_time
        api_user_data.last_pp_notification = scoresaber_user.last_pp_notification
        if api_user_data is None:
            logging.info("Could not retrieve scoresaber info from %s (%s)", member, profile)
            return
        db.update_scoresaber_user(api_user_data, member_id, scoresaber_user.ticks)
    except aiohttp.ServerDisconnectedError:
        return
    except asyncio.TimeoutError:
        logging.warning("Timed out when retrieving scoresaber info from %s (%s)", member, profile)
        return
    except ValueError:
        logging.info("Could not retrieve scoresaber info from %s (%s)", member, profile)
        return


class ScoreSaberTracker:
    def __init__(self):
        self.previous_update = None
        self.time_elapsed = 0
        self.started = None

        self.__tracking_loop.start()

    @tasks.loop(seconds=update_interval)
    async def __tracking_loop(self):
        self.started = datetime.now()

        try:
            member_list = db.get_linked_scoresaber_profiles()
            update_tasks = []
            for linked_profile in member_list:
                # Update the user's data
                update_tasks.append(self.__update_user_data(linked_profile.id, linked_profile.scoresaber_id))
            await asyncio.gather(*update_tasks)
        except KeyError as e:
            logging.exception(e)
            return
        finally:
            self.time_elapsed = (datetime.now() - self.started).total_seconds()
            self.previous_update = datetime.now(tz=timezone.utc)

    @__tracking_loop.before_loop
    async def wait_for_ready(self):
        await client.wait_until_ready()

    async def __notify(self, member_id: int, new_scoresaber_user: ScoreSaberPlayer,
                       old_scoresaber_user: ScoreSaberPlayer = None):
        # Next, check for any differences in pp between the "old" and the "new" subsections
        # and notify any guilds
        if misc_utils.check_for_pp_difference(new_scoresaber_user, old_scoresaber_user):
            await self.__notify_pp(member_id, new_scoresaber_user, old_scoresaber_user)

    async def __update_user_data(self, member_id: int, profile: int):
        """ Go through all registered members playing scoresaber!, and update their data. """
        member = discord.utils.get(client.get_all_members(), id=member_id)
        if not member:
            return

        # Check if the member is tracked, add to cache and tracking if not
        db_user = db.get_scoresaber_user(member_id)
        if not db_user:
            await add_new_user(member_id, profile)
            return

        scoresaber_user = ScoreSaberPlayer(db_user)
        scoresaber_user.add_tick()

        # Only update members not tracked ingame every nth update
        if not user_utils.is_playing(member) and scoresaber_user.ticks % not_playing_skip > 0:
            db.update_scoresaber_user(scoresaber_user, member_id, scoresaber_user.ticks)
            return

        await update_scoresaber_user(member_id, profile, member, scoresaber_user)
        new_scoresaber_user = db.get_scoresaber_user(member_id)
        if not new_scoresaber_user:
            return
        await self.__notify(member_id, ScoreSaberPlayer(new_scoresaber_user), scoresaber_user)

    @staticmethod
    async def __notify_pp(member_id: int, new_scoresaber_user: ScoreSaberPlayer,
                          old_scoresaber_user: ScoreSaberPlayer = None):
        """ Notify any differences in pp and post the scores + rank/pp gained. """
        member = discord.utils.get(client.get_all_members(), id=int(member_id))

        m = []
        thumbnail_url = ""
        scoresaber_scores = []  # type: list[ScoreSaberScore]
        # Since the user got pp they probably have a new score in their own top 100
        # If there is a score, there is also a beatmap
        for i in range(3):
            scoresaber_scores = await score_utils.get_new_score(member_id, new_scoresaber_user)
            if scoresaber_scores:
                break
            await asyncio.sleep(score_update_delay)
        else:
            logging.info("%s (%s) gained PP, but no new score was found.", member.name, member_id)

        if not scoresaber_scores and not notify_empty_score:
            return

        # If a new score was found, format the score(s)
        if len(scoresaber_scores) == 1:
            scoresaber_score = scoresaber_scores[0][0]
            leaderboard_info = scoresaber_scores[0][1]
            thumbnail_url = leaderboard_info.cover_image
            author_text = f"{new_scoresaber_user.name} set a new top score!"

            m.append(f"{score_format.format_new_score(scoresaber_score, leaderboard_info)}\n")
        elif len(scoresaber_scores) > 1:
            m.append(await score_format.get_formatted_score_list(scoresaber_scores,
                                                                 limit=len(scoresaber_scores) if len(scoresaber_scores)
                                                                                                 <= 5 else 5))
            thumbnail_url = new_scoresaber_user.profile_picture
            author_text = f"""{new_scoresaber_user.name} set new best scores"""
        else:
            author_text = new_scoresaber_user.name

        # Always add the difference in pp along with the ranks
        m.append(user_format.format_user_diff(new_scoresaber_user, old_scoresaber_user))

        # Send the message to all guilds
        for guild in member.mutual_guilds:
            channels = misc_utils.get_notify_channels(guild, "score")
            if not channels:
                continue
            member = guild.get_member(int(member_id))

            embed = embed_format.get_embed_from_template("".join(m), member.color, author_text,
                                                         user_utils.get_user_url(new_scoresaber_user.id),
                                                         new_scoresaber_user.profile_picture, thumbnail_url)
            for i, channel in enumerate(channels):
                try:
                    await client.send_message(channel, embed=embed)
                except discord.Forbidden:
                    pass
