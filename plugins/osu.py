""" Plugin for osu! commands

This plugin will notify any registered user's pp difference and if they
set a new best also post that. It also includes many osu! features, such
as a signature generator, pp calculation and user map updates.

TUTORIAL:
    A member with Manage Guild permission must first assign one or more channels
    that the bot should post scores or map updates in.
    See: !help osu config

    Members may link their osu! profile with `!osu link <name ...>`. The bot will
    only keep track of players who either has `osu` in their playing name or as the game in their stream, e.g:
        Playing osu!

    This plugin might send a lot of requests, so keep up to date with the
    !osu debug command.
"""
import copy
import importlib
import asyncio
import logging
import re
import traceback
from datetime import datetime, timedelta, timezone
from textwrap import wrap
from enum import Enum
from typing import List
from operator import itemgetter

import aiohttp
import discord
try:
    import pendulum
except ImportError:
    pendulum = None

import bot
import plugins
from pcbot import Config, utils, Annotate, config as botconfig
from plugins.osulib import api, Mods, calculate_pp, ClosestPPStats, PPStats, ordr
from plugins.twitchlib import twitch

client = plugins.client  # type: bot.Client

# Configuration data for this plugin, including settings for members and the API key
osu_config = Config("osu", pretty=True, data=dict(
    client_id="change to your client ID",
    client_secret="change to your client secret",
    pp_threshold=0.13,  # The amount of pp gain required to post a score
    score_request_limit=100,  # The maximum number of scores to request, between 0-100
    minimum_pp_required=0,  # The minimum pp required to assign a gamemode/profile in general
    use_mentions_in_scores=True,  # Whether the bot will mention people when they set a *score*
    update_interval=30,  # The sleep time in seconds between updates
    not_playing_skip=10,  # Number of rounds between every time someone not playing is updated
    map_event_repeat_interval=6,  # The time in hours before a map event will be treated as "new"
    profiles={},  # Profile setup as member_id: osu_id
    mode={},  # Member's game mode as member_id: gamemode_value
    guild={},  # Guild specific info for score- and map notification channels
    update_mode={},  # Member's notification update mode as member_id: UpdateModes.name
    primary_guild={},  # Member's primary guild; defines where they should be mentioned: member_id: guild_id
    map_cache={},  # Cache for map events, primarily used for calculating and caching pp of the difficulties
    score_update_delay=5,  # Seconds to wait to retry get_new_score if new score is not found
    user_update_delay=2,  # Seconds to wait after updating user data (for ratelimiting purposes)
    leaderboard={},  # A list of users that have turned on/off leaderboard notifications
    opt_in_leaderboard=True,  # Whether or not leaderboard notifications should be opt-in
    notify_empty_scores=False,  # Whether or not to notify pp gain when a score isn't found (only if pp mode is off)
    cache_user_profiles=True,  # Whether or not to cache user profiles when the bot turns off
))

osu_profile_cache = Config("osu_profile_cache", data=dict())
osu_tracking = copy.deepcopy(osu_profile_cache.data)  # Stores tracked osu! users
last_rendered = {}  # Saves when the member last rendered a replay
previous_score_updates = []  # Saves the score IDs of recent map notifications so they don't get posted several times
update_interval = osu_config.data.get("update_interval", 30)
not_playing_skip = osu_config.data.get("not_playing_skip", 10)
time_elapsed = 0  # The registered time it takes to process all information between updates (changes each update)
previous_update = None  # The time osu user data was last updated. None until first update has run
logging_interval = 30  # The time it takes before posting logging information to the console.
no_choke_cache = {}
rank_regex = re.compile(r"#\d+")

pp_threshold = osu_config.data.get("pp_threshold", 0.13)
score_request_limit = osu_config.data.get("score_request_limit", 100)
minimum_pp_required = osu_config.data.get("minimum_pp_required", 0)
use_mentions_in_scores = osu_config.data.get("use_mentions_in_scores", True)
notify_empty_scores = osu_config.data.get("notify_empty_scores", False)
cache_user_profiles = osu_config.data.get("cache_user_profiles", True)

max_diff_length = 23  # The maximum amount of characters in a beatmap difficulty

asyncio.run_coroutine_threadsafe(api.set_oauth_client(osu_config.data.get("client_id"),
                                                      osu_config.data.get("client_secret")), client.loop)
host = "https://osu.ppy.sh/"
rankings_url = "https://osu.ppy.sh/rankings/osu/performance"

recent_map_events = []
event_repeat_interval = osu_config.data.get("map_event_repeat_interval", 6)
timestamp_pattern = re.compile(r"(\d+:\d+:\d+\s(\([0-9,]+\))?\s*)-")


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


class UpdateModes(Enum):
    """ Enums for the various notification update modes.
    Values are valid names in a tuple. """
    Full = ("full", "on", "enabled", "f", "e")
    No_Mention = ("no_mention", "nomention", "silent")
    Minimal = ("minimal", "quiet", "m")
    PP = ("pp", "diff", "p")
    Disabled = ("none", "off", "disabled", "n", "d")

    @classmethod
    def get_mode(cls, mode: str):
        """ Return the mode with the specified name. """
        for enum in cls:
            if mode.lower() in enum.value:
                return enum

        return None


def calculate_acc(mode: api.GameMode, osu_score: dict, exclude_misses: bool = False):
    """ Calculate the accuracy using formulas from https://osu.ppy.sh/wiki/Accuracy """
    # Parse data from the score: 50s, 100s, 300s, misses, katu and geki
    keys = ("count_300", "count_100", "count_50", "count_miss", "count_katu", "count_geki")
    c300, c100, c50, miss, katu, geki = map(int, (osu_score["statistics"][key] for key in keys))

    # Catch accuracy is done a tad bit differently, so we calculate that by itself
    if mode is api.GameMode.fruits:
        total_numbers_of_fruits_caught = c50 + c100 + c300
        total_numbers_of_fruits = miss + c50 + c100 + c300 + katu
        return total_numbers_of_fruits_caught / total_numbers_of_fruits

    total_points_of_hits, total_number_of_hits = 0, 0

    if mode is api.GameMode.osu:
        total_points_of_hits = c50 * 50 + c100 * 100 + c300 * 300
        total_number_of_hits = (0 if exclude_misses else miss) + c50 + c100 + c300
    elif mode is api.GameMode.taiko:
        total_points_of_hits = (miss * 0 + c100 * 0.5 + c300 * 1) * 300
        total_number_of_hits = miss + c100 + c300
    elif mode is api.GameMode.mania:
        # In mania, katu is 200s and geki is MAX
        total_points_of_hits = c50 * 50 + c100 * 100 + katu * 200 + (c300 + geki) * 300
        total_number_of_hits = miss + c50 + c100 + katu + c300 + geki

    return total_points_of_hits / (total_number_of_hits * 300)


def get_leaderboard_update_status(member_id: str):
    """ Return whether or not the user should have leaderboard scores posted automatically. """
    if member_id in osu_config.data["leaderboard"]:
        return osu_config.data["leaderboard"][member_id]

    return not bool(osu_config.data["opt_in_leaderboard"])


def format_mode_name(mode: api.GameMode, short_name: bool = False, abbreviation: bool = False):
    """ Return formatted mode name for user facing modes. """
    name = ""
    if mode is api.GameMode.osu:
        if not short_name:
            name = "osu!"
        elif short_name:
            name = "S"
    elif mode is api.GameMode.mania:
        if not short_name and not abbreviation:
            name = "osu!mania"
        elif short_name:
            name = "M"
        elif abbreviation:
            name = "o!m"
    elif mode is api.GameMode.taiko:
        if not short_name and not abbreviation:
            name = "osu!taiko"
        elif short_name:
            name = "T"
        elif abbreviation:
            name = "o!t"
    elif mode is api.GameMode.fruits:
        if not short_name and not abbreviation:
            name = "osu!catch"
        elif short_name:
            name = "C"
        elif abbreviation:
            name = "o!c"
    return name


def format_user_diff(mode: api.GameMode, data_old: dict, data_new: dict):
    """ Get a bunch of differences and return a formatted string to send.
    iso is the country code. """
    pp_rank = int(data_new["statistics"]["global_rank"]) if data_new["statistics"]["global_rank"] else 0
    pp_country_rank = int(data_new["statistics"]["country_rank"]) if data_new["statistics"]["country_rank"] else 0
    iso = data_new["country"]["code"]
    rank = -int(get_diff(data_old, data_new, "global_rank", statistics=True))
    country_rank = -int(get_diff(data_old, data_new, "country_rank", statistics=True))
    accuracy = get_diff(data_old, data_new, "hit_accuracy", statistics=True)
    pp = get_diff(data_old, data_new, "pp", statistics=True)
    ranked_score = get_diff(data_old, data_new, "ranked_score", statistics=True)

    # Find the performance page number of the respective ranks

    formatted = [f"\u2139`{format_mode_name(mode, abbreviation=True)} "
                 f"{utils.format_number(data_new['statistics']['pp'], 2)}pp "
                 f"{utils.format_number(pp, 2):+}pp`",
                 f" [\U0001f30d]({rankings_url}?page="
                 f"{pp_rank // 50 + 1})`#{pp_rank:,}{'' if int(rank) == 0 else f' {int(rank):+}'}`",
                 f" [{utils.text_to_emoji(iso)}]({rankings_url}?country={iso}&page="
                 f"{pp_country_rank // 50 + 1})`"
                 f"#{pp_country_rank:,}{'' if int(country_rank) == 0 else f' {int(country_rank):+}'}`"]
    rounded_acc = utils.format_number(accuracy, 3)
    if rounded_acc > 0:
        formatted.append("\n\U0001f4c8")  # Graph with upwards trend
    elif rounded_acc < 0:
        formatted.append("\n\U0001f4c9")  # Graph with downwards trend
    else:
        formatted.append("\n\U0001f3af")  # Dart

    formatted.append(f"`{float(data_new['statistics']['hit_accuracy']):.3f}%"
                     f"{'' if rounded_acc == 0 else f' {rounded_acc:+}%'}`")

    formatted.append(f' \U0001f522`{data_new["statistics"]["ranked_score"]:,}'
                     f'{"" if ranked_score == 0 else f" {int(ranked_score):+,}"}`')

    return "".join(formatted)


async def format_stream(member: discord.Member, osu_score: dict, beatmap: dict):
    """ Format the stream url and a VOD button when possible. """
    stream_url = None
    for activity in member.activities:
        if activity and activity.type == discord.ActivityType.streaming and hasattr(activity, "platform") \
                and activity.platform.lower() == "twitch":
            stream_url = activity.url
    if not stream_url:
        return ""

    # Add the stream url and return immediately if twitch is not setup
    text = [f"**[Watch live]({stream_url})**"]
    if not twitch.twitch_client:
        text.append("\n")
        return "".join(text)

    # Try getting the vod information of the current stream
    try:
        twitch_id = await twitch.get_id(member)
        vod_request = await twitch.get_videos(twitch_id)
        assert len(vod_request) >= 1
    except Exception:
        logging.error(traceback.format_exc())
        text.append("\n")
        return "".join(text)

    vod = vod_request[0]

    # Find the timestamp of where the play would have started without pausing the game
    score_created = datetime.fromisoformat(osu_score["created_at"])
    vod_created = vod.created_at
    beatmap_length = int(beatmap["total_length"])

    # Return if the stream was started after the score was set
    if vod_created > score_created:
        text.append("\n")
        return "".join(text)

    # Convert beatmap length when speed mods are enabled
    mods = osu_score["mods"]
    if "DT" in mods or "NC" in mods:
        beatmap_length /= 1.5
    elif "HT" in mods:
        beatmap_length /= 0.75

    # Get the timestamp in the VOD when the score was created
    timestamp_score_created = (score_created - vod_created).total_seconds()
    timestamp_play_started = timestamp_score_created - beatmap_length

    # Add the vod url with timestamp to the formatted text
    text.append(f" | **[`Video of this play`]({vod.url}?t={int(timestamp_play_started)}s)**\n")
    return "".join(text)


async def format_new_score(mode: api.GameMode, osu_score: dict, beatmap: dict, rank: int = None,
                           member: discord.Member = None):
    """ Format any score. There should be a member name/mention in front of this string. """
    if mode is api.GameMode.osu:
        return (
            "[{i}{artist} - {title} [{version}]{i}]({host}beatmapsets/{beatmapset_id}/#{mode}/{beatmap_id})\n"
            "**{pp}pp {stars}\u2605, {rank} {scoreboard_rank}{failed}+{modslist} {score}**"
            "```diff\n"
            "  acc     300s  100s  50s  miss  combo\n"
            "{sign} {acc:<8.2%}{count300:<6}{count100:<6}{count50:<5}{countmiss:<6}{maxcombo}{max_combo}```"
            "{live}"
        ).format(
            host=host,
            beatmap_id=osu_score["beatmap"]["id"],
            beatmapset_id=beatmap["beatmapset_id"],
            mode=osu_score["mode"],
            sign="!" if osu_score["accuracy"] == 1 else ("+" if osu_score["perfect"] and osu_score["passed"] else "-"),
            modslist=Mods.format_mods(osu_score["mods"]),
            acc=osu_score["accuracy"],
            pp=utils.format_number(osu_score["pp"], 2) if "new_pp" not in osu_score else osu_score["new_pp"],
            rank=osu_score["rank"],
            score=f'{osu_score["score"]:,}' if osu_score["score"] else "",
            count300=osu_score["statistics"]["count_300"],
            count100=osu_score["statistics"]["count_100"],
            count50=osu_score["statistics"]["count_50"],
            countmiss=osu_score["statistics"]["count_miss"],
            artist=osu_score["beatmapset"]["artist"].replace("_", r"\_") if bool("beatmapset" in osu_score) else
            beatmap["beatmapset"]["artist"].replace("_", r"\_"),
            title=osu_score["beatmapset"]["title"].replace("_", r"\_") if bool("beatmapset" in osu_score) else
            beatmap["beatmapset"]["title"].replace("_", r"\_"),
            i=("*" if "*" not in osu_score["beatmapset"]["artist"] + osu_score["beatmapset"]["title"] else "") if
            bool("beatmapset" in osu_score) else
            ("*" if "*" not in beatmap["beatmapset"]["artist"] + beatmap["beatmapset"]["title"] else ""),
            # Escaping asterisk doesn't work in italics
            version=beatmap["version"],
            stars=utils.format_number(float(beatmap["difficulty_rating"]), 2),
            maxcombo=osu_score["max_combo"],
            max_combo=f"/{beatmap['max_combo']}" if "max_combo" in beatmap and beatmap["max_combo"] is not None
            else "",
            scoreboard_rank=f"#{rank} " if rank else "",
            failed="(Failed) " if osu_score["passed"] is False and osu_score["rank"] != "F" else "",
            live=await format_stream(member, osu_score, beatmap) if member else "",
        )

    if mode is api.GameMode.taiko:
        return (
            "[{i}{artist} - {title} [{version}]{i}]({host}beatmapsets/{beatmapset_id}/#{mode}/{beatmap_id})\n"
            "**{pp}pp {stars}\u2605, {rank} {scoreboard_rank}{failed}+{modslist} {score}**"
            "```diff\n"
            "  acc     great  good  miss  combo\n"
            "{sign} {acc:<8.2%}{count300:<7}{count100:<6}{countmiss:<6}{maxcombo}{max_combo}```"
            "{live}"
        ).format(
            host=host,
            beatmap_id=osu_score["beatmap"]["id"],
            beatmapset_id=beatmap["beatmapset_id"],
            mode=osu_score["mode"],
            sign="!" if osu_score["accuracy"] == 1 else ("+" if osu_score["perfect"] and osu_score["passed"] else "-"),
            modslist=Mods.format_mods(osu_score["mods"]),
            acc=osu_score["accuracy"],
            pp=utils.format_number(osu_score["pp"], 2),
            rank=osu_score["rank"],
            score=f'{osu_score["score"]:,}' if osu_score["score"] else "",
            count300=osu_score["statistics"]["count_300"],
            count100=osu_score["statistics"]["count_100"],
            countmiss=osu_score["statistics"]["count_miss"],
            artist=osu_score["beatmapset"]["artist"].replace("_", r"\_") if bool("beatmapset" in osu_score) else
            beatmap["beatmapset"]["artist"].replace("_", r"\_"),
            title=osu_score["beatmapset"]["title"].replace("_", r"\_") if bool("beatmapset" in osu_score) else
            beatmap["beatmapset"]["title"].replace("_", r"\_"),
            i=("*" if "*" not in osu_score["beatmapset"]["artist"] + osu_score["beatmapset"]["title"] else "") if
            bool("beatmapset" in osu_score) else
            ("*" if "*" not in beatmap["beatmapset"]["artist"] + beatmap["beatmapset"]["title"] else ""),
            # Escaping asterisk doesn't work in italics
            version=beatmap["version"],
            stars=utils.format_number(float(beatmap["difficulty_rating"]), 2),
            maxcombo=osu_score["max_combo"],
            max_combo=f"/{beatmap['max_combo']}" if "max_combo" in beatmap and beatmap["max_combo"] is not None
            else "",
            scoreboard_rank=f"#{rank} " if rank else "",
            failed="(Failed) " if osu_score["passed"] is False and osu_score["rank"] != "F" else "",
            live=await format_stream(member, osu_score, beatmap) if member else "",
        )

    if mode is api.GameMode.mania:
        return (
            "[{i}{artist} - {title} [{version}]{i}]({host}beatmapsets/{beatmapset_id}/#{mode}/{beatmap_id})\n"
            "**{pp}pp {stars}\u2605, {rank} {scoreboard_rank}{failed}+{modslist} {score}**"
            "```diff\n"
            "  acc     max   300s  200s  100s  50s  miss\n"
            "{sign} {acc:<8.2%}{countmax:<6}{count300:<6}{count200:<6}{count100:<6}{count50:<5}{countmiss:<6}```"
            "{live}"
        ).format(
            host=host,
            beatmap_id=osu_score["beatmap"]["id"],
            beatmapset_id=beatmap["beatmapset_id"],
            mode=osu_score["mode"],
            sign="!" if osu_score["accuracy"] == 1 else ("+" if osu_score["perfect"] and osu_score["passed"] else "-"),
            modslist=Mods.format_mods(osu_score["mods"]),
            acc=osu_score["accuracy"],
            pp=utils.format_number(osu_score["pp"], 2),
            rank=osu_score["rank"],
            score=f'{osu_score["score"]:,}' if osu_score["score"] else "",
            countmax=osu_score["statistics"]["count_geki"],
            count300=osu_score["statistics"]["count_300"],
            count200=osu_score["statistics"]["count_katu"],
            count100=osu_score["statistics"]["count_100"],
            count50=osu_score["statistics"]["count_50"],
            countmiss=osu_score["statistics"]["count_miss"],
            artist=osu_score["beatmapset"]["artist"].replace("_", r"\_") if bool("beatmapset" in osu_score) else
            beatmap["beatmapset"]["artist"].replace("_", r"\_"),
            title=osu_score["beatmapset"]["title"].replace("_", r"\_") if bool("beatmapset" in osu_score) else
            beatmap["beatmapset"]["title"].replace("_", r"\_"),
            i=("*" if "*" not in osu_score["beatmapset"]["artist"] + osu_score["beatmapset"]["title"] else "") if
            bool("beatmapset" in osu_score) else
            ("*" if "*" not in beatmap["beatmapset"]["artist"] + beatmap["beatmapset"]["title"] else ""),
            # Escaping asterisk doesn't work in italics
            version=beatmap["version"],
            stars=utils.format_number(float(beatmap["difficulty_rating"]), 2),
            scoreboard_rank=f"#{rank} " if rank else "",
            failed="(Failed) " if osu_score["passed"] is False and osu_score["rank"] != "F" else "",
            live=await format_stream(member, osu_score, beatmap) if member else "",
        )

    if mode is api.GameMode.fruits:
        return (
            "[{i}{artist} - {title} [{version}]{i}]({host}beatmapsets/{beatmapset_id}/#{mode}/{beatmap_id})\n"
            "**{pp}pp {stars}\u2605, {rank} {scoreboard_rank}{failed}+{modslist} {score}**"
            "```diff\n"
            "  acc     fruits ticks drpmiss miss combo\n"
            "{sign} {acc:<8.2%}{count300:<7}{count100:<6}{countdrpmiss:<8}{countmiss:<5}{maxcombo}{max_combo}```"
            "{live}"
        ).format(
            host=host,
            beatmap_id=osu_score["beatmap"]["id"],
            beatmapset_id=beatmap["beatmapset_id"],
            mode=osu_score["mode"],
            sign="!" if osu_score["accuracy"] == 1 else ("+" if osu_score["perfect"] and osu_score["passed"] else "-"),
            modslist=Mods.format_mods(osu_score["mods"]),
            acc=osu_score["accuracy"],
            pp=utils.format_number(osu_score["pp"], 2),
            rank=osu_score["rank"],
            score=f'{osu_score["score"]:,}' if osu_score["score"] else "",
            count300=osu_score["statistics"]["count_300"],
            count100=osu_score["statistics"]["count_100"],
            countdrpmiss=osu_score["statistics"]["count_katu"],
            countmiss=osu_score["statistics"]["count_miss"],
            artist=osu_score["beatmapset"]["artist"].replace("_", r"\_") if bool("beatmapset" in osu_score) else
            beatmap["beatmapset"]["artist"].replace("_", r"\_"),
            title=osu_score["beatmapset"]["title"].replace("_", r"\_") if bool("beatmapset" in osu_score) else
            beatmap["beatmapset"]["title"].replace("_", r"\_"),
            i=("*" if "*" not in osu_score["beatmapset"]["artist"] + osu_score["beatmapset"]["title"] else "") if
            bool("beatmapset" in osu_score) else
            ("*" if "*" not in beatmap["beatmapset"]["artist"] + beatmap["beatmapset"]["title"] else ""),
            # Escaping asterisk doesn't work in italics
            version=beatmap["version"],
            stars=utils.format_number(float(beatmap["difficulty_rating"]), 2),
            maxcombo=osu_score["max_combo"],
            max_combo=f"/{beatmap['max_combo']}" if "max_combo" in beatmap and beatmap["max_combo"] is not None
            else "",
            scoreboard_rank=f"#{rank} " if rank else "",
            failed="(Failed) " if osu_score["passed"] is False and osu_score["rank"] != "F" else "",
            live=await format_stream(member, osu_score, beatmap) if member else "",
        )


async def format_minimal_score(mode: api.GameMode, osu_score: dict, beatmap: dict, rank: int, member: discord.Member):
    """ Format any osu! score with minimal content.
    There should be a member name/mention in front of this string. """
    acc = calculate_acc(mode, osu_score)
    return (
        "[*{artist} - {title} [{version}]*]({host}beatmapsets/{beatmapset_id}/#{mode}/{beatmap_id})\n"
        "**{pp}pp {stars}\u2605, {maxcombo}{max_combo} {rank} {acc:.2%} {scoreboard_rank}+{mods}**"
        "{live}"
    ).format(
        host=host,
        beatmapset_id=beatmap["beatmapset_id"],
        mode=osu_score["mode"],
        mods=Mods.format_mods(osu_score["mods"]),
        acc=acc,
        beatmap_id=osu_score["beatmap"]["id"],
        artist=beatmap["beatmapset"]["artist"].replace("*", r"\*").replace("_", r"\_"),
        title=beatmap["beatmapset"]["title"].replace("*", r"\*").replace("_", r"\_"),
        version=beatmap["version"],
        maxcombo=osu_score["max_combo"],
        max_combo=f"/{beatmap['max_combo']}" if "max_combo" in beatmap and beatmap["max_combo"] is not None
        else "",
        rank=osu_score["rank"],
        stars=utils.format_number(float(beatmap["difficulty_rating"]), 2),
        scoreboard_rank=f"#{rank} " if rank else "",
        live=await format_stream(member, osu_score, beatmap),
        pp=utils.format_number(osu_score["pp"], 2)
    )


def updates_per_log():
    """ Returns the amount of updates needed before logging interval is met. """
    return logging_interval // (update_interval / 60)


def get_primary_guild(member_id: str):
    """ Return the primary guild for a member or None. """
    return osu_config.data["primary_guild"].get(member_id, None)


def get_mode(member_id: str):
    """ Return the api.GameMode for the member with this id. """
    if member_id not in osu_config.data["mode"]:
        mode = api.GameMode.osu
        return mode

    value = int(osu_config.data["mode"][member_id])
    mode = api.GameMode(value)
    return mode


def get_update_mode(member_id: str):
    """ Return the member's update mode. """
    if member_id not in osu_config.data["update_mode"]:
        return UpdateModes.Full

    return UpdateModes.get_mode(osu_config.data["update_mode"][member_id])


def get_user_url(member_id: str):
    """ Return the user website URL. """
    user_id = osu_config.data["profiles"][member_id]

    return "".join([host, "users/", user_id])


def get_formatted_score_time(osu_score: dict):
    """ Returns formatted time since score was set. """
    time_string = None
    if pendulum:
        score_time = pendulum.now("UTC").diff(pendulum.parse(osu_score["created_at"]))
        if score_time.in_seconds() < 60:
            time_string = f"""{"".join([str(score_time.in_seconds()),
                                        (" seconds" if score_time.in_seconds() > 1 else " second")])} ago"""
        elif score_time.in_minutes() < 60:
            time_string = f"""{"".join([str(score_time.in_minutes()),
                                        (" minutes" if score_time.in_minutes() > 1 else " minute")])} ago"""
        elif score_time.in_hours() < 24:
            time_string = f"""{"".join([str(score_time.in_hours()),
                                        (" hours" if score_time.in_hours() > 1 else " hour")])} ago"""
        elif score_time.in_days() <= 31:
            time_string = f"""{"".join([str(score_time.in_days()),
                                        (" days" if score_time.in_days() > 1 else " day")])} ago"""
        elif score_time.in_months() < 12:
            time_string = f"""{"".join([str(score_time.in_months()),
                                        (" months" if score_time.in_months() > 1 else " month")])} ago"""
        else:
            time_string = f"""{"".join([str(score_time.in_years()),
                                        (" years" if score_time.in_years() > 1 else " year")])} ago"""

    return time_string


def get_beatmap_sr(score_pp: PPStats, beatmap: dict, mods: str):
    """ Change beatmap SR if using SR adjusting mods. """
    difficulty_rating = score_pp.stars if (mods not in ("Nomod", "HD", "FL", "TD", "ScoreV2", "NF", "SD", "PF", "RX")
                                           or not beatmap["convert"]) and score_pp else beatmap["difficulty_rating"]
    return difficulty_rating


def format_potential_pp(score_pp: PPStats, osu_score: dict):
    """ Formats potential PP for scores. """
    if score_pp is not None and score_pp.max_pp is not None and score_pp.max_pp - osu_score["pp"] > 1\
            and not osu_score["perfect"]:
        potential_string = f"Potential: {utils.format_number(score_pp.max_pp, 2):,}pp, " \
                           f"{utils.format_number(score_pp.max_pp - osu_score['pp'], 2):+}pp"
    else:
        potential_string = None
    return potential_string


def is_playing(member: discord.Member):
    """ Check if a member has "osu!" in their Game name. """
    # See if the member is playing
    for activity in member.activities:
        if activity is not None and activity.name is not None:
            if "osu!" in activity.name.lower():
                return True
            if activity == discord.ActivityType.streaming and "osu!" in activity.game.lower():
                return True

    return False


def get_no_choke_scorerank(mods: list, acc: float):
    """ Get the scorerank of an unchoked play. """
    if ("HD" in mods or "FL" in mods) and acc == 1:
        scorerank = "XH"
    elif "HD" in mods or "FL" in mods:
        scorerank = "SH"
    elif acc == 1:
        scorerank = "X"
    else:
        scorerank = "S"
    return scorerank


async def retrieve_osu_scores(profile: str, mode: api.GameMode, timestamp: str):
    """ Retrieves"""
    params = {
        "mode": mode.name,
        "limit": score_request_limit,
    }
    fetched_scores = await api.get_user_scores(profile, "best", params=params)
    if fetched_scores is not None:
        for i, osu_score in enumerate(fetched_scores):
            osu_score["pos"] = i + 1
            del osu_score["beatmapset"]
            del osu_score["user"]
        user_scores = (dict(score_list=fetched_scores, time_updated=timestamp))
    else:
        user_scores = None
    return user_scores


async def update_user_data(member_id: str, profile: str):
    """ Go through all registered members playing osu!, and update their data. """
    # Go through each member playing and give them an "old" and a "new" subsection
    # for their previous and latest user data
    # Skip members who disabled tracking

    if get_update_mode(member_id) is UpdateModes.Disabled:
        return

    # Check if bot can see member and that profile exists on file (might have been unlinked or changed during iteration)
    member = discord.utils.get(client.get_all_members(), id=int(member_id))
    if member is None or member_id not in osu_config.data["profiles"] \
            or profile not in osu_config.data["profiles"][member_id] or (member_id in osu_tracking and
                                                                         str(osu_tracking[member_id]["new"]["id"])
                                                                         not in osu_config.data["profiles"][member_id]):
        if member_id in osu_tracking:
            del osu_tracking[member_id]
        return

    # Check if the member is tracked, add to cache and tracking if not
    if member_id not in osu_tracking:
        osu_tracking[member_id] = {}
        if cache_user_profiles:
            osu_profile_cache.data[member_id] = {}

    # Add update ticks to member tracking
    if "ticks" not in osu_tracking[member_id]:
        osu_tracking[member_id]["ticks"] = -1

    osu_tracking[member_id]["member"] = member
    osu_tracking[member_id]["ticks"] += 1

    # Only update members not tracked ingame every nth update
    if not is_playing(member) and osu_tracking[member_id]["ticks"] % not_playing_skip > 0:
        # Update their old data to match their new one in order to avoid duplicate posts
        if "new" in osu_tracking[member_id]:
            osu_tracking[member_id]["old"] = osu_tracking[str(member_id)]["new"]
        return

    # Get the user data for the player
    fetched_scores = None
    current_time = datetime.now(tz=timezone.utc).isoformat()
    mode = get_mode(member_id)
    try:
        params = {
            "key": "id"
        }
        user_data = await api.get_user(profile, mode.name, params=params)

        params = {
            "limit": 20
        }
        user_recent = await api.get_user_recent_activity(profile, params=params)

        # User is already tracked
        if "scores" not in osu_tracking[member_id]:
            fetched_scores = await retrieve_osu_scores(profile, mode, current_time)
    except aiohttp.ServerDisconnectedError:
        return
    except asyncio.TimeoutError:
        logging.warning("Timed out when retrieving osu! info from %s (%s)", member, profile)
        return
    except ValueError:
        logging.info("Could not retrieve osu! info from %s (%s)", member, profile)
        return
    except Exception:
        logging.error(traceback.format_exc())
        return
    if user_recent is None or user_data is None:
        logging.info("Could not retrieve osu! info from %s (%s)", member, profile)
        return
    # Update the "new" data
    if "scores" not in osu_tracking[member_id] and fetched_scores is not None:
        osu_tracking[member_id]["scores"] = fetched_scores
        if cache_user_profiles:
            osu_profile_cache.data[member_id]["scores"] = fetched_scores
    if "new" in osu_tracking[member_id]:
        # Move the "new" data into the "old" data of this user
        osu_tracking[member_id]["old"] = osu_tracking[member_id]["new"]

    osu_tracking[member_id]["new"] = user_data
    osu_tracking[member_id]["new"]["time_updated"] = current_time
    osu_tracking[member_id]["new"]["events"] = user_recent
    if cache_user_profiles:
        osu_profile_cache.data[member_id]["new"] = osu_tracking[member_id]["new"]
    await asyncio.sleep(osu_config.data["user_update_delay"])


async def calculate_no_choke_top_plays(osu_scores: dict, member_id: str):
    """ Calculates and returns a new list of unchoked plays. """
    mode = api.GameMode.osu
    no_choke_list = []
    if member_id not in no_choke_cache or (member_id in no_choke_cache and no_choke_cache[member_id]["time_updated"]
                                           < datetime.fromisoformat(osu_scores["time_updated"])):
        for osu_score in osu_scores["score_list"]:
            if osu_score["perfect"]:
                continue
            full_combo_acc = calculate_acc(mode, osu_score, exclude_misses=True)
            score_pp = await get_score_pp(osu_score, mode)
            if (score_pp.max_pp - osu_score["pp"]) > 10:
                osu_score["new_pp"] = f"""{utils.format_number(osu_score["pp"], 2)} => {utils.format_number(
                    score_pp.max_pp, 2)}"""
                osu_score["pp"] = score_pp.max_pp
                osu_score["perfect"] = True
                osu_score["accuracy"] = full_combo_acc
                osu_score["max_combo"] = score_pp.max_combo
                osu_score["statistics"]["count_miss"] = 0
                osu_score["rank"] = get_no_choke_scorerank(osu_score["mods"], full_combo_acc)
                osu_score["score"] = None
                no_choke_list.append(osu_score)
        no_choke_list.sort(key=itemgetter("pp"), reverse=True)
        for i, osu_score in enumerate(no_choke_list):
            osu_score["pos"] = i + 1
        no_choke_cache[member_id] = dict(score_list=no_choke_list, time_updated=datetime.now(tz=timezone.utc))
        no_chokes = no_choke_cache[member_id]
    else:
        no_chokes = no_choke_cache[member_id]
    return no_chokes


async def get_new_score(member_id: str):
    """ Compare old user scores with new user scores and return the discovered
    new score if there is any. When a score is returned, it's position in the
    player's top plays can be retrieved with score["pos"]. """
    # Download a list of the user's scores
    profile = osu_config.data["profiles"][member_id]
    mode = get_mode(member_id)
    try:
        user_scores = await retrieve_osu_scores(profile, mode, datetime.now(tz=timezone.utc).isoformat())
    except aiohttp.ServerDisconnectedError:
        return None
    except asyncio.TimeoutError:
        logging.warning("Timed out when retrieving osu! scores from %s (%s)", member_id, profile)
        return None
    except ValueError:
        logging.info("Could not retrieve osu! scores from %s (%s)", member_id, profile)
        return None
    except Exception:
        logging.error(traceback.format_exc())
        return None
    if user_scores is None:
        return None
    new_scores = []
    # Compare the scores from top to bottom and try to find a new one
    for i, osu_score in enumerate(user_scores["score_list"]):
        if datetime.fromisoformat(osu_tracking[member_id]["scores"]["time_updated"]) <\
                datetime.fromisoformat(osu_score["created_at"]):
            if i == 0:
                logging.info("a #1 score was set: check plugins.osu.osu_tracking['%s']['debug']", member_id)
                osu_tracking[member_id]["debug"] = dict(scores=user_scores,
                                                        old_scores=osu_tracking[member_id]["scores"],
                                                        old=dict(osu_tracking[member_id]["old"]),
                                                        new=dict(osu_tracking[member_id]["new"]))

            # Calculate the difference in pp from the score below
            if i < len(user_scores["score_list"]) - 2:
                pp = float(osu_score["pp"])
                diff = pp - float(user_scores["score_list"][i + 1]["pp"])
            else:
                diff = 0
            new_scores.append(dict(osu_score, diff=diff))
    if new_scores:
        osu_tracking[member_id]["scores"] = user_scores
        if cache_user_profiles:
            osu_profile_cache.data[member_id]["scores"] = user_scores
    return new_scores


async def get_formatted_score_list(member: discord.Member, osu_scores: list, limit: int, no_time: bool = False):
    """ Return a list of formatted scores along with time since the score was set. """
    mode = get_mode(str(member.id))
    m = []
    for i, osu_score in enumerate(osu_scores):
        if i > limit - 1:
            break
        params = {
            "beatmap_id": osu_score["beatmap"]["id"]
        }
        mods = Mods.format_mods(osu_score["mods"])
        beatmap = (await api.beatmap_lookup(params=params, map_id=osu_score["beatmap"]["id"], mode=mode.name))
        score_pp = await get_score_pp(osu_score, mode, beatmap)
        if score_pp is not None:
            beatmap["difficulty_rating"] = get_beatmap_sr(score_pp, beatmap, mods)
        if ("max_combo" not in beatmap or not beatmap["max_combo"]) and score_pp and score_pp.max_combo:
            beatmap["max_combo"] = score_pp.max_combo

        # Add time since play to the score
        score_datetime = datetime.fromisoformat(osu_score["created_at"])
        time_since_string = f"<t:{int(score_datetime.timestamp())}:R>"

        # Add score position to the score
        pos = osu_score["pos"] if "diff" not in osu_score else f"{osu_score['pos']}. " \
                                                               f"({utils.format_number(osu_score['diff'], 2):+}pp)"
        position_string = f"{pos}."

        # Add potential pp to the score
        potential_string = format_potential_pp(score_pp, osu_score)

        m.append("".join([f"{position_string}\n", await format_new_score(mode, osu_score, beatmap),
                          ("".join([potential_string, "\n"]) if potential_string is not None else ""),
                          "".join([time_since_string, "\n"]) if not no_time else "",
                          "\n" if not i == limit - 1 else ""]))
    return "".join(m)


def get_diff(old: dict, new: dict, value: str, statistics=False):
    """ Get the difference between old and new osu! user data. """
    if statistics:
        new_value = float(new["statistics"][value]) if new["statistics"][value] else 0.0
        old_value = float(old["statistics"][value]) if old["statistics"][value] else 0.0
    else:
        new_value = float(new[value]) if new[value] else 0.0
        old_value = float(old[value]) if old[value] else 0.0

    return new_value - old_value


def get_notify_channels(guild: discord.Guild, data_type: str):
    """ Find the notifying channel or return the guild. """
    if str(guild.id) not in osu_config.data["guild"]:
        return None

    if "".join([data_type, "-channels"]) not in osu_config.data["guild"][str(guild.id)]:
        return None

    return [guild.get_channel(int(s)) for s in osu_config.data["guild"][str(guild.id)]["".join([data_type,
                                                                                                "-channels"])]
            if guild.get_channel(int(s))]


async def get_score_pp(osu_score: dict, mode: api.GameMode, beatmap: dict = None):
    """ Return PP for a given score. """
    mods = Mods.format_mods(osu_score["mods"])
    score_pp = None
    if beatmap and beatmap["convert"]:
        return score_pp
    if mode is api.GameMode.osu:
        try:
            score_pp = await calculate_pp(int(osu_score["beatmap"]["id"]), mode=mode,
                                          ignore_osu_cache=not bool(beatmap["status"] == "ranked"
                                                                    or beatmap["status"] == "approved") if beatmap
                                          else False,
                                          *"{modslist}{acc:.2%} {potential_acc:.2%}pot {c300}x300 {c100}x100 {c50}x50 "
                                           "{countmiss}m {maxcombo}x {objects}objects"
                                          .format(acc=calculate_acc(mode, osu_score),
                                                  potential_acc=calculate_acc(mode, osu_score, exclude_misses=True),
                                                  c300=osu_score["statistics"]["count_300"],
                                                  c100=osu_score["statistics"]["count_100"],
                                                  c50=osu_score["statistics"]["count_50"],
                                                  modslist="".join(["+", mods, " "]) if mods != "Nomod" else "",
                                                  countmiss=osu_score["statistics"]["count_miss"],
                                                  maxcombo=osu_score["max_combo"],
                                                  objects=osu_score["statistics"]["count_300"] +
                                                  osu_score["statistics"]["count_100"] +
                                                  osu_score["statistics"]["count_50"] +
                                                  osu_score["statistics"]["count_miss"]).split())
        except Exception:
            logging.error(traceback.format_exc())

    elif mode is api.GameMode.taiko:
        try:
            score_pp = await calculate_pp(int(osu_score["beatmap"]["id"]), mode=mode,
                                          ignore_osu_cache=not bool(beatmap["status"] == "ranked"
                                                                    or beatmap["status"] == "approved") if beatmap
                                          else False,
                                          *"{modslist}{acc:.2%} {c300}x300 {c100}x100 "
                                           "{countmiss}m {maxcombo}x {objects}objects"
                                          .format(acc=calculate_acc(mode, osu_score),
                                                  c300=osu_score["statistics"]["count_300"],
                                                  c100=osu_score["statistics"]["count_100"],
                                                  modslist="".join(["+", mods, " "]) if mods != "Nomod" else "",
                                                  countmiss=osu_score["statistics"]["count_miss"],
                                                  maxcombo=osu_score["max_combo"],
                                                  objects=osu_score["statistics"]["count_300"] +
                                                  osu_score["statistics"]["count_100"] +
                                                  osu_score["statistics"]["count_miss"]).split())
        except Exception:
            logging.error(traceback.format_exc())

    elif mode is api.GameMode.mania:
        try:
            score_pp = await calculate_pp(int(osu_score["beatmap"]["id"]), mode=mode,
                                          ignore_osu_cache=not bool(beatmap["status"] == "ranked"
                                                                    or beatmap["status"] == "approved") if beatmap
                                          else False,
                                          *"{modslist} {score}score {objects}objects"
                                          .format(modslist="".join(["+", mods, " "]) if mods != "Nomod" else "",
                                                  score=osu_score["score"],
                                                  objects=osu_score["statistics"]["count_300"] +
                                                  osu_score["statistics"]["count_geki"] +
                                                  osu_score["statistics"]["count_katu"] +
                                                  osu_score["statistics"]["count_100"] +
                                                  osu_score["statistics"]["count_miss"]).split())
        except Exception:
            logging.error(traceback.format_exc())

    elif mode is api.GameMode.fruits:
        try:
            score_pp = await calculate_pp(int(osu_score["beatmap"]["id"]), mode=mode,
                                          ignore_osu_cache=not bool(beatmap["status"] == "ranked"
                                                                    or beatmap["status"] == "approved") if beatmap
                                          else False,
                                          *"{modslist}{c300}x300 {c100}x100 {c50}x50 {dropmiss}dropmiss "
                                           "{countmiss}m {maxcombo}x"
                                          .format(c300=osu_score["statistics"]["count_300"],
                                                  c100=osu_score["statistics"]["count_100"],
                                                  c50=osu_score["statistics"]["count_50"],
                                                  dropmiss=osu_score["statistics"]["count_katu"],
                                                  modslist="".join(["+", mods, " "]) if mods != "Nomod" else "",
                                                  countmiss=osu_score["statistics"]["count_miss"],
                                                  maxcombo=osu_score["max_combo"]).split())
        except Exception:
            logging.error(traceback.format_exc())
    return score_pp


def get_sorted_scores(osu_scores: dict, list_type: str):
    """ Sort scores by newest or oldest scores. """
    if list_type == "oldest":
        sorted_scores = sorted(osu_scores["score_list"], key=itemgetter("created_at"))
    elif list_type == "newest":
        sorted_scores = sorted(osu_scores["score_list"], key=itemgetter("created_at"), reverse=True)
    elif list_type == "acc":
        sorted_scores = sorted(osu_scores["score_list"], key=itemgetter("accuracy"), reverse=True)
    elif list_type == "combo":
        sorted_scores = sorted(osu_scores["score_list"], key=itemgetter("max_combo"), reverse=True)
    elif list_type == "score":
        sorted_scores = sorted(osu_scores["score_list"], key=itemgetter("score"), reverse=True)
    else:
        sorted_scores = osu_scores["score_list"]
    return dict(score_list=sorted_scores, time_updated=osu_scores["time_updated"])


def get_formatted_score_embed(member: discord.Member, osu_score: dict, formatted_score: str, pp_stats: PPStats):
    """ Return a formatted score as an embed """
    embed = discord.Embed(color=member.color, url=get_user_url(str(member.id)))
    embed.description = formatted_score
    footer = []

    # Add potential pp in the footer
    potential_string = format_potential_pp(pp_stats, osu_score)
    if potential_string:
        footer.append(potential_string)

    # Add completion rate to footer if score is failed
    if osu_score and pp_stats and osu_score["passed"] is False and osu_score["mode"] != "fruits":
        if osu_score["mode"] == "osu":
            objects = (osu_score["statistics"]["count_300"] + osu_score["statistics"]["count_100"] +
                       osu_score["statistics"]["count_50"] + osu_score["statistics"]["count_miss"])
            beatmap_objects = (osu_score["beatmap"]["count_circles"] + osu_score["beatmap"]["count_sliders"] +
                               osu_score["beatmap"]["count_spinners"])
        elif osu_score["mode"] == "taiko":
            objects = (osu_score["statistics"]["count_300"] + osu_score["statistics"]["count_100"] +
                       osu_score["statistics"]["count_miss"])
            beatmap_objects = (osu_score["beatmap"]["count_circles"] + osu_score["beatmap"]["count_sliders"] +
                               osu_score["beatmap"]["count_spinners"])
        else:
            objects = (osu_score["statistics"]["count_300"] + osu_score["statistics"]["count_geki"] +
                       osu_score["statistics"]["count_katu"] + osu_score["statistics"]["count_100"] +
                       osu_score["statistics"]["count_miss"])
            beatmap_objects = (osu_score["beatmap"]["count_circles"] + osu_score["beatmap"]["count_sliders"] +
                               osu_score["beatmap"]["count_spinners"])
        footer.append(f"\nCompletion rate: {(objects / beatmap_objects) * 100:.2f}% "
                      f"({utils.format_number(pp_stats.partial_stars, 2)}\u2605)")

    embed.set_footer(text="".join(footer))
    return embed


async def notify_pp(member_id: str, data: dict):
    """ Notify any differences in pp and post the scores + rank/pp gained. """
    # Only update pp when there is actually a difference
    if "old" not in data:
        return

    # Get the difference in pp since the old data
    old, new = data["old"], data["new"]
    pp_diff = get_diff(old, new, "pp", statistics=True)

    # If the difference is too small or nothing, move on
    if pp_threshold > pp_diff > -pp_threshold:
        return

    member = data["member"]
    mode = get_mode(member_id)
    update_mode = get_update_mode(member_id)
    m = []
    score_pp = None
    thumbnail_url = None
    osu_score = None
    osu_scores = []  # type: list
    # Since the user got pp they probably have a new score in their own top 100
    # If there is a score, there is also a beatmap
    if update_mode is not UpdateModes.PP:
        for i in range(3):
            osu_scores = await get_new_score(member_id)
            if osu_scores:
                break
            await asyncio.sleep(osu_config.data["score_update_delay"])
        else:
            logging.info("%s gained PP, but no new score was found.", member_id)
            if not notify_empty_scores:
                return
    for osu_score in list(osu_scores):
        if osu_score["best_id"] in previous_score_updates:
            osu_scores.remove(osu_score)
            continue
        previous_score_updates.append(osu_score["best_id"])
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
        score_pp = await get_score_pp(osu_score, mode, beatmap)
        mods = Mods.format_mods(osu_score["mods"])
        beatmap["difficulty_rating"] = get_beatmap_sr(score_pp, beatmap, mods)
        if ("max_combo" not in beatmap or not beatmap["max_combo"]) and score_pp.max_combo:
            beatmap["max_combo"] = score_pp.max_combo
        if update_mode is UpdateModes.Minimal:
            m.append("".join([await format_minimal_score(mode, osu_score, beatmap, scoreboard_rank, member), "\n"]))
        else:
            m.append(await format_new_score(mode, osu_score, beatmap, scoreboard_rank, member))
    elif len(osu_scores) > 1:
        for osu_score in list(osu_scores):
            # There might not be any events
            osu_score["scoreboard_rank"] = None
            if new["events"]:
                osu_score["scoreboard_rank"] = api.rank_from_events(new["events"],
                                                                    str(osu_score["beatmap"]["id"]), osu_score)
        m.append(await get_formatted_score_list(member, osu_scores,
                                                limit=len(osu_scores) if len(osu_scores) <= 5 else 5, no_time=True))
        thumbnail_url = data["new"]["avatar_url"]
        author_text = f"""{data["new"]["username"]} set new best scores"""
    else:
        author_text = data["new"]["username"]

    # Always add the difference in pp along with the ranks
    m.append(format_user_diff(mode, old, new))

    # Send the message to all guilds
    for guild in member.mutual_guilds:
        channels = get_notify_channels(guild, "score")
        if not channels:
            continue
        member = guild.get_member(int(member_id))

        primary_guild = get_primary_guild(str(member.id))
        is_primary = True if primary_guild is None else bool(primary_guild == str(guild.id))
        if len(osu_scores) <= 1:
            embed = get_formatted_score_embed(member, osu_score, "".join(m), score_pp if score_pp is not None
                                              and not bool(osu_score["perfect"] and osu_score["passed"]) else None)
        else:
            embed = discord.Embed(color=member.color)
            embed.description = "".join(m)
        if osu_scores:
            embed.set_thumbnail(url=thumbnail_url)
        embed.set_author(name=author_text, icon_url=data["new"]["avatar_url"], url=get_user_url(str(member.id)))

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


def get_missing_user_string(member: discord.Member):
    """ Format missing user text for all commands needing it. """
    return f"No osu! profile assigned to **{member.name}**! Please assign a profile using " \
           f"**{botconfig.guild_command_prefix(member.guild)}osu link <username>**"


def get_user(message: discord.Message, username: str):
    """ Get member by discord username or osu username. """
    member = utils.find_member(guild=message.guild, name=username)
    if not member:
        for key, value in osu_tracking.items():
            if value["new"]["username"].lower() == username.lower():
                member = discord.utils.get(message.guild.members, id=int(key))
    return member


async def format_beatmapset_diffs(beatmapset: dict):
    """ Format some difficulty info on a beatmapset. """
    # Get the longest difficulty name
    diff_length = len(max((diff["version"] for diff in beatmapset["beatmaps"]), key=len))
    if diff_length > max_diff_length:
        diff_length = max_diff_length
    elif diff_length < len("difficulty"):
        diff_length = len("difficulty")

    m = ["```elm\n"
         f"M {'Difficulty': <{diff_length}}  Stars  Drain  PP"]

    for diff in sorted(beatmapset["beatmaps"], key=lambda d: float(d["difficulty_rating"])):
        diff_name = diff["version"]
        m.append("\n{gamemode: <2}{name: <{diff_len}}  {stars: <7}{drain: <7}{pp}".format(
            gamemode=format_mode_name(api.GameMode(int(diff["mode_int"])), short_name=True),
            name=diff_name if len(diff_name) < max_diff_length else diff_name[:max_diff_length - 3] + "...",
            diff_len=diff_length,
            stars=f"{utils.format_number(float(diff['difficulty_rating']), 2)}\u2605",
            pp=f"{int(diff.get('pp', '0'))}pp",
            drain="{}:{:02}".format(*divmod(int(diff["hit_length"] / diff["clock_rate"]), 60)))
        )
    m.append("```")
    return "".join(m)


async def format_beatmap_info(diff: dict, mods: str):
    """ Format some difficulty info on a beatmapset. """
    # Get the longest difficulty name
    diff_length = len(diff["version"])
    if diff_length > max_diff_length:
        diff_length = max_diff_length
    elif diff_length < len("difficulty"):
        diff_length = len("difficulty")

    m = [f"```elm\n{'Difficulty': <{diff_length}}  Drain  BPM  Passrate"]

    diff_name = diff["version"]
    pass_rate = "Not passed"
    if not diff["passcount"] == 0 and not diff["playcount"] == 0:
        pass_rate = f"{(diff['passcount'] / diff['playcount']) * 100:.2f}%"

    m.append("\n{name: <{diff_len}}  {drain: <7}{bpm: <5}{passrate}\n\n"
             "OD   CS   AR   HP   Max Combo  Mode\n"
             "{od: <5}{cs: <5}{ar: <5}{hp: <5}{maxcombo: <11}{mode_name}\n\n"
             "Total PP   Total Stars   Mods\n"
             "{pp: <11}{stars: <14}{mods}".format(
              name=diff_name if len(diff_name) < max_diff_length else diff_name[:max_diff_length - 3] + "...",
              diff_len=diff_length,
              stars=f"{utils.format_number(float(diff['difficulty_rating']), 2)}\u2605",
              pp=f"{int(diff.get('pp', '0'))}pp",
              drain="{}:{:02}".format(*divmod(int(diff["hit_length"] / diff["clock_rate"]), 60)),
              passrate=pass_rate,
              od=utils.format_number(float(diff["accuracy"]), 1),
              ar=utils.format_number(float(diff["ar"]), 1),
              hp=utils.format_number(float(diff["drain"]), 1),
              cs=utils.format_number(float(diff["cs"]), 1),
              bpm=int(diff["bpm"] * diff["clock_rate"]) if diff["bpm"] and diff["clock_rate"] else "None",
              maxcombo=f"{diff['max_combo']}x" if diff["max_combo"] else "None",
              mode_name=format_mode_name(api.GameMode.get_mode(diff["mode"])),
              mods=mods.upper() if not mods == "+Nomod" else mods
             ))

    m.append("```")
    return "".join(m)


async def format_map_status(member: discord.Member, status_format: str, beatmapset: dict, minimal: bool,
                            user_update: bool = True, mods: str = "+Nomod"):
    """ Format the status update of a beatmap. """
    if user_update:
        user_id = osu_config.data["profiles"][str(member.id)]
        name = member.display_name
    else:
        user_id = beatmapset["user_id"]
        name = beatmapset["creator"]
    status = [status_format.format(name=name, user_id=user_id, host=host, artist=beatmapset["artist"],
                                   title=beatmapset["title"], id=beatmapset["id"])]
    if not minimal:
        beatmap = bool(len(beatmapset["beatmaps"]) == 1)
        if not beatmap:
            status.append(await format_beatmapset_diffs(beatmapset))
        else:
            status.append(await format_beatmap_info(beatmapset["beatmaps"][0], mods))

    embed = discord.Embed(color=member.color, description="".join(status))
    embed.set_image(url=beatmapset["covers"]["cover@2x"])
    return embed


async def calculate_pp_for_beatmapset(beatmapset: dict, ignore_osu_cache: bool = False,
                                      ignore_memory_cache: bool = False, mods: str = "+Nomod"):
    """ Calculates the pp for every difficulty in the given mapset, added
    to a "pp" key in the difficulty's dict. """
    # Init the cache of this mapset if it has not been created
    set_id = str(beatmapset["id"])
    if set_id not in osu_config.data["map_cache"]:
        osu_config.data["map_cache"][set_id] = {}

    if not ignore_osu_cache:
        ignore_osu_cache = not bool(beatmapset["status"] == "ranked" or beatmapset["status"] == "approved")
    if not ignore_memory_cache:
        ignore_osu_cache = not bool(beatmapset["status"] == "ranked" or beatmapset["status"] == "approved" or
                                    beatmapset["status"] == "loved")

    cached_mapset = osu_config.data["map_cache"][set_id]

    for diff in beatmapset["beatmaps"]:
        map_id = str(diff["id"])

        if ignore_osu_cache:
            # If the diff is cached and unchanged, use the cached pp
            if map_id in cached_mapset and mods in cached_mapset[map_id]:
                if diff["checksum"] == cached_mapset[map_id]["md5"]:
                    diff["pp"] = cached_mapset[map_id][mods]["pp"]
                    diff["difficulty_rating"] = cached_mapset[map_id][mods]["stars"]
                    diff["ar"] = cached_mapset[map_id][mods]["ar"]
                    diff["cs"] = cached_mapset[map_id][mods]["cs"]
                    diff["accuracy"] = cached_mapset[map_id][mods]["od"]
                    diff["drain"] = cached_mapset[map_id][mods]["hp"]
                    diff["clock_rate"] = cached_mapset[map_id][mods]["clock_rate"]
                    continue

                # If it was changed, add an asterisk to the beatmap name (this is a really stupid place to do this)
                diff["version"] = "".join(["*", diff["version"]])

        # If the diff is not cached, or was changed, calculate the pp and update the cache
        try:
            pp_stats = await calculate_pp(int(map_id), mods, mode=api.GameMode.get_mode(diff["mode"]),
                                          ignore_osu_cache=ignore_osu_cache)
        except ValueError:
            logging.error(traceback.format_exc())
            continue

        diff["pp"] = pp_stats.pp
        diff["difficulty_rating"] = pp_stats.stars
        diff["ar"] = pp_stats.ar
        diff["cs"] = pp_stats.cs
        diff["accuracy"] = pp_stats.od
        diff["drain"] = pp_stats.hp
        diff["clock_rate"] = pp_stats.clock_rate

        if ignore_osu_cache:
            # Cache the difficulty
            if map_id in cached_mapset:
                if diff["checksum"] != cached_mapset[map_id]["md5"]:
                    osu_config.data["map_cache"][set_id][map_id] = {
                        "md5": diff["checksum"]
                    }
            else:
                osu_config.data["map_cache"][set_id][map_id] = {
                    "md5": diff["checksum"]
                }
            if mods not in osu_config.data["map_cache"][set_id][map_id]:
                osu_config.data["map_cache"][set_id][map_id][mods] = {}
            osu_config.data["map_cache"][set_id][map_id][mods]["pp"] = pp_stats.pp
            osu_config.data["map_cache"][set_id][map_id][mods]["stars"] = pp_stats.stars
            osu_config.data["map_cache"][set_id][map_id][mods]["ar"] = pp_stats.ar
            osu_config.data["map_cache"][set_id][map_id][mods]["cs"] = pp_stats.cs
            osu_config.data["map_cache"][set_id][map_id][mods]["od"] = pp_stats.od
            osu_config.data["map_cache"][set_id][map_id][mods]["hp"] = pp_stats.hp
            osu_config.data["map_cache"][set_id][map_id][mods]["clock_rate"] = pp_stats.clock_rate
    if ignore_osu_cache:
        await osu_config.asyncsave()


async def notify_recent_events(member_id: str, data: dict):
    """ Notify any map updates, such as update, resurrect and qualified. """
    # Only update when there is a difference
    if "old" not in data:
        return

    # Get the old and the new events
    old, new = data["old"]["events"], data["new"]["events"]

    # If nothing has changed, move on to the next member
    if old == new:
        return

    # Get the new events
    events = []  # type: List[dict]
    for event in new:
        if event in old:
            break

        # Since the events are displayed on the profile from newest to oldest, we want to post the oldest first
        events.insert(0, event)

    # Format and post the events
    status_format = None
    beatmap_info = None
    leaderboard_enabled = get_leaderboard_update_status(member_id)
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
                beatmapset = await api.beatmapset_from_url("".join(["https://osu.ppy.sh", event["beatmapset"]["url"]]),
                                                           force_redownload=True)
                if beatmapset:
                    break
                await asyncio.sleep(60)
            else:
                # well shit
                continue

            # Calculate (or retrieve cached info) the pp for every difficulty of this mapset
            try:
                await calculate_pp_for_beatmapset(beatmapset, ignore_osu_cache=True, ignore_memory_cache=True)
            except ValueError:
                logging.error(traceback.format_exc())

            event_text = [event["beatmapset"]["title"], event["type"],
                          (event["approval"] if event["type"] == "beatmapsetApprove" else "")]
            new_event = MapEvent(text=str("".join(event_text)))
            prev = discord.utils.get(recent_map_events, text="".join(event_text))
            to_delete = []

            if prev:
                recent_map_events.remove(prev)

                if prev.time_created + timedelta(hours=event_repeat_interval) > new_event.time_created:
                    to_delete = prev.messages
                    new_event.count = prev.count + 1
                    new_event.time_created = prev.time_created

            # Always append the new event to the recent list
            recent_map_events.append(new_event)

            # Send the message to all guilds
            member = data["member"]
            if not member:
                continue
            for guild in member.mutual_guilds:
                channels = get_notify_channels(guild, "map")  # type: list

                if not channels:
                    continue

                member = guild.get_member(int(member_id))

                for channel in channels:
                    # Do not format difficulties when minimal (or pp) information is specified
                    update_mode = get_update_mode(member_id)
                    embed = await format_map_status(member, status_format, beatmapset,
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

            if osu_score["best_id"] in previous_score_updates:
                continue

            top100_best_id = []
            for old_score in data["scores"]["score_list"]:
                top100_best_id.append(old_score["best_id"])

            if osu_score["best_id"] in top100_best_id:
                continue

            previous_score_updates.append(osu_score["best_id"])

            params = {
                "beatmap_id": osu_score["beatmap"]["id"],
            }
            beatmap = (await api.beatmap_lookup(params=params, map_id=beatmap_info.beatmap_id, mode=mode.name))
            # Send the message to all guilds
            member = data["member"]
            if not member:
                continue
            for guild in member.mutual_guilds:
                channels = get_notify_channels(guild, "score")
                if not channels:
                    continue
                member = guild.get_member(int(member_id))

                embed = await create_score_embed_with_pp(member, osu_score, beatmap, mode, position, twitch_link=True)
                embed.set_author(name=f"{data['new']['username']} set a new leaderboard score",
                                 icon_url=data["new"]["avatar_url"], url=get_user_url(str(member.id)))

                for channel in channels:
                    try:
                        await client.send_message(channel, embed=embed)
                    except discord.Forbidden:
                        pass


async def on_ready():
    """ Handle every event. """
    global time_elapsed, previous_update
    no_key = False

    await client.wait_until_ready()
    await ordr.establish_ws_connection()

    # Notify the owner when they have not set their API key
    if osu_config.data["client_secret"] == "change to your client secret" or \
            osu_config.data["client_id"] == "change to your client ID":
        logging.warning("osu! functionality is unavailable until a "
                        "client ID and client secret is provided (config/osu.json)")
        no_key = True

    while not client.loop.is_closed() and not no_key:
        try:
            await asyncio.sleep(float(update_interval))
            started = datetime.now()

            for member_id, profile in list(osu_config.data["profiles"].items()):
                # First, update the user's data
                await update_user_data(member_id, profile)
                if str(member_id) in osu_tracking:
                    data = osu_tracking[str(member_id)]
                    # Next, check for any differences in pp between the "old" and the "new" subsections
                    # and notify any guilds
                    # NOTE: This used to also be ensure_future before adding the potential pp check.
                    # The reason for this change is to ensure downloading and running the .osu files won't happen twice
                    # at the same time, which would cause problems retrieving the correct potential pp.
                    await notify_pp(str(member_id), data)
                    # Check for any differences in the users' events and post about map updates
                    # NOTE: the same applies to this now. These can't be concurrent as they also calculate pp.
                    await notify_recent_events(str(member_id), data)
            if cache_user_profiles:
                await osu_profile_cache.asyncsave()
        except aiohttp.ClientOSError:
            logging.error(traceback.format_exc())
        except asyncio.CancelledError:
            return
        except Exception:
            logging.error(traceback.format_exc())
        finally:
            # Save the time elapsed since we started the update
            time_elapsed = (datetime.now() - started).total_seconds()
            previous_update = datetime.now(tz=timezone.utc)


async def on_reload(name: str):
    """ Preserve the tracking cache. """
    global recent_map_events, time_elapsed, previous_update, previous_score_updates, no_choke_cache, \
        last_rendered
    local_events = recent_map_events
    local_renders = last_rendered
    local_requests = api.requests_sent
    local_update_time_elapsed = time_elapsed
    local_update_time = previous_update
    local_score_updates = previous_score_updates
    local_no_choke_cache = no_choke_cache

    importlib.reload(plugins.osulib.api)
    importlib.reload(plugins.osulib.args)
    importlib.reload(plugins.osulib.pp)
    await plugins.reload(name)

    api.requests_sent = local_requests
    last_rendered = local_renders
    recent_map_events = local_events
    time_elapsed = local_update_time_elapsed
    previous_update = local_update_time
    previous_score_updates = local_score_updates
    no_choke_cache = local_no_choke_cache


def get_timestamps_with_url(content: str):
    """ Yield every map timestamp found in a string, and an edditor url.

    :param content: The string to search
    :returns: a tuple of the timestamp as a raw string and an editor url
    """
    for match in timestamp_pattern.finditer(content):
        editor_url = match.group(1).strip(" ").replace(" ", "%20").replace(")", r")")
        yield match.group(0), f"<osu://edit/{editor_url}>"


@plugins.event()
async def on_message(message: discord.Message):
    """ Automatically post editor timestamps with URL. """
    # Ignore commands
    if message.content.startswith("!"):
        return

    timestamps = [f"{stamp} {editor_url}" for stamp, editor_url in get_timestamps_with_url(message.content)]
    if timestamps:
        await client.send_message(message.channel,
                                  embed=discord.Embed(color=message.author.color,
                                                      description="\n".join(timestamps)))
        return True


@plugins.command(aliases="circlesimulator eba", usage="[member] <mode>")
async def osu(message: discord.Message, *options):
    """ Handle osu! commands.

    When your user is linked, this plugin will check if you are playing osu!
    (your profile would have `playing osu!`), and send updates whenever you set a
    new top score. """
    member = None
    mode = None

    for value in options:
        member = get_user(message, value)
        if member:
            continue

        mode = api.GameMode.get_mode(value)

    if member is None:
        member = message.author

    # Make sure the member is assigned
    assert str(member.id) in osu_config.data["profiles"], get_missing_user_string(member)

    user_id = osu_config.data["profiles"][str(member.id)]
    mode = get_mode(str(member.id)) if mode is None else mode

    # Set the signature color to that of the role color
    color = "pink" if member.color == discord.Color.default() \
        else "#{0:02x}{1:02x}{2:02x}".format(*member.color.to_rgb())

    # Calculate whether the header color should be black or white depending on the background color.
    # Stupidly, the API doesn't accept True/False. It only looks for the &darkheaders keyword.
    # The silly trick done here is extracting either the darkheader param or nothing.
    r, g, b = member.color.to_rgb()
    dark = dict(darkheader="True") if (r * 0.299 + g * 0.587 + b * 0.144) > 186 else {}

    # Download and upload the signature
    params = {
        "colour": color,
        "uname": user_id,
        "pp": 0,
        "countryrank": "",
        "xpbar": "",
        "mode": mode.value,
        "date": datetime.now().ctime()
    }
    signature = await utils.retrieve_page("https://osusig.lolicon.app/sig.php", head=True, **params, **dark)
    embed = discord.Embed(color=member.color)
    embed.set_author(name=member.display_name, icon_url=member.display_avatar.url, url=get_user_url(str(member.id)))
    embed.set_image(url=signature.url)
    await client.send_message(message.channel, embed=embed)


async def has_enough_pp(user: str, mode: api.GameMode, **params):
    """ Lookup the given member and check if they have enough pp to register.
    params are just like api.get_user. """
    osu_user = await api.get_user(user, mode, params=params)
    return osu_user["statistics"]["pp"] >= minimum_pp_required


@osu.command(aliases="set")
async def link(message: discord.Message, name: Annotate.LowerContent):
    """ Tell the bot who you are on osu!. """
    params = {
        "key": "username",
    }
    osu_user = await api.get_user(name, params=params)

    # Check if the osu! user exists
    assert "id" in osu_user, f"osu! user `{name}` does not exist."
    user_id = osu_user["id"]
    mode = api.GameMode.get_mode(osu_user["playmode"])

    # Make sure the user has more pp than the minimum limit defined in config
    if float(osu_user["statistics"]["pp"]) < minimum_pp_required:
        # Perhaps the user wants to display another gamemode
        await client.say(message,
                         f"**You have less than the required {minimum_pp_required}pp.\nIf you have enough in "
                         f"a different mode, please enter your gamemode below. Valid gamemodes are `{gamemodes}`.**")

        def check(m):
            return m.author == message.author and m.channel == message.channel

        try:
            reply = await client.wait_for_message(timeout=60, check=check)
        except asyncio.TimeoutError:
            return

        mode = api.GameMode.get_mode(reply.content)
        assert mode is not None, "**The given gamemode is invalid.**"
        assert await has_enough_pp(user=user_id, mode=mode.name), \
            f"**Your pp in {mode.name} is less than the required {minimum_pp_required}pp.**"

    # Clear the scores when changing user
    if str(message.author.id) in osu_tracking:
        del osu_tracking[str(message.author.id)]

    user_id = osu_user["id"]

    # Assign the user using their unique user_id
    osu_config.data["profiles"][str(message.author.id)] = str(user_id)
    osu_config.data["mode"][str(message.author.id)] = mode.value
    osu_config.data["primary_guild"][str(message.author.id)] = str(message.guild.id)
    await osu_config.asyncsave()
    await client.say(message, f"Set your osu! profile to `{osu_user['username']}`.")


@osu.command(hidden=True, owner=True)
async def wipe_tracking(message: discord.Message, member: discord.Member = None):
    """ Wipe all tracked members or just the specified member. """
    if member:
        if str(member.id) in osu_tracking:
            del osu_tracking[str(member.id)]
            await client.say(message, f"Deleted {member.name} from tracking.")
        if str(member.id) in osu_profile_cache.data:
            del osu_profile_cache.data[str(member.id)]
        else:
            await client.say(message, "User not in tracking.")
    else:
        previous_length = len(osu_tracking)
        for entry in list(osu_tracking):
            del osu_tracking[entry]
        osu_profile_cache.data = {}
        await osu_profile_cache.asyncsave()
        await client.say(message, f"Deleted {previous_length} entries.")


@osu.command(aliases="unset")
async def unlink(message: discord.Message, member: discord.Member = Annotate.Self):
    """ Unlink your osu! account or unlink the member specified (**Owner only**). """
    # The message author is allowed to unlink himself
    # If a member is specified and the member is not the owner, set member to the author
    if not plugins.is_owner(message.author):
        member = message.author

    # The member might not be linked to any profile
    assert str(member.id) in osu_config.data["profiles"], get_missing_user_string(member)

    # Clear the tracking data when unlinking user
    if str(member.id) in osu_tracking:
        del osu_tracking[str(member.id)]
    if str(member.id) in osu_profile_cache.data:
        del osu_profile_cache.data[str(member.id)]
        await osu_profile_cache.asyncsave()

    # Unlink the given member (usually the message author)
    del osu_config.data["profiles"][str(member.id)]
    await osu_config.asyncsave()
    await client.say(message, f"Unlinked **{member.name}'s** osu! profile.")


gamemodes = ", ".join(format_mode_name(gm) for gm in api.GameMode)


@osu.command(aliases="mode m track", error=f"Valid gamemodes: `{gamemodes}`", doc_args=dict(modes=gamemodes))
async def gamemode(message: discord.Message, mode: api.GameMode.get_mode):
    """ Sets the command executor's gamemode.

    Gamemodes are: `{modes}`. """
    assert str(message.author.id) in osu_config.data["profiles"], get_missing_user_string(message.author)

    user_id = osu_config.data["profiles"][str(message.author.id)]

    mode_name = format_mode_name(mode)

    assert await has_enough_pp(user=user_id, mode=mode.name), \
        f"**Your pp in {mode_name} is less than the required {minimum_pp_required}pp.**"

    osu_config.data["mode"][str(message.author.id)] = mode.value
    await osu_config.asyncsave()

    # Clear the scores when changing mode
    if str(message.author.id) in osu_tracking:
        del osu_tracking[str(message.author.id)]
    if str(message.author.id) in osu_profile_cache.data:
        del osu_profile_cache.data[str(message.author.id)]
        await osu_profile_cache.asyncsave()

    await client.say(message, f"Set your gamemode to **{mode_name}**.")


@osu.command(usage="<on/off>")
async def leaderboard_notifications(message: discord.Message, notify_setting: str):
    """ When leaderboard updates are enabled, the bot will post your top50 scores on maps unless
    it's in your top100 PP scores. """
    member = message.author
    # Make sure the member is assigned
    assert str(member.id) in osu_config.data["profiles"], get_missing_user_string(member)

    if notify_setting.lower() == "on":
        osu_config.data["leaderboard"][str(member.id)] = True
        await client.say(message, "Enabled leaderboard updates.")
    elif notify_setting.lower() == "off":
        osu_config.data["leaderboard"][str(member.id)] = False
        await client.say(message, "Disabled leaderboard updates.")
    else:
        await client.say(message, "Invalid setting selected. Valid settings are on and off.")

    await osu_config.asyncsave()


@osu.command()
async def info(message: discord.Message, member: discord.Member = Annotate.Self):
    """ Display configuration info. """
    # Make sure the member is assigned
    assert str(member.id) in osu_config.data["profiles"], get_missing_user_string(member)

    user_id = osu_config.data["profiles"][str(member.id)]
    mode = get_mode(str(member.id))
    update_mode = get_update_mode(str(member.id))
    if str(member.id) in osu_tracking and "new" in osu_tracking[str(member.id)]:
        timestamp = datetime.fromisoformat(osu_tracking[str(member.id)]["new"]["time_updated"])
    else:
        timestamp = None
    if timestamp:
        e = discord.Embed(color=member.color, timestamp=timestamp)
        e.set_footer(text="User data last updated:\n")
    else:
        e = discord.Embed(color=member.color)
    e.set_author(name=member.display_name, icon_url=member.display_avatar.url, url="".join([host, "users/", user_id]))
    e.add_field(name="Game Mode", value=format_mode_name(mode))
    e.add_field(name="Notification Mode", value=update_mode.name)
    e.add_field(name="Playing osu!", value="YES" if is_playing(member) else "NO")
    e.add_field(name="Notifying leaderboard scores", value="YES" if get_leaderboard_update_status(str(member.id))
                else "NO")

    await client.send_message(message.channel, embed=e)


doc_modes = ", ".join(m.name.lower() for m in UpdateModes)


@osu.command(aliases="n updatemode", error=f"Valid modes: `{doc_modes}`", doc_args=dict(modes=doc_modes))
async def notify(message: discord.Message, mode: UpdateModes.get_mode):
    """ Sets the command executor's update notification mode. This changes
    how much text is in each update, or if you want to disable them completely.

    Update modes are: `{modes}`. """
    assert str(message.author.id) in osu_config.data["profiles"], get_missing_user_string(message.author)

    osu_config.data["update_mode"][str(message.author.id)] = mode.name
    await osu_config.asyncsave()

    # Clear the scores when disabling mode
    if str(message.author.id) in osu_tracking and mode == UpdateModes.Disabled:
        del osu_tracking[str(message.author.id)]

    await client.say(message, f"Set your update notification mode to **{mode.name.lower()}**.")


@osu.command()
async def url(message: discord.Message, member: discord.Member = Annotate.Self,
              section: str.lower = None):
    """ Display the member's osu! profile URL. """
    # Member might not be registered
    assert str(member.id) in osu_config.data["profiles"], get_missing_user_string(member)

    # Send the URL since the member is registered
    await client.say(message, f"**{member.display_name}'s profile:** "
                              f"<{get_user_url(str(member.id))}{f'#_{section}' if section else ''}>")


async def pp_(message: discord.Message, beatmap_url: str, *options):
    """ Calculate and return the would be pp using `rosu-pp`.

    Options are a parsed set of command-line arguments:  /
    `([acc]% | [num_100s]x100 [num_50s]x50) +[mods] [combo]x [misses]m`

    **Additionally**, PCBOT includes a *find closest pp* feature. This works as an
    argument in the options, formatted like `[pp_value]pp`
    """
    try:
        beatmap_info = api.parse_beatmap_url(beatmap_url)
        assert beatmap_info.beatmap_id, "Please link to a specific difficulty."
        assert beatmap_info.gamemode, "Please link to a specific mode."

        params = {
            "beatmap_id": beatmap_info.beatmap_id,
        }
        beatmap = (await api.beatmap_lookup(params=params, map_id=beatmap_info.beatmap_id,
                                            mode=beatmap_info.gamemode.name))

        assert not beatmap["convert"], "Converts are not supported by the PP calculator."

        pp_stats = await calculate_pp(beatmap_url, *options, mode=beatmap_info.gamemode,
                                      ignore_osu_cache=not bool(beatmap["status"] == "ranked" or
                                                                beatmap["status"] == "approved"))
    except ValueError as e:
        await client.say(message, str(e))
        return

    options = list(options)
    if isinstance(pp_stats, ClosestPPStats):
        # Remove any accuracy percentage from options as we're setting this manually, and remove unused options
        for opt in options:
            if opt.endswith("%") or opt.endswith("pp") or opt.endswith("x300") or opt.endswith("x100") or opt.endswith(
                    "x50"):
                options.remove(opt)

        options.insert(0, f"{pp_stats.acc}%")
    for opt in options:
        if opt.startswith("+"):
            options.append(opt.upper())
            options.remove(opt)
    await client.say(message,
                     "*{artist} - {title}* **[{version}] {0}** {stars:.02f}\u2605 would be worth `{pp:,.02f}pp`."
                     .format(" ".join(options), artist=beatmap["beatmapset"]["artist"],
                             title=beatmap["beatmapset"]["title"], version=beatmap["version"], stars=pp_stats.stars,
                             pp=pp_stats.pp))


plugins.command(name="pp", aliases="oppai")(pp_)
osu.command(name="pp", aliases="oppai")(pp_)


async def create_score_embed_with_pp(member: discord.Member, osu_score: dict, beatmap: dict,
                                     mode: api.GameMode, scoreboard_rank: bool = False, twitch_link: bool = False):
    """ Returns a score embed for use outside of automatic score notifications. """
    score_pp = await get_score_pp(osu_score, mode, beatmap)
    mods = Mods.format_mods(osu_score["mods"])

    if score_pp is not None and osu_score["pp"] is None:
        osu_score["pp"] = score_pp.pp
    elif osu_score["pp"] is None:
        osu_score["pp"] = 0
    if score_pp is not None:
        beatmap["difficulty_rating"] = get_beatmap_sr(score_pp, beatmap, mods)
    if ("max_combo" not in beatmap or not beatmap["max_combo"]) and score_pp and score_pp.max_combo:
        beatmap["max_combo"] = score_pp.max_combo

    # There might not be any events
    if scoreboard_rank is False and str(member.id) in osu_tracking and "new" in osu_tracking[str(member.id)] \
            and osu_tracking[str(member.id)]["new"]["events"]:
        scoreboard_rank = api.rank_from_events(osu_tracking[str(member.id)]["new"]["events"],
                                               str(osu_score["beatmap"]["id"]), osu_score)

    embed = get_formatted_score_embed(member, osu_score, await format_new_score(mode, osu_score, beatmap,
                                                                                scoreboard_rank,
                                                                                member if twitch_link else None),
                                      score_pp if score_pp is not None and not bool(osu_score["perfect"]
                                                                                    and osu_score["passed"]) else None)
    embed.set_author(name=osu_score["user"]["username"], icon_url=osu_score["user"]["avatar_url"],
                     url=get_user_url(str(member.id)))
    embed.set_thumbnail(url=osu_score["beatmapset"]["covers"]["list@2x"] if bool(
        "beatmapset" in osu_score) else beatmap["beatmapset"]["covers"]["list@2x"])
    return embed


async def recent(message: discord.Message, user: str = None):
    """ Display your or another member's most recent score. """
    if not user:
        member = message.author
    else:
        member = get_user(message, user)
    if not member:
        member = message.author
    assert str(member.id) in osu_config.data["profiles"], get_missing_user_string(member)

    user_id = osu_config.data["profiles"][str(member.id)]
    mode = get_mode(str(member.id))

    params = {
        "include_fails": 1,
        "mode": mode.name,
        "limit": 1
    }

    osu_scores = await api.get_user_scores(user_id, "recent", params=params)
    assert osu_scores, "Found no recent score."

    osu_score = osu_scores[0]

    params = {
        "beatmap_id": osu_score["beatmap"]["id"],
    }
    beatmap = (await api.beatmap_lookup(params=params, map_id=int(osu_score["beatmap"]["id"]), mode=mode.name))

    embed = await create_score_embed_with_pp(member, osu_score, beatmap, mode,
                                             twitch_link=osu_score["passed"])
    await client.send_message(message.channel, embed=embed)


plugins.command()(recent)
osu.command(aliases="last new")(recent)


@osu.command(usage="<replay>")
async def render(message: discord.Message, *options):
    """ Render a replay using <https://ordr.issou.best>.
    The command accepts either a URL or an uploaded file.\n
    You can only render a replay every 5 minutes. """

    replay_url = ""
    for value in options:
        if utils.http_url_pattern.match(value):
            replay_url = value

    if not message.attachments == []:
        for attachment in message.attachments:
            replay_url = attachment.url

    if message.author.id in last_rendered:
        time_since_render = datetime.utcnow() - last_rendered[message.author.id]
        if time_since_render.total_seconds() < 300:
            await client.say(message, "It's been less than 5 minutes since your last render. "
                                      "Please wait before trying again")
            return

    assert replay_url, "No replay provided"
    placeholder_msg = await client.send_message(message.channel, "Sending render...")
    render_job = await ordr.send_render_job(replay_url)

    if not isinstance(render_job, dict):
        await placeholder_msg.edit("An error occured when sending this replay. The bot might be rate-limited.")
        return

    if "renderID" not in render_job:
        await placeholder_msg.edit("An error occured when sending this replay. The bot might be rate-limited.")
        return

    last_rendered[message.author.id] = datetime.utcnow()
    ordr.requested_renders[int(render_job["renderID"])] = dict(message=placeholder_msg, edited=datetime.utcnow())


async def score(message: discord.Message, *options):
    """ Display your own or the member's score on a beatmap. Add mods to simulate the beatmap score with those mods.
    If URL is not provided it searches the last 10 messages for a URL. """
    member = None
    beatmap_url = None
    mods = None

    for value in options:
        if utils.http_url_pattern.match(value):
            beatmap_url = value
        elif value.startswith("+"):
            mods = value.replace("+", "").upper()
        else:
            member = get_user(message, value)

    if not member:
        member = message.author

    assert str(member.id) in osu_config.data["profiles"], get_missing_user_string(member)

    # Attempt to find beatmap URL in previous messages
    if not beatmap_url:
        beatmap_info = None
        match = False
        async for m in message.channel.history():
            to_search = [m.content]
            if m.embeds:
                for embed in m.embeds:
                    to_search.append(embed.description if embed.description else "")
                    to_search.append(embed.title if embed.title else "")
                    to_search.append(embed.footer.text if embed.footer else "")
            found_url = utils.http_url_pattern.search("".join(to_search))
            if found_url:
                try:
                    beatmap_info = await api.beatmap_from_url(found_url.group(), return_type="info")
                    match = True
                    break
                except SyntaxError:
                    continue
        # Check if URL was found
        assert match, "No beatmap link found"
    else:
        try:
            beatmap_info = await api.beatmap_from_url(beatmap_url, return_type="info")
        except SyntaxError as e:
            await client.say(message, str(e))
            return

    user_id = osu_config.data["profiles"][str(member.id)]
    mode = get_mode(str(member.id))
    params = {
        "mode": beatmap_info.gamemode.name if beatmap_info.gamemode else mode.name,
    }
    osu_scores = await api.get_user_beatmap_score(beatmap_info.beatmap_id, user_id, params=params)
    assert osu_scores, f"Found no scores by **{member.name}**."

    osu_score = osu_scores["score"]
    if mods:
        osu_score["mods"] = wrap(mods, 2)
        osu_score["pp"] = None
        osu_score["score"] = None
        scoreboard_rank = None
    else:
        scoreboard_rank = osu_scores["position"]

    params = {
        "beatmap_id": osu_score["beatmap"]["id"],
    }
    beatmap = (await api.beatmap_lookup(params=params, map_id=osu_score["beatmap"]["id"],
                                        mode=beatmap_info.gamemode.name if beatmap_info.gamemode else mode.name))

    embed = await create_score_embed_with_pp(member, osu_score, beatmap, beatmap_info.gamemode
                                             if beatmap_info.gamemode else mode, scoreboard_rank)
    embed.set_footer(text="".join([embed.footer.text, ("".join(["\n", get_formatted_score_time(osu_score)
                                                       if not mods and pendulum else ""]))]))
    await client.send_message(message.channel, embed=embed)


plugins.command(name="score", usage="[member] <url> +<mods>")(score)
osu.command(name="score", usage="[member] <url> +<mods>")(score)


@osu.command(aliases="map")
async def mapinfo(message: discord.Message, beatmap_url: str, mods: str = "+Nomod"):
    """ Display simple beatmap information. """
    try:
        beatmapset = await api.beatmapset_from_url(beatmap_url)
    except Exception as e:
        await client.say(message, str(e))
        return

    await calculate_pp_for_beatmapset(beatmapset, mods=mods)
    status = "[**{artist} - {title}**]({host}beatmapsets/{id}) submitted by [**{name}**]({host}users/{user_id})"
    embed = await format_map_status(status_format=status, beatmapset=beatmapset, minimal=False,
                                    member=message.author, user_update=False, mods=mods)
    await client.send_message(message.channel, embed=embed)


def generate_full_no_choke_score_list(no_choke_scores: list, original_scores: list):
    """ Insert no_choke plays into full score list. """
    no_choke_ids = []
    for osu_score in no_choke_scores:
        no_choke_ids.append(osu_score["best_id"])
    for osu_score in list(original_scores):
        if osu_score["best_id"] in no_choke_ids:
            original_scores.remove(osu_score)
    for osu_score in no_choke_scores:
        original_scores.append(osu_score)
    original_scores.sort(key=itemgetter("pp"), reverse=True)
    return original_scores


async def top(message: discord.Message, *options):
    """ By default displays your or the selected member's 5 highest rated plays sorted by PP.
     You can also add "nochoke" as an option to display a list of unchoked top scores instead.
     Alternative sorting methods are "oldest", "newest", "combo", "score" and "acc" """
    member = None
    list_type = "pp"
    nochoke = False
    for value in options:
        if value in ("newest", "recent"):
            list_type = "newest"
        elif value == "oldest":
            list_type = value
        elif value == "acc":
            list_type = value
        elif value == "combo":
            list_type = value
        elif value == "score":
            list_type = value
        elif value == "nochoke":
            nochoke = True
        else:
            member = get_user(message, value)

    if not member:
        member = message.author
    mode = get_mode(str(member.id))
    assert str(member.id) in osu_config.data["profiles"], get_missing_user_string(member)
    assert str(member.id) in osu_tracking and "scores" in osu_tracking[str(member.id)], \
        "Scores have not been retrieved for this user yet. Please wait a bit and try again."
    assert mode is api.GameMode.osu if nochoke else True, \
        "No-choke lists are only supported for osu!standard."
    assert not list_type == "score" if nochoke else True, "No-choke lists can't be sorted by score."
    if nochoke:
        async with message.channel.typing():
            osu_scores = await calculate_no_choke_top_plays(copy.deepcopy(osu_tracking[str(member.id)]["scores"]),
                                                            str(member.id))
            full_osu_score_list = generate_full_no_choke_score_list(
                osu_scores["score_list"], copy.deepcopy(osu_tracking[str(member.id)]["scores"]["score_list"]))
            new_total_pp = calculate_total_user_pp(full_osu_score_list, str(member.id))
            author_text = "{} ({} => {}, {:+})".format(osu_tracking[str(member.id)]["new"]["username"],
                                                       utils.format_number(
                                                          osu_tracking[str(member.id)]["new"]["statistics"]["pp"], 2),
                                                       utils.format_number(new_total_pp, 2),
                                                       utils.format_number(
                                                          new_total_pp -
                                                          osu_tracking[str(member.id)]["new"]["statistics"]["pp"], 2))
            sorted_scores = get_sorted_scores(osu_scores, list_type)
            m = await get_formatted_score_list(member, sorted_scores["score_list"], 5)
    else:
        osu_scores = osu_tracking[str(member.id)]["scores"]
        author_text = osu_tracking[str(member.id)]["new"]["username"]
        sorted_scores = get_sorted_scores(osu_scores, list_type)
        m = await get_formatted_score_list(member, sorted_scores["score_list"], 5)
    e = discord.Embed(color=member.color)
    e.description = m
    e.set_author(name=author_text,
                 icon_url=osu_tracking[str(member.id)]["new"]["avatar_url"], url=get_user_url(str(member.id)))
    e.set_thumbnail(url=osu_tracking[str(member.id)]["new"]["avatar_url"])
    await client.send_message(message.channel, embed=e)


plugins.command(name="top", usage="[member] <sort_by>", aliases="osutop")(top)
osu.command(name="top", usage="[member] <sort_by>", aliases="osutop")(top)


def init_guild_config(guild: discord.Guild):
    """ Initializes the config when it's not already set. """
    if str(guild.id) not in osu_config.data["guild"]:
        osu_config.data["guild"][str(guild.id)] = {}
        osu_config.save()


def calculate_total_user_pp(osu_scores: list, member_id: str):
    """ Calculates the user's total PP. """
    total_pp = 0
    for i, osu_score in enumerate(osu_scores):
        total_pp += osu_score["pp"] * (0.95 ** i)
    total_pp_without_bonus_pp = 0
    for osu_score in osu_tracking[member_id]["scores"]["score_list"]:
        total_pp_without_bonus_pp += osu_score["weight"]["pp"]
    bonus_pp = osu_tracking[member_id]["new"]["statistics"]["pp"] - total_pp_without_bonus_pp
    return total_pp + bonus_pp


@osu.command(aliases="configure cfg")
async def config(message, _: utils.placeholder):
    """ Manage configuration for this plugin. """


@config.command(alias="score", permissions="manage_guild")
async def scores(message: discord.Message, *channels: discord.TextChannel):
    """ Set which channels to post scores to. """
    init_guild_config(message.guild)
    osu_config.data["guild"][str(message.guild.id)]["score-channels"] = list(str(c.id) for c in channels)
    await osu_config.asyncsave()
    await client.say(message, f"**Notifying scores in**: {utils.format_objects(*channels, sep=' ') or 'no channels'}")


@config.command(alias="map", permissions="manage_guild")
async def maps(message: discord.Message, *channels: discord.TextChannel):
    """ Set which channels to post map updates to. """
    init_guild_config(message.guild)
    osu_config.data["guild"][str(message.guild.id)]["map-channels"] = list(c.id for c in channels)
    await osu_config.asyncsave()
    await client.say(message, f"**Notifying map updates in**: "
                              f"{utils.format_objects(*channels, sep=' ') or 'no channels'}")


@osu.command(owner=True)
async def debug(message: discord.Message):
    """ Display some debug info. """
    client_time = f"<t:{int(client.time_started.replace(tzinfo=timezone.utc).timestamp())}:F>"
    member_list = [f"`{d['member'].name}`" for d in osu_tracking.values() if "member" in d and is_playing(d["member"])]
    await client.say(message, "Sent `{}` requests since the bot started ({}).\n"
                              "Sent an average of `{}` requests per minute. \n"
                              "Spent `{:.3f}` seconds last update.\n"
                              "Last update happened at: {}\n"
                              "Members registered as playing: {}\n"
                              "Total members tracked: `{}`".format(
                               api.requests_sent, client_time,
                               utils.format_number(api.requests_sent /
                                                   ((datetime.utcnow() - client.time_started).total_seconds() / 60.0),
                                                   2)
                               if api.requests_sent > 0 else 0,
                               time_elapsed,
                               f"<t:{int(previous_update.timestamp())}:F>"
                               if previous_update else "Not updated yet.",
                               ", ".join(member_list) if member_list else "None", len(osu_tracking)
                               )
                     )
