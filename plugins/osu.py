""" Plugin for osu! commands

This plugin will notify any registered user's pp difference and if they
set a new best also post that. It also includes many osu! features, such
as a signature generator, pp calculation and user map updates.

TUTORIAL:
    A member with Manage Guild permission must first assign one or more channels
    that the bot should post scores or map updates in.
    See: !help osu config

    Members may link their osu! profile with `!osu link <name ...>`. The bot will
    only keep track of players who either has `osu` in their playing name, e.g:
        Playing osu!
    or has their rank as #xxx, for instance:
        Streaming Chill | #4 Norway

    This plugin might send a lot of requests, so keep up to date with the
    !osu debug command.

    The pp command requires that you setup pyttanko
    pip install pyttanko

    Check the readme in the link above for install instructions.

Commands:
    osu
    pp
"""
import importlib
import logging
import re
import traceback
from datetime import datetime, timedelta
import pytz
from enum import Enum
from typing import List

import aiohttp
import asyncio
import discord
import pendulum

import plugins
from pcbot import Config, utils, Annotate, config as botconfig
from plugins.osulib import api, Mods, calculate_pp, can_calc_pp, ClosestPPStats, ordr
from plugins.twitchlib import twitch

client = plugins.client  # type: discord.Client

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
))

osu_tracking = {}  # Saves the requested data or deletes whenever the user stops playing (for comparisons)
last_rendered = {}  # Saves when the member last rendered a replay
update_interval = osu_config.data.get("update_interval", 30)
not_playing_skip = osu_config.data.get("not_playing_skip", 10)
time_elapsed = 0  # The registered time it takes to process all information between updates (changes each update)
logging_interval = 30  # The time it takes before posting logging information to the console. TODO: setup logging
rank_regex = re.compile(r"#\d+")

pp_threshold = osu_config.data.get("pp_threshold", 0.13)
score_request_limit = osu_config.data.get("score_request_limit", 100)
minimum_pp_required = osu_config.data.get("minimum_pp_required", 0)
use_mentions_in_scores = osu_config.data.get("use_mentions_in_scores", True)
max_diff_length = 22  # The maximum amount of characters in a beatmap difficulty

asyncio.run_coroutine_threadsafe(api.set_oauth_client(osu_config.data.get("client_id"),
                                                      osu_config.data.get("client_secret")), client.loop)
host = "https://osu.ppy.sh/"
rankings_url = "https://osu.ppy.sh/rankings/osu/performance"

gamemodes = ", ".join(gm.name for gm in api.GameMode)

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
        return "MapEvent(text={}, time_created={}, count={})".format(self.text, self.time_created.ctime(), self.count)

    def __str__(self):
        return repr(self)


class UpdateModes(Enum):
    """ Enums for the various notification update modes.
    Values are valid names in a tuple. """
    Full = ("full", "on", "enabled", "f", "e")
    NoMention = ("nomention", "silent")
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


def calculate_acc(mode: api.GameMode, score: dict, exclude_misses: bool = False):
    """ Calculate the accuracy using formulas from https://osu.ppy.sh/wiki/Accuracy """
    # Parse data from the score: 50s, 100s, 300s, misses, katu and geki
    keys = ("count_300", "count_100", "count_50", "count_miss", "count_katu", "count_geki")
    c300, c100, c50, miss, katu, geki = map(int, (score["statistics"][key] for key in keys))

    # Catch accuracy is done a tad bit differently, so we calculate that by itself
    if mode is api.GameMode.Catch:
        total_numbers_of_fruits_caught = c50 + c100 + c300
        total_numbers_of_fruits = miss + c50 + c100 + c300 + katu
        return total_numbers_of_fruits_caught / total_numbers_of_fruits

    total_points_of_hits, total_number_of_hits = 0, 0

    if mode is api.GameMode.Standard:
        total_points_of_hits = c50 * 50 + c100 * 100 + c300 * 300
        total_number_of_hits = (0 if exclude_misses else miss) + c50 + c100 + c300
    elif mode is api.GameMode.Taiko:
        total_points_of_hits = (miss * 0 + c100 * 0.5 + c300 * 1) * 300
        total_number_of_hits = miss + c100 + c300
    elif mode is api.GameMode.Mania:
        # In mania, katu is 200s and geki is MAX
        total_points_of_hits = c50 * 50 + c100 * 100 + katu * 200 + (c300 + geki) * 300
        total_number_of_hits = miss + c50 + c100 + katu + c300 + geki

    return total_points_of_hits / (total_number_of_hits * 300)


def format_user_diff(mode: api.GameMode, pp: float, rank: int, country_rank: int, accuracy: float, iso: str,
                     data: dict):
    """ Get a bunch of differences and return a formatted string to send.
    iso is the country code. """
    pp_rank = int(data["statistics"]["global_rank"])
    pp_country_rank = int(data["statistics"]["country_rank"])

    # Find the performance page number of the respective ranks

    formatted = "\u2139`{} {:.2f}pp {:+.2f}pp`".format(mode.name.replace("Standard", "osu!"), float(data["statistics"]
                                                                                                    ["pp"]), pp)
    formatted += (" [\U0001f30d]({}?page={})`#{:,}{}`".format(rankings_url, pp_rank // 50 + 1, pp_rank,
                                                              "" if int(rank) == 0 else " {:+}".format(int(rank))))
    formatted += (" [{}]({}?country={}&page={})`#{:,}{}`".format(utils.text_to_emoji(iso), rankings_url, iso,
                                                                 pp_country_rank // 50 + 1, pp_country_rank,
                                                                 "" if int(country_rank) == 0 else " {:+}".format(
                                                                     int(country_rank))))
    rounded_acc = round(accuracy, 3)
    if rounded_acc > 0:
        formatted += "\n\U0001f4c8"  # Graph with upwards trend
    elif rounded_acc < 0:
        formatted += "\n\U0001f4c9"  # Graph with downwards trend
    else:
        formatted += "\n\U0001f3af"  # Dart

    formatted += "`{:.3f}%".format(float(data["statistics"]["hit_accuracy"]))
    if not rounded_acc == 0:
        formatted += " {:+}%`".format(rounded_acc)
    else:
        formatted += "`"

    return formatted


async def format_stream(member: discord.Member, score: dict, beatmap: dict):
    """ Format the stream url and a VOD button when possible. """
    stream_url = getattr(member.activity, "url", None)
    if not stream_url:
        return ""

    # Add the stream url and return immediately if twitch is not setup
    text = "**Watch live @** <{}>".format(stream_url)
    if not twitch.client_id:
        return text + "\n"

    # Try getting the vod information of the current stream
    try:
        twitch_id = await twitch.get_id(member)
        vod_request = await twitch.request("channels/{}/videos".format(twitch_id), limit=1, broadcast_type="archive",
                                           sort="time")
        assert vod_request["_total"] >= 1
    except:
        logging.error(traceback.format_exc())
        return text + "\n"

    vod = vod_request["videos"][0]

    # Find the timestamp of where the play would have started without pausing the game
    score_created = datetime.strptime(score["date"], "%Y-%m-%d %H:%M:%S")
    vod_created = datetime.strptime(vod["created_at"], "%Y-%m-%dT%H:%M:%SZ")
    beatmap_length = int(beatmap["total_length"])

    # Convert beatmap length when speed mods are enabled
    mods = Mods.list_mods(score["mods"])
    if Mods.DT in mods or Mods.NC in mods:
        beatmap_length /= 1.5
    elif Mods.HT in mods:
        beatmap_length /= 0.75

    # Get the timestamp in the VOD when the score was created
    timestamp_score_created = (score_created - vod_created).total_seconds()
    timestamp_play_started = timestamp_score_created - beatmap_length

    # Add the vod url with timestamp to the formatted text
    text += " | **[`Video of this play :)`]({0}?t={1}s)**\n".format(vod["url"], int(timestamp_play_started))
    return text


async def format_new_score(mode: api.GameMode, score: dict, beatmap: dict, rank: int = None,
                           member: discord.Member = None):
    """ Format any score. There should be a member name/mention in front of this string. """
    acc = calculate_acc(mode, score)
    return (
        "[{i}{artist} - {title} [{version}]{i}]({host}beatmapsets/{beatmapset_id}/#{mode}/{beatmap_id})\n"
        "**{pp}pp {stars:.2f}\u2605, {rank} {scoreboard_rank}{failed}+{modslist}**"
        "```diff\n"
        "  acc     300s  100s  50s  miss  combo\n"
        "{sign} {acc:<8.2%}{count300:<6}{count100:<6}{count50:<5}{countmiss:<6}{maxcombo}{max_combo}```"
        "{live}"
    ).format(
        host=host,
        beatmap_id=score["beatmap"]["id"],
        beatmapset_id=beatmap["beatmapset_id"],
        mode=score["mode"],
        sign="!" if acc == 1 else ("+" if score["perfect"] and score["passed"] else "-"),
        modslist=Mods.format_mods(score["mods"]),
        acc=acc,
        pp=round(score["pp"], 2),
        rank=score["rank"],
        count300=score["statistics"]["count_300"],
        count100=score["statistics"]["count_100"],
        count50=score["statistics"]["count_50"],
        countmiss=score["statistics"]["count_miss"],
        artist=score["beatmapset"]["artist"].replace("_", r"\_") if bool("beatmapset" in score) else
        beatmap["beatmapset"]["artist"].replace("_", r"\_"),
        title=score["beatmapset"]["title"].replace("_", r"\_") if bool("beatmapset" in score) else
        beatmap["beatmapset"]["title"].replace("_", r"\_"),
        i=("*" if "*" not in score["beatmapset"]["artist"] + score["beatmapset"]["title"] else "") if
        bool("beatmapset" in score) else
        ("*" if "*" not in beatmap["beatmapset"]["artist"] + beatmap["beatmapset"]["title"] else ""),
        # Escaping asterisk doesn't work in italics
        version=beatmap["version"],
        stars=float(beatmap["difficulty_rating"]),
        maxcombo=score["max_combo"],
        max_combo="/{}".format(beatmap["max_combo"]) if "max_combo" in beatmap and beatmap["max_combo"] is not None
        else "",
        scoreboard_rank="#{} ".format(rank) if rank else "",
        failed="(Failed) " if score["passed"] is False and score["rank"] != "F" else "",
        live=await format_stream(member, score, beatmap) if member else "",
    )


async def format_minimal_score(mode: api.GameMode, score: dict, beatmap: dict, rank: int, member: discord.Member):
    """ Format any osu! score with minimal content.
    There should be a member name/mention in front of this string. """
    acc = calculate_acc(mode, score)
    return (
        "[*{artist} - {title} [{version}]*]({host}beatmapsets/{beatmapset_id}/#{mode}/{beatmap_id})\n"
        "**{pp}pp {stars:.2f}\u2605, {maxcombo}{max_combo} {rank} {acc:.2%} {scoreboard_rank}+{mods}**"
        "{live}"
    ).format(
        host=host,
        beatmapset_id=beatmap["beatmapset_id"],
        mode=score["mode"],
        mods=Mods.format_mods(score["mods"]),
        acc=acc,
        beatmap_id=score["beatmap"]["id"],
        artist=beatmap["beatmapset"]["artist"].replace("*", "\*").replace("_", "\_"),
        title=beatmap["beatmapset"]["title"].replace("*", "\*").replace("_", "\_"),
        version=beatmap["version"],
        maxcombo=score["max_combo"],
        max_combo="/{}".format(beatmap["max_combo"]) if "max_combo" in beatmap and beatmap["max_combo"] is not None
        else "",
        rank=score["rank"],
        stars=float(beatmap["difficulty_rating"]),
        scoreboard_rank="#{} ".format(rank) if rank else "",
        live=await format_stream(member, score, beatmap),
        pp=round(score["pp"], 2)
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
        mode = api.GameMode.Standard
        mode.string = "osu"
        return mode

    value = int(osu_config.data["mode"][member_id])
    mode = api.GameMode(value)
    if mode == api.GameMode.Standard:
        mode.string = "osu"
    elif mode == api.GameMode.Taiko:
        mode.string = "taiko"
    elif mode == api.GameMode.Catch:
        mode.string = "fruits"
    elif mode == api.GameMode.Mania:
        mode.string = "mania"
    return mode


def get_update_mode(member_id: str):
    """ Return the member's update mode. """
    if member_id not in osu_config.data["update_mode"]:
        return UpdateModes.Full

    return UpdateModes.get_mode(osu_config.data["update_mode"][member_id])


def get_user_url(member_id: str):
    """ Return the user website URL. """
    user_id = osu_config.data["profiles"][member_id]

    return host + "users/" + user_id


def is_playing(member: discord.Member):
    """ Check if a member has "osu!" in their Game name. """
    # See if the member is playing
    for activity in member.activities:
        if activity is not None and activity.name is not None:
            if "osu" in activity.name.lower():
                return True
            elif activity is discord.ActivityType.streaming and "osu" in activity.game.lower():
                return True
    else:
        return False


async def update_user_data():
    """ Go through all registered members playing osu!, and update their data. """
    global osu_tracking

    # Go through each member playing and give them an "old" and a "new" subsection
    # for their previous and latest user data
    for member_id, profile in osu_config.data["profiles"].items():
        # Skip members who disabled tracking
        if get_update_mode(str(member_id)) is UpdateModes.Disabled:
            continue

        member = discord.utils.get(client.get_all_members(), id=int(member_id))
        if member is None:
            continue

        # Add the member to tracking
        if member_id not in osu_tracking:
            osu_tracking[member_id] = dict(member=member, ticks=-1)

        osu_tracking[str(member_id)]["ticks"] += 1

        # Only update members not tracked ingame every nth update
        if not is_playing(member) and osu_tracking[str(member_id)]["ticks"] % not_playing_skip > 0:
            # Update their old data to match their new one in order to avoid duplicate posts
            if "new" in osu_tracking[str(member_id)]:
                osu_tracking[str(member_id)]["old"] = osu_tracking[str(member_id)]["new"]
            continue

        # Get the user data for the player
        mode = get_mode(str(member_id))
        try:
            params = {
                "key": "id"
            }
            user_data = await api.get_user(profile, mode.string, params=params)
            if user_data is None:
                user_data = osu_tracking[str(member_id)]["new"]

            params = {
                "limit": 20
            }

            user_recent = await api.get_user_recent_activity(profile, params=params)
            if user_recent is None:
                user_recent = osu_tracking[str(member_id)]["new"]["events"]
        except aiohttp.ServerDisconnectedError:
            continue
        except asyncio.TimeoutError:
            logging.warning("Timed out when retrieving osu! info from {} ({})".format(member, profile))
            continue

        # Just in case something goes wrong, we skip this member (these things are usually one-time occurrences)
        if user_data is None:
            logging.info("Could not retrieve osu! info from {} ({})".format(member, profile))
            continue

        # User is already tracked
        if "new" in osu_tracking[str(member_id)]:
            # Move the "new" data into the "old" data of this user
            osu_tracking[str(member_id)]["old"] = osu_tracking[str(member_id)]["new"]
        else:
            # If this is the first time, update the user's list of scores for later
            params = {
                "mode": mode.string,
                "limit": score_request_limit,
            }
            fetched_scores = await api.get_user_scores(profile, "best", params=params)
            if fetched_scores is None:
                fetched_scores = osu_tracking[str(member_id)]["scores"]
            osu_tracking[str(member_id)]["scores"] = fetched_scores

        # Update the "new" data
        osu_tracking[str(member_id)]["new"] = user_data
        osu_tracking[str(member_id)]["new"]["events"] = user_recent
        await asyncio.sleep(3)


async def get_new_score(member_id: str):
    """ Compare old user scores with new user scores and return the discovered
    new score if there is any. When a score is returned, it's position in the
    player's top plays can be retrieved with score["pos"]. """
    # Download a list of the user's scores
    profile = osu_config.data["profiles"][member_id]
    params = {
        "mode": get_mode(member_id).string,
        "limit": score_request_limit,
    }
    await asyncio.sleep(10)
    user_scores = await api.get_user_scores(profile, "best", params=params)
    if user_scores is None:
        return None

    old_best_id = []

    for old_score in osu_tracking[member_id]["scores"]:
        old_best_id.append(old_score["best_id"])

    # Compare the scores from top to bottom and try to find a new one
    for i, score in enumerate(user_scores):
        if score["best_id"] not in old_best_id:
            if i == 0:
                logging.info(f"a #1 score was set: check plugins.osu.osu_tracking['{member_id}']['debug']")
                osu_tracking[member_id]["debug"] = dict(scores=user_scores,
                                                        old_scores=osu_tracking[member_id]["scores"],
                                                        old=dict(osu_tracking[member_id]["old"]),
                                                        new=dict(osu_tracking[member_id]["new"]))
            osu_tracking[member_id]["scores"] = user_scores

            # Calculate the difference in pp from the score below
            if i < len(osu_tracking[member_id]["scores"]) - 2:
                pp = float(score["pp"])
                diff = pp - float(user_scores[i + 1]["pp"])
            else:
                diff = 0
            return dict(score, pos=i + 1, diff=diff)
    else:
        logging.info(f"{member_id} gained PP, but no new score was found")
        return None


def get_diff(old, new, value, statistics=False):
    """ Get the difference between old and new osu! user data. """
    if statistics:
        return float(new["statistics"][value]) - float(old["statistics"][value])
    else:
        return float(new[value]) - float(old[value])


def get_notify_channels(guild: discord.Guild, data_type: str):
    """ Find the notifying channel or return the guild. """
    if str(guild.id) not in osu_config.data["guild"]:
        return None

    if data_type + "-channels" not in osu_config.data["guild"][str(guild.id)]:
        return None

    return [guild.get_channel(int(s)) for s in osu_config.data["guild"][str(guild.id)][data_type + "-channels"]
            if guild.get_channel(int(s))]


async def get_score_pp(osu_score, beatmap, member: discord.Member):
    mode = get_mode(str(member.id))
    mods = Mods.format_mods(osu_score["mods"])
    score_pp = None
    if mode is api.GameMode.Standard:
        try:
            score_pp = await calculate_pp(int(osu_score["beatmap"]["id"]), potential=True,
                                          ignore_osu_cache=not bool(beatmap["status"] == "ranked"
                                                                    or beatmap["status"] == "approved"),
                                          ignore_memory_cache=not bool(beatmap["status"] == "ranked"
                                                                       or beatmap["status"] == "approved"
                                                                       or beatmap["status"] == "loved"),
                                          *"{modslist}{acc:.2%} {acc: .2%}pot {c300}x300 {c100}x100 {c50}x50 "
                                          "{scorerank}rank {countmiss}m {maxcombo}x"
                                           .format(acc=calculate_acc(mode, osu_score),
                                                   potential_acc=calculate_acc(mode, osu_score, exclude_misses=True),
                                                   scorerank="F" if osu_score["passed"] is False else osu_score["rank"],
                                                   c300=osu_score["statistics"]["count_300"],
                                                   c100=osu_score["statistics"]["count_100"],
                                                   c50=osu_score["statistics"]["count_50"],
                                                   modslist="+" + mods + " " if mods != "Nomod" else "",
                                                   countmiss=osu_score["statistics"]["count_miss"],
                                                   maxcombo=osu_score["max_combo"]).split())
        except Exception as e:
            logging.error(e)
            pass
    return score_pp


def get_score_name(member: discord.Member, username: str):
    """ Formats the username and link for scores."""
    user_url = get_user_url(str(member.id))
    return "{member.mention} [`{name}`]({url})".format(member=member, name=username, url=user_url)


def get_formatted_score_embed(member: discord.Member, score: dict, formatted_score: str, potential_pp: tuple = None):
    embed = discord.Embed(color=member.color, url=get_user_url(str(member.id)))
    embed.description = formatted_score
    footer = ""

    # Add potential pp in the footer
    if potential_pp:
        footer += "Potential: {0:,.2f}pp, {1:+.2f}pp".format(potential_pp.max_pp,
                                                             potential_pp.max_pp - float(score["pp"]))

    # Add completion rate to footer if score is failed
    if score["passed"] is False:
        objects = score["statistics"]["count_300"] + score["statistics"]["count_100"] + \
                  score["statistics"]["count_50"] + score["statistics"]["count_miss"]

        beatmap_objects = score["beatmap"]["count_circles"] + score["beatmap"]["count_sliders"] \
                                                            + score["beatmap"]["count_spinners"]
        footer += "\nCompletion rate: {completion_rate:.2f}% ({partial_sr}\u2605)".format(
            completion_rate=(objects / beatmap_objects) * 100, partial_sr=round(potential_pp.partial_stars, 2))

    embed.set_footer(text=footer)
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

    rank_diff = -int(get_diff(old, new, "global_rank", statistics=True))
    country_rank_diff = -int(get_diff(old, new, "country_rank", statistics=True))
    accuracy_diff = get_diff(old, new, "hit_accuracy", statistics=True)  # Percent points difference

    member = data["member"]
    mode = get_mode(member_id)
    update_mode = get_update_mode(member_id)
    m = ""
    potential_pp = None

    # Since the user got pp they probably have a new score in their own top 100
    # If there is a score, there is also a beatmap
    if update_mode is UpdateModes.PP:
        score = None
    else:
        score = await get_new_score(member_id)

    # If a new score was found, format the score
    if score:
        params = {
            "beatmap_id": score["beatmap"]["id"],
        }
        beatmap = (await api.beatmap_lookup(params=params, map_id=score["beatmap"]["id"], mode=mode.string))

        # There might not be any events
        scoreboard_rank = None
        if new["events"]:
            scoreboard_rank = api.rank_from_events(new["events"], str(score["beatmap"]["id"]), score)
        if update_mode is not UpdateModes.PP:
            potential_pp = await get_score_pp(score, beatmap, member)

        beatmap["difficulty_rating"] = potential_pp.stars if potential_pp is not None \
            and potential_pp.stars is not None and mode is api.GameMode.Standard else beatmap["difficulty_rating"]
        if update_mode is UpdateModes.Minimal:
            m += await format_minimal_score(mode, score, beatmap, scoreboard_rank, member) + "\n"
        else:
            m += await format_new_score(mode, score, beatmap, scoreboard_rank, member)

    # Always add the difference in pp along with the ranks
    m += format_user_diff(mode, pp_diff, rank_diff, country_rank_diff, accuracy_diff, old["country"]["code"], new)

    # Send the message to all guilds
    for guild in client.guilds:
        member = guild.get_member(int(member_id))
        channels = get_notify_channels(guild, "score")
        if not member or not channels:
            continue

        primary_guild = get_primary_guild(str(member.id))
        is_primary = True if primary_guild is None else (True if primary_guild == str(guild.id) else False)

        # Format the url and the username
        name = get_score_name(member, new["username"])
        embed = get_formatted_score_embed(member, score, m, potential_pp if potential_pp is not None
                                          and potential_pp.max_pp is not None and potential_pp.max_pp - score["pp"] > 1
                                          and not bool(score["perfect"] and score["passed"]) else None)
        if score:
            embed.set_thumbnail(url=beatmap["beatmapset"]["covers"]["list@2x"])

        # The top line of the format will differ depending on whether we found a score or not
        if score:
            embed.description = "**{0} set a new best `(#{pos}/{1} +{diff:.2f}pp)` on**\n".format(name,
                                                                                                  score_request_limit,
                                                                                                  **score) + m
        else:
            embed.description = name + "\n" + m

        for i, channel in enumerate(channels):
            try:
                await client.send_message(channel, embed=embed)

                # In the primary guild and if the user sets a score, send a mention and delete it
                # This will only mention in the first channel of the guild
                if use_mentions_in_scores and score and i == 0 and is_primary \
                        and update_mode is not UpdateModes.NoMention:
                    mention = await client.send_message(channel, member.mention)
                    await client.delete_message(mention)
            except discord.Forbidden:
                pass


async def format_beatmapset_diffs(beatmapset):
    """ Format some difficulty info on a beatmapset. """
    # Get the longest difficulty name
    diff_length = len(max((diff["version"] for diff in beatmapset["beatmaps"]), key=len))
    if diff_length > max_diff_length:
        diff_length = max_diff_length
    elif diff_length < len("difficulty"):
        diff_length = len("difficulty")

    m = "```elm\n" \
        "M {version: <{diff_len}}  Stars  Drain  PP".format(version="Difficulty", diff_len=diff_length)

    for diff in sorted(beatmapset["beatmaps"], key=lambda d: float(d["difficulty_rating"])):
        diff_name = diff["version"]
        m += "\n{gamemode: <2}{name: <{diff_len}}  {stars: <7}{drain: <7}{pp}".format(
            gamemode=api.GameMode(int(diff["mode_int"])).name[0],
            name=diff_name if len(diff_name) < max_diff_length else diff_name[:max_diff_length - 3] + "...",
            diff_len=diff_length,
            stars="{:.2f}\u2605".format(float(diff["difficulty_rating"])),
            pp="{}pp".format(int(diff.get("pp", "0"))),
            drain="{}:{:02}".format(*divmod(int(diff["hit_length"]), 60))
        )

    return m + "```"


async def format_beatmap_info(beatmapset):
    """ Format some difficulty info on a beatmapset. """
    # Get the longest difficulty name
    diff_length = len(max((diff["version"] for diff in beatmapset["beatmaps"]), key=len))
    if diff_length > max_diff_length + 1:
        diff_length = max_diff_length + 1
    elif diff_length < len("difficulty"):
        diff_length = len("difficulty")

    m = "```elm\n" \
        "{version: <{diff_len}}  Drain  BPM  Passrate".format(version="Difficulty", diff_len=diff_length)

    for diff in sorted(beatmapset["beatmaps"], key=lambda d: float(d["difficulty_rating"])):
        diff_name = diff["version"]
        pass_rate = "Not passed yet"
        if not diff["passcount"] == 0 and not diff["playcount"] == 0:
            pass_rate = "{:.2f}%".format((diff["passcount"] / diff["playcount"]) * 100)

        m += "\n{name: <{diff_len}}  {drain: <7}{bpm: <5}{passrate}\n\nOD   CS   AR   HP   Max Combo\n{od: <5}" \
             "{cs: <5}{ar: <5}{hp: <5}{maxcombo}\n\nAim PP  Speed PP  Acc PP  Total PP\n{aim_pp: <8}{speed_pp: <10}" \
             "{acc_pp: <8}{pp}\n\nAim Stars  Speed Stars  Total Stars\n{aim_stars: <11}{speed_stars: <13}" \
             "{stars}".format(
              gamemode=api.GameMode(int(diff["mode_int"])).name[0],
              name=diff_name if len(diff_name) < max_diff_length else diff_name[:max_diff_length - 2] + "...",
              diff_len=diff_length,
              stars="{:.2f}\u2605".format(float(diff["difficulty_rating"])),
              pp="{}pp".format(int(diff.get("pp", "0"))),
              drain="{}:{:02}".format(*divmod(int(diff["hit_length"]), 60)),
              aim_pp="{}pp".format(int(diff.get("aim_pp", "0"))),
              speed_pp="{}pp".format(int(diff.get("speed_pp", "0"))),
              acc_pp="{}pp".format(int(diff.get("acc_pp", "0"))),
              passrate=pass_rate,
              od=diff["accuracy"],
              ar=diff["ar"],
              hp=diff["drain"],
              cs=diff["cs"],
              aim_stars="{:.2f}\u2605".format(float(diff["aim_stars"])),
              speed_stars="{:.2f}\u2605".format(float(diff["speed_stars"])),
              bpm=int(diff["bpm"]),
              maxcombo="{}x".format(diff["max_combo"])
             )

    return m + "```"


async def format_map_status(member: discord.Member, status_format: str, beatmapset, minimal: bool, user_update=True,
                            beatmap=False):
    """ Format the status update of a beatmap. """
    if user_update:
        user_id = osu_config.data["profiles"][str(member.id)]
        name = member.display_name
    else:
        user_id = beatmapset["user_id"]
        name = beatmapset["creator"]
    status = status_format.format(name=name, user_id=user_id, host=host, artist=beatmapset["artist"],
                                  title=beatmapset["title"], id=beatmapset["id"])
    if not minimal:
        if not beatmap:
            status += await format_beatmapset_diffs(beatmapset)
            embed = discord.Embed(color=member.color, description=status)
            embed.set_image(url=beatmapset["covers"]["cover@2x"])
        else:
            status += await format_beatmap_info(beatmapset)
            embed = discord.Embed(color=member.color, description=status)
            embed.set_image(url=beatmapset["covers"]["cover@2x"])
    else:
        embed = discord.Embed(color=member.color, description=status)
        embed.set_image(url=beatmapset["covers"]["cover@2x"])

    return embed


async def calculate_pp_for_beatmapset(beatmapset, ignore_osu_cache: bool = False, ignore_memory_cache: bool = False):
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

    for i, diff in enumerate(beatmapset["beatmaps"]):
        map_id = str(diff["id"])
        # Skip any diff that's not standard osu!
        if int(diff["mode_int"]) != api.GameMode.Standard.value:
            continue

        if ignore_osu_cache:
            # If the diff is cached and unchanged, use the cached pp
            if map_id in cached_mapset:
                if diff["checksum"] == cached_mapset[map_id]["md5"] and "speed_pp" in cached_mapset[map_id]:
                    diff["pp"] = cached_mapset[map_id]["pp"]
                    diff["aim_pp"] = cached_mapset[map_id]["aim_pp"]
                    diff["speed_pp"] = cached_mapset[map_id]["speed_pp"]
                    diff["acc_pp"] = cached_mapset[map_id]["acc_pp"]
                    diff["aim_stars"] = cached_mapset[map_id]["aim_stars"]
                    diff["speed_stars"] = cached_mapset[map_id]["speed_stars"]
                    continue

                # If it was changed, add an asterisk to the beatmap name (this is a really stupid place to do this)
                diff["version"] = "*" + diff["version"]

        # If the diff is not cached, or was changed, calculate the pp and update the cache
        try:
            pp_stats = await calculate_pp(int(map_id), ignore_osu_cache=ignore_osu_cache, map_calc=True)
        except ValueError:
            logging.error(traceback.format_exc())
            continue

        diff["pp"] = pp_stats.pp
        diff["aim_pp"] = pp_stats.aim_pp
        diff["speed_pp"] = pp_stats.speed_pp
        diff["acc_pp"] = pp_stats.acc_pp
        diff["aim_stars"] = pp_stats.aim_stars
        diff["speed_stars"] = pp_stats.speed_stars

        if ignore_osu_cache:
            # Cache the difficulty
            osu_config.data["map_cache"][set_id][map_id] = {
                "md5": diff["checksum"],
                "pp": pp_stats.pp,
                "aim_stars": pp_stats.aim_stars,
                "speed_stars": pp_stats.speed_stars,
                "aim_pp": pp_stats.aim_pp,
                "speed_pp": pp_stats.speed_pp,
                "acc_pp": pp_stats.acc_pp,
            }
    if ignore_osu_cache:
        await osu_config.asyncsave()


async def notify_maps(member_id: str, data: dict):
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
            beatmapset = await api.beatmapset_from_url("https://osu.ppy.sh" + event["beatmapset"]["url"],
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

        new_event = MapEvent(text=str(event["beatmapset"]["title"] + event["type"] + (event["approval"] if
                                      event["type"] == "beatmapsetApprove" else "")))
        prev = discord.utils.get(recent_map_events, text=str(event["beatmapset"]["title"] + event["type"] +
                                                             (event["approval"] if
                                                             event["type"] == "beatmapsetApprove" else "")))
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
        for guild in client.guilds:
            member = guild.get_member(int(member_id))
            channels = get_notify_channels(guild, "map")  # type: list

            if not member or not channels:
                continue

            for channel in channels:
                # Do not format difficulties when minimal (or pp) information is specified
                update_mode = get_update_mode(member_id)
                embed = await format_map_status(member, status_format, beatmapset,
                                                update_mode is not UpdateModes.Full,
                                                beatmap=bool(len(beatmapset["beatmaps"]) == 1
                                                             and beatmapset["beatmaps"][0]["mode"] == "osu"))

                if new_event.count > 1:
                    embed.set_footer(text="updated {} times since".format(new_event.count))
                    embed.timestamp = new_event.time_created

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


async def on_ready():
    """ Handle every event. """
    global time_elapsed

    # Notify the owner when they have not set their API key
    if osu_config.data["client_secret"] == "change to your client secret":
        logging.warning("osu! functionality is unavailable until a "
                        "client ID and client secret is provided (config/osu.json)")

    while not client.loop.is_closed():
        try:
            await asyncio.sleep(float(update_interval), loop=client.loop)
            started = datetime.now()

            # First, update every user's data
            await update_user_data()

            # Next, check for any differences in pp between the "old" and the "new" subsections
            # and notify any guilds
            # NOTE: This used to also be ensure_future before adding the potential pp check.
            # The reason for this change is to ensure downloading and running the .osu files won't happen twice
            # at the same time, which would cause problems retrieving the correct potential pp.
            for member_id, data in osu_tracking.items():
                await notify_pp(str(member_id), data)

            # Check for any differences in the users' events and post about map updates
            # NOTE: the same applies to this now. These can't be concurrent as they also calculate pp.
            for member_id, data in osu_tracking.items():
                await notify_maps(str(member_id), data)
        except aiohttp.ClientOSError as e:
            logging.error(str(e))
        except asyncio.CancelledError:
            return
        except:
            logging.error(traceback.format_exc())
        finally:
            pass
            # TODO: setup logging

            # Save the time elapsed since we started the update
            time_elapsed = (datetime.now() - started).total_seconds()


async def on_reload(name: str):
    """ Preserve the tracking cache. """
    global osu_tracking, recent_map_events
    local_tracking = osu_tracking
    local_events = recent_map_events
    local_requests = api.requests_sent

    importlib.reload(plugins.osulib.api)
    importlib.reload(plugins.osulib.ordr)
    importlib.reload(plugins.osulib.args)
    importlib.reload(plugins.osulib.pp)
    await plugins.reload(name)

    api.requests_sent = local_requests
    osu_tracking = local_tracking
    recent_map_events = local_events


def get_timestamps_with_url(content: str):
    """ Yield every map timestamp found in a string, and an edditor url.

    :param content: The string to search
    :returns: a tuple of the timestamp as a raw string and an editor url
    """
    for match in timestamp_pattern.finditer(content):
        url = match.group(1).strip(" ").replace(" ", "%20").replace(")", r")")
        yield match.group(0), "<osu://edit/{}>".format(url)


@plugins.event()
async def on_message(message):
    # Ignore commands
    if message.content.startswith("!"):
        return

    timestamps = ["{} {}".format(stamp, url) for stamp, url in get_timestamps_with_url(message.content)]
    if timestamps:
        await client.send_message(message.channel,
                                  embed=discord.Embed(color=message.author.color,
                                                      description="\n".join(timestamps)))
        return True


@plugins.command(aliases="circlesimulator eba", usage="[member] [mode]")
async def osu(message: discord.Message, *options):
    """ Handle osu! commands.

    When your user is linked, this plugin will check if you are playing osu!
    (your profile would have `playing osu!`), and send updates whenever you set a
    new top score. """
    member = None
    mode = None

    for value in options:
        member = utils.find_member(guild=message.guild, name=value)
        if member:
            continue
        else:
            mode = api.GameMode.get_mode(value)

    if member is None:
        member = message.author

    # Make sure the member is assigned
    assert str(member.id) in osu_config.data[
        "profiles"], "No osu! profile assigned to **{}**! Please assign a profile using {}osu link".format(
        member.name, botconfig.guild_command_prefix(member.guild))

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
    signature = await utils.retrieve_page("https://lemmmy.pw/osusig/sig.php", head=True, **params, **dark)
    embed = discord.Embed(color=member.color)
    embed.set_author(name=member.display_name, icon_url=member.avatar_url, url=get_user_url(str(member.id)))
    embed.set_image(url=signature.url)
    await client.send_message(message.channel, embed=embed)


async def has_enough_pp(user, mode, **params):
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
    assert "id" in osu_user, "osu! user `{}` does not exist.".format(name)
    user_id = osu_user["id"]

    if osu_user["playmode"] == "osu":
        mode = api.GameMode.Standard
    elif osu_user["playmode"] == "taiko":
        mode = api.GameMode.Taiko
    elif osu_user["playmode"] == "fruits":
        mode = api.GameMode.Catch
    elif osu_user["playmode"] == "mania":
        mode = api.GameMode.Mania
    else:
        mode = api.GameMode.Standard

    # Make sure the user has more pp than the minimum limit defined in config
    if float(osu_user["statistics"]["pp"]) < minimum_pp_required:
        # Perhaps the user wants to display another gamemode
        await client.say(message,
                         "**You have less than the required {}pp.\nIf you have enough in a different mode, please "
                         "enter your gamemode below. Valid gamemodes are `{}`.**".format(minimum_pp_required,
                                                                                         gamemodes))

        def check(m):
            return m.author == message.author and m.channel == message.channel

        try:
            reply = await client.wait_for_message(timeout=60, check=check)
        except asyncio.TimeoutError:
            return

        mode = api.GameMode.get_mode(reply.content)
        assert mode is not None, "**The given gamemode is invalid.**"
        assert await has_enough_pp(user=user_id, mode=mode.string), \
            "**Your pp in {} is less than the required {}pp.**".format(mode.name, minimum_pp_required)

    # Clear the scores when changing user
    if str(message.author.id) in osu_tracking:
        del osu_tracking[str(message.author.id)]

    user_id = osu_user["id"]

    # Assign the user using their unique user_id
    osu_config.data["profiles"][str(message.author.id)] = str(user_id)
    osu_config.data["mode"][str(message.author.id)] = mode.value
    osu_config.data["primary_guild"][str(message.author.id)] = str(message.guild.id)
    await osu_config.asyncsave()
    await client.say(message, "Set your osu! profile to `{}`.".format(osu_user["username"]))


@osu.command(aliases="unset")
async def unlink(message: discord.Message, member: discord.Member = Annotate.Self):
    """ Unlink your osu! account or unlink the member specified (**Owner only**). """
    # The message author is allowed to unlink himself
    # If a member is specified and the member is not the owner, set member to the author
    if not plugins.is_owner(message.author):
        member = message.author

    # The member might not be linked to any profile
    assert str(member.id) in osu_config.data["profiles"], "No osu! profile assigned to **{}**!".format(member.name)

    # Clear the tracking data when unlinking user
    if str(member.id) in osu_tracking:
        del osu_tracking[str(member.id)]

    # Unlink the given member (usually the message author)
    del osu_config.data["profiles"][str(member.id)]
    await osu_config.asyncsave()
    await client.say(message, "Unlinked **{}'s** osu! profile.".format(member.name))


@osu.command(aliases="mode m track", error="Valid gamemodes: `{}`".format(gamemodes), doc_args=dict(modes=gamemodes))
async def gamemode(message: discord.Message, mode: api.GameMode.get_mode):
    """ Sets the command executor's gamemode.

    Gamemodes are: `{modes}`. """
    assert str(message.author.id) in osu_config.data["profiles"], \
        "No osu! profile assigned to **{}**!".format(message.author.name)

    user_id = osu_config.data["profiles"][str(message.author.id)]
    if mode == api.GameMode.Standard:
        mode.string = "osu"
    elif mode == api.GameMode.Taiko:
        mode.string = "taiko"
    elif mode == api.GameMode.Catch:
        mode.string = "fruits"
    elif mode == api.GameMode.Mania:
        mode.string = "mania"

    assert await has_enough_pp(user=user_id, mode=mode.string), \
        "**Your pp in {} is less than the required {}pp.**".format(mode.name, minimum_pp_required)

    osu_config.data["mode"][str(message.author.id)] = mode.value
    await osu_config.asyncsave()

    # Clear the scores when changing mode
    if str(message.author.id) in osu_tracking:
        del osu_tracking[str(message.author.id)]

    await client.say(message, "Set your gamemode to **{}**.".format(mode.name))


@osu.command()
async def info(message: discord.Message, member: discord.Member = Annotate.Self):
    """ Display configuration info. """
    # Make sure the member is assigned
    assert str(member.id) in osu_config.data["profiles"], "No osu! profile assigned to **{}**!".format(member.name)

    user_id = osu_config.data["profiles"][str(member.id)]
    mode = get_mode(str(member.id))
    update_mode = get_update_mode(str(member.id))

    e = discord.Embed(color=member.color)
    e.set_author(name=member.display_name, icon_url=member.avatar_url, url=host + "users/" + user_id)
    e.add_field(name="Game Mode", value=mode.name)
    e.add_field(name="Notification Mode", value=update_mode.name)
    e.add_field(name="Playing osu!", value="YES" if is_playing(member) else "NO")

    await client.send_message(message.channel, embed=e)


doc_modes = ", ".join(m.name.lower() for m in UpdateModes)


@osu.command(aliases="n updatemode", error="Valid modes: `{}`".format(doc_modes), doc_args=dict(modes=doc_modes))
async def notify(message: discord.Message, mode: UpdateModes.get_mode):
    """ Sets the command executor's update notification mode. This changes
    how much text is in each update, or if you want to disable them completely.

    Update modes are: `{modes}`. """
    assert str(message.author.id) in osu_config.data["profiles"], \
        "No osu! profile assigned to **{}**!".format(message.author.name)

    osu_config.data["update_mode"][str(message.author.id)] = mode.name
    await osu_config.asyncsave()

    # Clear the scores when disabling mode
    if str(message.author.id) in osu_tracking and mode == UpdateModes.Disabled:
        del osu_tracking[str(message.author.id)]

    await client.say(message, "Set your update notification mode to **{}**.".format(mode.name.lower()))


@osu.command()
async def url(message: discord.Message, member: discord.Member = Annotate.Self,
              section: str.lower = None):
    """ Display the member's osu! profile URL. """
    # Member might not be registered
    assert str(member.id) in osu_config.data["profiles"], "No osu! profile assigned to **{}**!".format(member.name)

    # Send the URL since the member is registered
    await client.say(message, "**{0.display_name}'s profile:** <{1}{2}>".format(
        member, get_user_url(str(member.id)), "#_{}".format(section) if section else ""))


async def pp_(message: discord.Message, beatmap_url: str, *options):
    """ Calculate and return the would be pp using `oppai-ng`.

    The beatmap url should either be a link to a beatmap /b/ or /s/, or an
    uploaded .osu file.

    Options are a parsed set of command-line arguments:  /
    `([acc]% | [num_100s]x100 [num_50s]x50) +[mods] [combo]x [misses]m scorev[scoring_version] ar[ar] od[od] cs[cs]`

    **Additionally**, PCBOT includes a *find closest pp* feature. This works as an
    argument in the options, formatted like `[pp_value]pp`
    """
    try:
        pp_stats = await calculate_pp(beatmap_url, *options, ignore_osu_cache=True)
    except ValueError as e:
        await client.say(message, str(e))
        return

    options = list(options)
    if type(pp_stats) is ClosestPPStats:
        # Remove any accuracy percentage from options as we're setting this manually, and remove unused options
        for opt in options:
            if opt.endswith("%") or opt.endswith("pp") or opt.endswith("x300") or opt.endswith("x100") or opt.endswith(
                    "x50"):
                options.remove(opt)

        options.insert(0, "{}%".format(pp_stats.acc))

    await client.say(message,
                     "*{artist} - {title}* **[{version}] {0}** {stars:.02f}\u2605 would be worth `{pp:,.02f}pp`.".format(
                         " ".join(options), **pp_stats._asdict()))


if can_calc_pp:
    plugins.command(name="pp", aliases="oppai")(pp_)
    osu.command(name="pp", aliases="oppai")(pp_)


async def create_score_embed_with_pp(member: discord.Member, score, beatmap, mode, potential_pp: bool = False,
                                     scoreboard_rank: bool = False):
    score_pp = await get_score_pp(score, beatmap, member)

    if score_pp is not None and score["pp"] is None:
        score["pp"] = round(score_pp.pp, 2)
    elif score["pp"] is None:
        score["pp"] = 0
    if score_pp is not None:
        beatmap["difficulty_rating"] = score_pp.stars if mode is api.GameMode.Standard else beatmap["difficulty_rating"]

    # There might not be any events
    if scoreboard_rank is False and str(member.id) in osu_tracking and "new" in osu_tracking[str(member.id)] \
            and osu_tracking[str(member.id)]["new"]["events"]:
        scoreboard_rank = api.rank_from_events(osu_tracking[str(member.id)]["new"]["events"],
                                               str(score["beatmap"]["id"]), score)

    embed = get_formatted_score_embed(member, score, await format_new_score(mode, score, beatmap, scoreboard_rank),
                                      score_pp if score_pp is not None and score_pp.max_pp is not None and
                                      score_pp.max_pp - score["pp"] > 1 and not bool(score["perfect"]
                                                                                     and score["passed"]) else None)
    embed.set_author(name=member.display_name, icon_url=member.avatar_url, url=get_user_url(str(member.id)))
    embed.set_thumbnail(url=score["beatmapset"]["covers"]["list@2x"] if bool(
        "beatmapset" in score) else beatmap["beatmapset"]["covers"]["list@2x"])
    return embed


async def recent(message: discord.Message, member: Annotate.Member = Annotate.Self):
    """ Display your or another member's most recent score. """
    assert str(member.id) in osu_config.data["profiles"], \
        "No osu! profile assigned to **{}**!".format(member.name)

    user_id = osu_config.data["profiles"][str(member.id)]
    mode = get_mode(str(member.id))

    params = {
        "include_fails": 1,
        "mode": mode.string,
        "limit": 1
    }

    scores = await api.get_user_scores(user_id, "recent", params=params)
    assert scores, "Found no recent score."

    score = scores[0]

    params = {
        "beatmap_id": score["beatmap"]["id"],
    }
    beatmap = (await api.beatmap_lookup(params=params, map_id=int(score["beatmap"]["id"]), mode=mode.string))

    embed = await create_score_embed_with_pp(member, score, beatmap, mode, potential_pp=not bool(
        bool(score["perfect"]) and bool(score["passed"])))
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
        time_since_render = datetime.now() - last_rendered[message.author.id]
        in_minutes = time_since_render.total_seconds() / 60
        if in_minutes < 5:
            await client.say(message, "It's been less than 5 minutes since your last render. "
                                      "Please wait before trying again")
            return

    assert replay_url, "No replay provided"
    render_job = await ordr.send_render_job(replay_url)

    assert isinstance(render_job, dict), \
        "An error occured when sending this replay:\n{}".format(render_job)

    if "renderID" not in render_job:
        await client.say(message, "An error occured when sending this replay:\n{}".format(render_job["message"]))
        return

    last_rendered[message.author.id] = datetime.now()

    e = discord.Embed(color=message.author.color)
    e.description = "Progress: Rendering 0%"

    placeholder_msg = await client.send_message(message.channel, embed=e)

    render_complete = False
    video_url = ""

    while not render_complete:
        ordr_render = await ordr.get_render(render_job["renderID"])
        if not utils.http_url_pattern.match(ordr_render["videoUrl"]):
            await asyncio.sleep(10)
            e.description = "Progress: {}".format(ordr_render["progress"])
            await placeholder_msg.edit(embed=e)
            if "error" in ordr_render["progress"].lower():
                return
        else:
            e.description = "Progress: {}".format(ordr_render["progress"])
            video_url = ordr_render["videoUrl"]
            render_complete = True

    await placeholder_msg.edit(content=video_url, embed=None)


async def score(message: discord.Message, *options):
    """ Display your own or the member's score on a beatmap.
    If URL is not provided it searches the last 10 messages for a URL. """
    member = None
    beatmap_url = None

    for value in options:
        if not utils.http_url_pattern.match(value):
            member = utils.find_member(guild=message.guild, name=value)
        else:
            beatmap_url = value

    if not member:
        member = message.author

    assert str(member.id) in osu_config.data["profiles"], \
        "No osu! profile assigned to **{}**!".format(member.name)

    if not beatmap_url:
        beatmap_id = None
        match = False
        async for m in message.channel.history(limit=10):
            to_search = m.content
            if m.embeds:
                for embed in m.embeds:
                    to_search += embed.description if embed.description else ""
                    to_search += embed.title if embed.title else ""
                    to_search += embed.footer.text if embed.footer else ""
            match_v1 = api.beatmap_url_pattern_v1.search(to_search)
            if match_v1:
                if match_v1.group("type") == "b":
                    beatmap_id = match_v1.group("id")
                match = True
                break

            match_v2_beatmapset = api.beatmapset_url_pattern_v2.search(to_search)
            if match_v2_beatmapset:
                if match_v2_beatmapset.group("mode") is not None:
                    beatmap_id = match_v2_beatmapset.group("beatmap_id")
                match = True
                break

            match_v2_beatmap = api.beatmap_url_pattern_v2.search(to_search)
            if match_v2_beatmap:
                beatmap_id = match_v2_beatmap.group("beatmap_id")
                match = True
                break

        if not match:
            await client.say(message, "No beatmap link found")
            return
    else:
        try:
            beatmap_info = api.parse_beatmap_url(beatmap_url)
            beatmap_id = beatmap_info.beatmap_id
        except SyntaxError as e:
            await client.say(message, e)
            return

    user_id = osu_config.data["profiles"][str(member.id)]
    mode = get_mode(str(member.id))

    assert beatmap_id, "Please link to a specific difficulty"
    params = {
        "mode": mode.string,
    }
    scores = await api.get_user_beatmap_score(beatmap_id, user_id, params=params)
    assert scores, "Found no scores by **{}**.".format(member.name)

    score = scores["score"]
    scoreboard_rank = scores["position"]

    params = {
        "beatmap_id": score["beatmap"]["id"],
    }
    beatmap = (await api.beatmap_lookup(params=params, map_id=score["beatmap"]["id"], mode=mode.string))

    embed = await create_score_embed_with_pp(member, score, beatmap, mode, potential_pp=not bool(
        bool(score["perfect"]) and bool(score["passed"])), scoreboard_rank=scoreboard_rank)
    await client.send_message(message.channel, embed=embed)


plugins.command(name="score", usage="[member] <url>")(score)
osu.command(name="score", usage="[member] <url>")(score)


@osu.command(aliases="map")
async def mapinfo(message: discord.Message, beatmap_url: str):
    """ Display simple beatmap information. """
    try:
        beatmapset = await api.beatmapset_from_url(beatmap_url)
        await calculate_pp_for_beatmapset(beatmapset)
    except Exception as e:
        await client.say(message, e)
        return

    status = "[**{artist} - {title}**]({host}beatmapsets/{id}) submitted by [**{name}**]({host}users/{user_id})"
    embed = await format_map_status(status_format=status, beatmapset=beatmapset, minimal=False,
                                    member=message.author, user_update=False,
                                    beatmap=bool(len(beatmapset["beatmaps"]) == 1
                                                 and beatmapset["beatmaps"][0]["mode"] == "osu"))
    await client.send_message(message.channel, embed=embed)


@osu.command()
async def top(message: discord.Message, member: Annotate.Member = Annotate.Self):
    """ Displays your or the selected member's 5 highest rated plays by PP. """
    assert str(member.id) in osu_config.data["profiles"], \
        "No osu! profile assigned to **{}**!".format(member.name)

    m = ""
    mode = get_mode(str(member.id))
    if str(member.id) in osu_tracking and "scores" in osu_tracking[str(member.id)]:
        for i, osu_score in enumerate(osu_tracking[str(member.id)]["scores"]):
            if i > 4:
                break
            params = {
                "beatmap_id": osu_score["beatmap"]["id"]
            }
            beatmap = (await api.beatmap_lookup(params=params, map_id=osu_score["beatmap"]["id"], mode=mode.string))
            score_pp = await get_score_pp(osu_score, beatmap, member)
            if score_pp is not None:
                beatmap["difficulty_rating"] = score_pp.stars if mode is api.GameMode.Standard else beatmap[
                    "difficulty_rating"]

            # Add time since play to the score
            time_since_play = "{} ago".format(
                pendulum.now("UTC").diff(pendulum.parse(osu_score["created_at"])).in_words())

            potential_string = None
            # Add potential pp to the score
            if score_pp is not None and score_pp.max_pp is not None and score_pp.max_pp - osu_score["pp"] > 1 \
                    and not osu_score["perfect"]:
                potential_string = "Potential: {0:,.2f}pp, {1:+.2f}pp".format(score_pp.max_pp,
                                                                              score_pp.max_pp - float(osu_score["pp"]))

            m += "{}.\n".format(str(i+1)) + \
                 await format_new_score(mode, osu_score, beatmap, rank=None,
                                        member=osu_tracking[str(member.id)]["member"]) + time_since_play + "\n" \
                 + (potential_string + "\n" if potential_string is not None else "") + "\n"
    else:
        await client.say(message, "Scores have not been retrieved for this user yet. Please wait a bit and try again")
        return None
    e = discord.Embed(color=message.author.color)
    e.description = m
    e.set_author(name=member.display_name, icon_url=member.avatar_url, url=get_user_url(str(member.id)))
    e.set_thumbnail(url=osu_tracking[str(member.id)]["new"]["avatar_url"])
    await client.send_message(message.channel, embed=e)


def init_guild_config(guild: discord.Guild):
    """ Initializes the config when it's not already set. """
    if str(guild.id) not in osu_config.data["guild"]:
        osu_config.data["guild"][str(guild.id)] = {}
        osu_config.save()


@osu.command(aliases="configure cfg")
async def config(message, _: utils.placeholder):
    """ Manage configuration for this plugin. """
    pass


@config.command(alias="score", permissions="manage_guild")
async def scores(message: discord.Message, *channels: discord.TextChannel):
    """ Set which channels to post scores to. """
    init_guild_config(message.guild)
    osu_config.data["guild"][str(message.guild.id)]["score-channels"] = list(str(c.id) for c in channels)
    await osu_config.asyncsave()
    await client.say(message, "**Notifying scores in**: {}".format(
        utils.format_objects(*channels, sep=" ") or "no channels"))


@config.command(alias="map", permissions="manage_guild")
async def maps(message: discord.Message, *channels: discord.TextChannel):
    """ Set which channels to post map updates to. """
    init_guild_config(message.guild)
    osu_config.data["guild"][str(message.guild.id)]["map-channels"] = list(c.id for c in channels)
    await osu_config.asyncsave()
    await client.say(message, "**Notifying map updates in**: {}".format(
        utils.format_objects(*channels, sep=" ") or "no channels"))


@osu.command(owner=True)
async def debug(message: discord.Message):
    """ Display some debug info. """
    await client.say(message, "Sent `{}` requests since the bot started (`{}`).\n"
                              "Sent an average of `{}` requests per minute. \n"
                              "Spent `{:.3f}` seconds last update.\n"
                              "Members registered as playing: {}\n"
                              "Total members tracked: `{}`".format(
        api.requests_sent, client.time_started.ctime(),
        round(api.requests_sent / ((datetime.utcnow() - client.time_started).total_seconds() / 60.0),
              2) if api.requests_sent > 0 else 0,
        time_elapsed,
        utils.format_objects(*[d["member"] for d in osu_tracking.values() if is_playing(d["member"])], dec="`"),
        len(osu_tracking)
    ))
