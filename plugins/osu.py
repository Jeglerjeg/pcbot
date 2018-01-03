""" Plugin for osu! commands

This plugin will notify any registered user's pp difference and if they
set a new best also post that. It also includes many osu! features, such
as a signature generator, pp calculation and user map updates.

TUTORIAL:
    A member with Manage Server permission must first assign one or more channels
    that the bot should post scores or map updates in.
    See: !help osu config

    Members may link their osu! profile with `!osu link <name ...>`. The bot will
    only keep track of players who either has `osu` in their playing name, e.g:
        Playing osu!
    or has their rank as #xxx, for instance:
        Streaming Chill | #4 Norway

    This plugin might send a lot of requests, so keep up to date with the
    !osu debug command.

    The pp command requires that you setup pyoppai
    https://github.com/Francesco149/oppai/tree/master/pyoppai

    Check the readme in the link above for install instructions.

Commands:
    osu
    pp
"""

import logging
import re
from datetime import datetime, timedelta
from enum import Enum
from traceback import print_exc
from typing import List

import asyncio
import discord
from aiohttp import ServerDisconnectedError

import plugins
from pcbot import Config, utils, Annotate
from plugins.osulib import api, Mods, calculate_pp, pyoppai, ClosestPPStats
from plugins.twitchlib import twitch


client = plugins.client  # type: discord.Client

# Configuration data for this plugin, including settings for members and the API key
osu_config = Config("osu", pretty=True, data=dict(
    key="change to your api key",
    pp_threshold=0.13,  # The amount of pp gain required to post a score
    score_request_limit=100,  # The maximum number of scores to request, between 0-100
    minimum_pp_required=0,  # The minimum pp required to assign a gamemode/profile in general
    use_mentions_in_scores=True,  # Whether the bot will mention people when they set a *score*
    update_interval=30,  # The sleep time in seconds between updates
    profiles={},  # Profile setup as member_id: osu_id
    mode={},  # Member's game mode as member_id: gamemode_value
    server={},  # Server specific info for score- and map notification channels
    update_mode={},  # Member's notification update mode as member_id: UpdateModes.name
    primary_server={},  # Member's primary server; defines where they should be mentioned: member_id: server_id
))

osu_tracking = {}  # Saves the requested data or deletes whenever the user stops playing (for comparisons)
update_interval = osu_config.data.get("update_interval", 30)
time_elapsed = 0  # The registered time it takes to process all information between updates (changes each update)
logging_interval = 30  # The time it takes before posting logging information to the console. TODO: setup logging
rank_regex = re.compile(r"#\d+")

pp_threshold = osu_config.data.get("pp_threshold", 0.13)
score_request_limit = osu_config.data.get("score_request_limit", 100)
minimum_pp_required = osu_config.data.get("minimum_pp_required", 0)
use_mentions_in_scores = osu_config.data.get("use_mentions_in_scores", True)
max_diff_length = 32  # The maximum amount of characters in a beatmap difficulty

api.set_api_key(osu_config.data.get("key"))
host = "https://osu.ppy.sh/"

gamemodes = ", ".join(gm.name for gm in api.GameMode)


class UpdateModes(Enum):
    """ Enums for the various notification update modes.
    Values are valid names in a tuple. """
    Full = ("full", "on", "enabled", "f", "e")
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


def calculate_acc(mode: api.GameMode, score: dict):
    """ Calculate the accuracy using formulas from https://osu.ppy.sh/wiki/Accuracy """
    # Parse data from the score: 50s, 100s, 300s, misses, katu and geki
    keys = ("count300", "count100", "count50", "countmiss", "countkatu", "countgeki")
    c300, c100, c50, miss, katu, geki = map(int, (score[key] for key in keys))

    # Catch accuracy is done a tad bit differently, so we calculate that by itself
    if mode is api.GameMode.Catch:
        total_numbers_of_fruits_caught = c50 + c100 + c300
        total_numbers_of_fruits = miss + c50 + c100 + c300 + katu
        return total_numbers_of_fruits_caught / total_numbers_of_fruits

    total_points_of_hits, total_number_of_hits = 0, 0

    if mode is api.GameMode.Standard:
        total_points_of_hits = c50 * 50 + c100 * 100 + c300 * 300
        total_number_of_hits = miss + c50 + c100 + c300
    elif mode is api.GameMode.Taiko:
        total_points_of_hits = (miss * 0 + c100 * 0.5 + c300 * 1) * 300
        total_number_of_hits = miss + c100 + c300
    elif mode is api.GameMode.Mania:
        # In mania, katu is 200s and geki is MAX
        total_points_of_hits = c50 * 50 + c100 * 100 + katu * 200 + (c300 + geki) * 300
        total_number_of_hits = miss + c50 + c100 + katu + c300 + geki

    return total_points_of_hits / (total_number_of_hits * 300)


def format_user_diff(mode: api.GameMode, pp: float, rank: int, country_rank: int, accuracy: float, iso: str, data: dict):
    """ Get a bunch of differences and return a formatted string to send.
    iso is the country code. """
    formatted = "\u2139`{} {:.2f}pp {:+.2f}pp`".format(mode.name.replace("Standard", "osu!"), float(data["pp_raw"]), pp)
    formatted += (" \U0001f30d`#{:,}{}`".format(int(data["pp_rank"]),
                                                "" if int(rank) == 0 else " {:+}".format(int(rank))))
    formatted += (" {}`#{:,}{}`".format(utils.text_to_emoji(iso), int(data["pp_country_rank"]),
                                        "" if int(country_rank) == 0 else " {:+}".format(int(country_rank))))
    rounded_acc = round(accuracy, 3)
    if rounded_acc > 0:
        formatted += " \U0001f4c8"  # Graph with upwards trend
    elif rounded_acc < 0:
        formatted += " \U0001f4c9"  # Graph with downwards trend
    else:
        formatted += " \U0001f3af"  # Dart

    formatted += "`{:.3f}%".format(float(data["accuracy"]))
    if not rounded_acc == 0:
        formatted += " {:+}%`".format(rounded_acc)
    else:
        formatted += "`"

    return formatted


async def format_stream(member: discord.Member, score: dict, beatmap: dict):
    """ Format the stream url and a VOD button when possible. """
    stream_url = getattr(member.game, "url", None)
    if not stream_url:
        return ""

    # Add the stream url and return immediately if twitch is not setup
    text = "**Watch live @** <{}>".format(stream_url)
    if not twitch.client_id:
        return text + "\n"

    # Try getting the vod information of the current stream
    try:
        twitch_id = await twitch.get_id(member)
        vod_request = await twitch.request("channels/{}/videos".format(twitch_id), limit=1, broadcast_type="archive", sort="time")
        assert vod_request["_total"] >= 1
    except:
        print_exc()
        return text + "\n"

    vod = vod_request["videos"][0]

    # Find the timestamp of where the play would have started without pausing the game
    score_created = datetime.strptime(score["date"], "%Y-%m-%d %H:%M:%S")
    vod_created = datetime.strptime(vod["created_at"], "%Y-%m-%dT%H:%M:%SZ") + timedelta(hours=8)  # UTC-8
    beatmap_length = int(beatmap["total_length"])

    # Convert beatmap length when speed mods are enabled
    mods = Mods.list_mods(int(score["enabled_mods"]))
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


async def format_new_score(mode: api.GameMode, score: dict, beatmap: dict, rank: int, member: discord.Member):
    """ Format any score. There should be a member name/mention in front of this string. """
    acc = calculate_acc(mode, score)
    return (
        "[{i}{artist} - {title} [{version}]{i}]({host}b/{beatmap_id})\n"
        "**{pp}pp {stars:.2f}\u2605, {rank} {scoreboard_rank}+{mods}**"
        "```diff\n"
        "  acc     300s   100s   50s    miss   combo\n"
        "{sign} {acc:<8.2%}{count300:<7}{count100:<7}{count50:<7}{countmiss:<7}{maxcombo}{max_combo}```"
        "{live}"
    ).format(
        host=host,
        sign="!" if acc == 1 else ("+" if score["perfect"] == "1" else "-"),
        mods=Mods.format_mods(int(score["enabled_mods"])),
        acc=acc,
        artist=beatmap["artist"].replace("_", "\_"),
        title=beatmap["title"].replace("_", "\_"),
        i="*" if "*" not in beatmap["artist"] + beatmap["title"] else "",  # Escaping asterisk doesn't work in italics
        version=beatmap["version"],
        stars=float(beatmap["difficultyrating"]),
        max_combo="/{}".format(beatmap["max_combo"]) if mode in (api.GameMode.Standard, api.GameMode.Catch) else "",
        scoreboard_rank="#{} ".format(rank) if rank else "",
        live=await format_stream(member, score, beatmap),
        **score
    )


async def format_minimal_score(mode: api.GameMode, score: dict, beatmap: dict, rank: int, member: discord.Member):
    """ Format any osu! score with minimal content.
    There should be a member name/mention in front of this string. """
    acc = calculate_acc(mode, score)
    return (
        "[*{artist} - {title} [{version}]*]({host}b/{beatmap_id})\n"
        "**{pp}pp {stars:.2f}\u2605, {rank} {acc:.2%} {scoreboard_rank}+{mods}**"
        "{live}"
    ).format(
        host=host,
        mods=Mods.format_mods(int(score["enabled_mods"])),
        acc=acc,
        artist=beatmap["artist"].replace("*", "\*").replace("_", "\_"),
        title=beatmap["title"].replace("*", "\*").replace("_", "\_"),
        version=beatmap["version"],
        stars=float(beatmap["difficultyrating"]),
        scoreboard_rank="#{} ".format(rank) if rank else "",
        live=await format_stream(member, score, beatmap),
        **score
    )


def updates_per_log():
    """ Returns the amount of updates needed before logging interval is met. """
    return logging_interval // (update_interval / 60)


def get_primary_server(member_id: str):
    """ Return the primary server for a member or None. """
    return osu_config.data["primary_server"].get(member_id, None)


def get_mode(member_id: str):
    """ Return the api.GameMode for the member with this id. """
    if member_id not in osu_config.data["mode"]:
        return api.GameMode.Standard

    value = int(osu_config.data["mode"][member_id])
    return api.GameMode(value)


def get_update_mode(member_id: str):
    """ Return the member's update mode. """
    if member_id not in osu_config.data["update_mode"]:
        return UpdateModes.Full

    return UpdateModes.get_mode(osu_config.data["update_mode"][member_id])


def get_user_url(member_id: str):
    """ Return the user website URL. """
    user_id = osu_config.data["profiles"][member_id]

    if api.ripple_pattern.match(user_id):
        return "https://ripple.moe/u/" + user_id[7:]
    else:
        return host + "u/" + user_id


def check_playing(member: discord.Member, member_id: str):
    """ Check if a member has "osu!" in their Game name. """
    # The member doesn't even match
    if not member.id == member_id:
        return False

    # The member has disabled these features
    if get_update_mode(member_id) is UpdateModes.Disabled:
        return False

    # See if the member is playing
    if getattr(member.game, "name", None) and ("osu" in member.game.name.lower() or rank_regex.search(member.game.name)):
        return True

    return False


async def update_user_data():
    """ Go through all registered members playing osu!, and update their data. """
    global osu_tracking

    # Go through each member playing and give them an "old" and a "new" subsection
    # for their previous and latest user data
    for member_id, profile in osu_config.data["profiles"].items():
        member = discord.utils.find(lambda m: check_playing(m, member_id), client.get_all_members())

        # If the member is not playing anymore, remove them from the tracking data
        if not member:
            if member_id in osu_tracking:
                del osu_tracking[member_id]

            continue

        mode = get_mode(member_id).value
        try:
            user_data = await api.get_user(u=profile, type="id", m=mode)
        except ServerDisconnectedError:
            continue
        except asyncio.TimeoutError:
            logging.warning("Timed out when retrieving osu! info from {} ({})".format(member, profile))
            continue

        # Sleep after using get_user as to not put too much strain on the API at once
        await asyncio.sleep(.2)

        # Just in case something goes wrong, we skip this member (these things are usually one-time occurrences)
        if user_data is None:
            logging.info("Could not retrieve osu! info from {} ({})".format(member, profile))
            continue

        # User is already tracked
        if member_id in osu_tracking:
            # Move the "new" data into the "old" data of this user
            osu_tracking[member_id]["old"] = osu_tracking[member_id]["new"]
        else:
            # If this is the first time, update the user's list of scores for later
            user_scores = await api.get_user_best(u=profile, type="id", limit=score_request_limit, m=mode)
            osu_tracking[member_id] = dict(member=member, scores=user_scores)

        # Update the "new" data
        osu_tracking[member_id]["new"] = user_data
        osu_tracking[member_id]["new"]["ripple"] = True if api.ripple_pattern.match(profile) else False


async def get_new_score(member_id: str):
    """ Compare old user scores with new user scores and return the discovered
    new score if there is any. When a score is returned, it's position in the
    player's top plays can be retrieved with score["pos"]. """
    # Download a list of the user's scores
    profile = osu_config.data["profiles"][member_id]
    user_scores = await api.get_user_best(u=profile, type="id", limit=score_request_limit, m=get_mode(member_id).value,
                                          request_tries=3)

    # Compare the scores from top to bottom and try to find a new one
    for i, score in enumerate(user_scores):
        if score not in osu_tracking[member_id]["scores"]:
            osu_tracking[member_id]["scores"] = user_scores

            # Calculate the difference in pp from the score below
            if i < len(osu_tracking[member_id]["scores"]) - 2:
                pp = float(score["pp"])
                diff = pp - float(user_scores[i + 1]["pp"])
            else:
                diff = 0

            return dict(score, pos=i + 1, diff=diff)
    else:
        return None


def get_diff(old, new, value):
    """ Get the difference between old and new osu! user data. """
    return float(new[value]) - float(old[value])


def get_notify_channels(server: discord.Server, data_type: str):
    """ Find the notifying channel or return the server. """
    if server.id not in osu_config.data["server"]:
        return None

    if data_type + "-channels" not in osu_config.data["server"][server.id]:
        return None

    return [server.get_channel(s) for s in osu_config.data["server"][server.id][data_type + "-channels"]
            if server.get_channel(s)]


async def notify_pp(member_id: str, data: dict):
    """ Notify any differences in pp and post the scores + rank/pp gained. """
    # Only update pp when there is actually a difference
    if "old" not in data:
        return

    # Get the difference in pp since the old data
    old, new = data["old"], data["new"]
    pp_diff = get_diff(old, new, "pp_raw")

    # If the difference is too small or nothing, move on
    if pp_threshold > pp_diff > -pp_threshold:
        return

    rank_diff = -int(get_diff(old, new, "pp_rank"))
    country_rank_diff = -int(get_diff(old, new, "pp_country_rank"))
    accuracy_diff = get_diff(old, new, "accuracy")  # Percent points difference

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
        beatmap = (await api.get_beatmaps(b=int(score["beatmap_id"]), m=mode.value, a=1, request_tries=3))[0]

        # There might not be any events
        scoreboard_rank = None
        if new["events"]:
            scoreboard_rank = api.rank_from_events(new["events"], score["beatmap_id"])

        # Find the potentially gained pp in standard when not FC
        if mode is api.GameMode.Standard and update_mode is not UpdateModes.PP and int(score["maxcombo"]) < int(beatmap["max_combo"]):
            options = [score["count100"] + "x100", score["count50"] + "x50",
                       "+" + Mods.format_mods(int(score["enabled_mods"]))]
            try:
                pp_stats = await calculate_pp("https://osu.ppy.sh/b/{}".format(score["beatmap_id"]), *options)
                potential_pp = pp_stats.pp
            except:
                pass

            # Drop this info whenever the potential pp gain is negative.
            #     The osu! API does not provide info on sliderbreak count and missed sliderend count, which results
            #     in faulty calculation (very often negative relatively). Therefore, I will conclude that the score
            #     was actually an FC and has missed sliderends when the gain is negative.
            if potential_pp - float(score["pp"]) <= 0:
                potential_pp = None

        if update_mode is UpdateModes.Minimal:
            m += await format_minimal_score(mode, score, beatmap, scoreboard_rank, member) + "\n"
        else:
            m += await format_new_score(mode, score, beatmap, scoreboard_rank, member)

    # Always add the difference in pp along with the ranks
    m += format_user_diff(mode, pp_diff, rank_diff, country_rank_diff, accuracy_diff, old["country"], new)

    # Send the message to all servers
    for server in client.servers:
        member = server.get_member(member_id)
        channels = get_notify_channels(server, "score")
        if not member or not channels:
            continue

        primary_server = get_primary_server(member.id)
        is_primary = True if primary_server is None else (True if primary_server == server.id else False)

        # Format the url and the username
        user_url = get_user_url(member.id)
        name = "{member.mention} [`{ripple}{name}`]({url})".format(member=member, name=new["username"], url=user_url,
                                                                   ripple="ripple: " if new["ripple"] else "")

        embed = discord.Embed(color=member.color, url=user_url)
        embed.description = m

        # The top line of the format will differ depending on whether we found a score or not
        if score:
            embed.description = "**{0} set a new best `(#{pos}/{1} +{diff:.2f}pp)` on**\n".format(name, score_request_limit, **score) + m
        else:
            embed.description = name + "\n" + m

        # Add potential pp in the footer
        if potential_pp:
            embed.set_footer(text="Potential: {0:,.2f}pp, {1:+.2f}pp".format(potential_pp, potential_pp - float(score["pp"])))

        for i, channel in enumerate(channels):
            try:
                await client.send_message(channel, embed=embed)

                # In the primary server and if the user sets a score, send a mention and delete it
                # This will only mention in the first channel of the server
                if use_mentions_in_scores and score and i == 0 and is_primary:
                    mention = await client.send_message(channel, member.mention)
                    await client.delete_message(mention)
            except discord.Forbidden:
                pass


def format_beatmapset_diffs(beatmapset: dict):
    """ Format some difficulty info on a beatmapset. """
    # Get the longest difficulty name
    diff_length = len(max((diff["version"] for diff in beatmapset), key=len))
    if diff_length > max_diff_length:
        diff_length = max_diff_length
    elif diff_length < len("version"):
        diff_length = len("version")

    m = "```elm\n" \
        "M {version: <{diff_len}}  |  stars   drain".format(
        version="version", diff_len=diff_length)

    for diff in sorted(beatmapset, key=lambda d: float(d["difficultyrating"])):
        diff_name = diff["version"]
        m += "\n{gamemode: <2}{name: <{diff_len}}  |  " \
             "{stars: <8}{drain}".format(
            gamemode=api.GameMode(int(diff["mode"])).name[0],
            name=diff_name if len(diff_name) < max_diff_length else diff_name[:29] + "...",
            diff_len=diff_length,
            stars="{:.2f}\u2605".format(float(diff["difficultyrating"])),
            drain="{}:{:02}".format(*divmod(int(diff["hit_length"]), 60))
        )

    return m + "```"


def format_map_status(member: discord.Member, status_format: str, beatmapset: dict, minimal: bool):
    """ Format the status update of a beatmap. """
    set_id = beatmapset[0]["beatmapset_id"]
    user_id = osu_config.data["profiles"][member.id]

    status = status_format.format(name=member.display_name, user_id=user_id, host=host, **beatmapset[0])
    if not minimal:
        status += format_beatmapset_diffs(beatmapset)

    embed = discord.Embed(color=member.color, description=status)
    embed.set_thumbnail(url="https://b.ppy.sh/thumb/{}.jpg?date={}".format(set_id, datetime.now().ctime().replace(" ", "%20")))
    return embed


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
        html = event["display_html"]

        # Get and format the type of event
        if "submitted" in html:
            status_format = "\U0001F310 <name> has submitted a new beatmap <title>"
        elif "updated" in html:
            status_format = "\U0001F53C <name> has updated the beatmap <title>"
        elif "revived" in html:
            status_format = "\U0001F64F <title> has been revived from eternal slumber by <name>"
        elif "qualified" in html:
            status_format = "\U0001F497 <title> by <name> has just been qualified!"
        else:  # We discard any other events
            continue

        # Replace shortcuts with proper formats and add url formats
        if status_format:
            status_format = status_format.replace("<name>", "[**{name}**]({host}u/{user_id})")
            status_format = status_format.replace("<title>", "[**{artist} - {title}**]({host}s/{beatmapset_id})")

        # We'll sleep a little bit to let the beatmap API catch up with the change
        await asyncio.sleep(10)

        # Try returning the beatmap info 3 times with a span of 20 seconds.
        # This might be needed when new maps are submitted.
        for _ in range(3):
            beatmapset = await api.get_beatmaps(s=event["beatmapset_id"])
            if beatmapset:
                break
            await asyncio.sleep(20)
        else:
            # Oh well, false positive?
            continue

        # Send the message to all servers
        for server in client.servers:
            member = server.get_member(member_id)
            channels = get_notify_channels(server, "map")  # type: list

            if not member or not channels:
                continue

            for channel in channels:
                # Do not format difficulties when minimal (or pp) information is specified
                update_mode = get_update_mode(member_id)
                embed = format_map_status(member, status_format, beatmapset, update_mode is not UpdateModes.Full)

                try:
                    await client.send_message(channel, embed=embed)
                except discord.errors.Forbidden:
                    pass


async def on_ready():
    """ Handle every event. """
    global time_elapsed

    # Notify the owner when they have not set their API key
    if osu_config.data["key"] == "change to your api key":
        logging.warning("osu! functionality is unavailable until an API key is provided (config/osu.json)")

    while not client.loop.is_closed():
        try:
            await asyncio.sleep(update_interval, loop=client.loop)
            started = datetime.now()

            # First, update every user's data
            await update_user_data()

            # Next, check for any differences in pp between the "old" and the "new" subsections
            # and notify any servers
            # NOTE: This used to also be ensure_future before adding the potential pp check.
            # The reason for this change is to ensure downloading and running the .osu files won't happen twice
            # at the same time, which would cause problems retrieving the correct potential pp.
            for member_id, data in osu_tracking.items():
                await notify_pp(member_id, data)

            # Check for any differences in the users' events and post about map updates
            for member_id, data in osu_tracking.items():
                asyncio.ensure_future(notify_maps(member_id, data))
        # We don't want to stop updating scores even if something breaks
        except:
            print_exc()
        finally:
            pass
            # TODO: setup logging

            # Save the time elapsed since we started the update
            time_elapsed = (datetime.now() - started).total_seconds()


async def on_reload(name: str):
    """ Preserve the tracking cache. """
    global osu_tracking
    local_tracking = osu_tracking

    await plugins.reload(name)

    osu_tracking = local_tracking


@plugins.command(aliases="circlesimulator eba")
async def osu(message: discord.Message, member: discord.Member=Annotate.Self,
              mode: api.GameMode.get_mode=None):
    """ Handle osu! commands.

    When your user is linked, this plugin will check if you are playing osu!
    (your profile would have `playing osu!`), and send updates whenever you set a
    new top score. """
    # Make sure the member is assigned
    assert member.id in osu_config.data["profiles"], "No osu! profile assigned to **{}**!".format(member.name)

    user_id = osu_config.data["profiles"][member.id]
    mode = get_mode(member.id) if mode is None else mode

    # Set the signature color to that of the role color
    color = "pink" if member.color == discord.Color.default() \
        else "#{0:02x}{1:02x}{2:02x}".format(*member.color.to_tuple())

    # Calculate whether the header color should be black or white depending on the background color.
    # Stupidly, the API doesn't accept True/False. It only looks for the &darkheaders keyword.
    # The silly trick done here is extracting either the darkheader param or nothing.
    r, g, b = member.color.to_tuple()
    dark = dict(darkheader=True) if (r * 0.299 + g * 0.587 + b * 0.144) > 186 else {}

    # Download and upload the signature
    signature = await utils.retrieve_page("http://lemmmy.pw/osusig/sig.php", head=True, colour=color,
                                          uname=user_id, pp=True, countryrank=True, xpbar=True,
                                          mode=mode.value, date=datetime.now().ctime(), **dark)
    embed = discord.Embed(color=member.color, url=get_user_url(member.id))
    embed.set_author(name=member.display_name, icon_url=member.avatar_url)
    embed.set_image(url=signature.url)
    await client.send_message(message.channel, embed=embed)


async def has_enough_pp(**params):
    """ Lookup the given member and check if they have enough pp to register.
    params are just like api.get_user. """
    osu_user = await api.get_user(**params)
    return float(osu_user["pp_raw"]) >= minimum_pp_required


@osu.command(aliases="set")
async def link(message: discord.Message, name: Annotate.LowerContent):
    """ Tell the bot who you are on osu!.

    If you're using ripple, type ripple:<name>. """
    mode = api.GameMode.Standard
    osu_user = await api.get_user(u=name)

    # Check if the osu! user exists
    assert osu_user, "osu! user `{}` does not exist.".format(name)
    user_id = osu_user["user_id"]

    # Make sure the user has more pp than the minimum limit defined in config
    if float(osu_user["pp_raw"]) < minimum_pp_required:
        # Perhaps the user wants to display another gamemode
        await client.say(message, "**You have less than the required {}pp.\nIf you're not an osu!standard player, please "
                                  "enter your gamemode below. Valid gamemodes are `{}`.**".format(minimum_pp_required, gamemodes))
        reply = await client.wait_for_message(timeout=60, author=message.author, channel=message.channel)
        if not reply:
            return

        mode = api.GameMode.get_mode(reply.content)
        assert mode is not None, "**The given gamemode is invalid.**"
        assert await has_enough_pp(u=user_id, m=mode.value, type="id"), \
            "**Your pp in {} is less than the required {}pp.**".format(mode.name, minimum_pp_required)

    # Clear the scores when changing user
    if message.author.id in osu_tracking:
        del osu_tracking[message.author.id]

    # Convert their user_id to a ripple id
    user_id = osu_user["user_id"]
    if api.ripple_pattern.match(name):
        user_id = "ripple:" + user_id

    # Assign the user using their unique user_id
    osu_config.data["profiles"][message.author.id] = user_id
    osu_config.data["mode"][message.author.id] = mode.value
    osu_config.data["primary_server"][message.author.id] = message.server.id
    osu_config.save()
    await client.say(message, "Set your osu! profile to `{}`.".format(osu_user["username"]))


@osu.command(aliases="unset")
async def unlink(message: discord.Message, member: discord.Member=Annotate.Self):
    """ Unlink your osu! account or unlink the member specified (**Owner only**). """
    # The message author is allowed to unlink himself
    # If a member is specified and the member is not the owner, set member to the author
    if not plugins.is_owner(message.author):
        member = message.author

    # The member might not be linked to any profile
    assert member.id in osu_config.data["profiles"], "No osu! profile assigned to **{}**!".format(member.name)

    # Unlink the given member (usually the message author)
    del osu_config.data["profiles"][member.id]
    osu_config.save()
    await client.say(message, "Unlinked **{}'s** osu! profile.".format(member.name))


@osu.command(aliases="mode m track", error="Valid gamemodes: `{}`".format(gamemodes), doc_args=dict(modes=gamemodes))
async def gamemode(message: discord.Message, mode: api.GameMode.get_mode):
    """ Sets the command executor's gamemode.

    Gamemodes are: `{modes}`. """
    assert message.author.id in osu_config.data["profiles"], \
        "No osu! profile assigned to **{}**!".format(message.author.name)

    user_id = osu_config.data["profiles"][message.author.id]
    assert await has_enough_pp(u=user_id, m=mode.value, type="id"), \
        "**Your pp in {} is less than the required {}pp.**".format(mode.name, minimum_pp_required)

    osu_config.data["mode"][message.author.id] = mode.value
    osu_config.save()

    # Clear the scores when changing mode
    if message.author.id in osu_tracking:
        del osu_tracking[message.author.id]

    await client.say(message, "Set your gamemode to **{}**.".format(mode.name))


@osu.command()
async def info(message: discord.Message, member: discord.Member=Annotate.Self):
    """ Display configuration info. """
    # Make sure the member is assigned
    assert member.id in osu_config.data["profiles"], "No osu! profile assigned to **{}**!".format(member.name)

    user_id = osu_config.data["profiles"][member.id]
    mode = get_mode(member.id)
    update_mode = get_update_mode(member.id)

    e = discord.Embed(color=member.color)
    e.set_author(name=member.display_name, icon_url=member.avatar_url, url=host + "u/" + user_id)
    e.add_field(name="Game Mode", value=mode.name)
    e.add_field(name="Notification Mode", value=update_mode.name)
    e.add_field(name="Playing osu!", value="YES" if member.id in osu_tracking.keys() else "NO")

    await client.send_message(message.channel, embed=e)


doc_modes = ", ".join(m.name.lower() for m in UpdateModes)


@osu.command(aliases="n updatemode", error="Valid modes: `{}`".format(doc_modes), doc_args=dict(modes=doc_modes))
async def notify(message: discord.Message, mode: UpdateModes.get_mode):
    """ Sets the command executor's update notification mode. This changes
    how much text is in each update, or if you want to disable them completely.

    Update modes are: `{modes}`. """
    assert message.author.id in osu_config.data["profiles"], \
        "No osu! profile assigned to **{}**!".format(message.author.name)

    osu_config.data["update_mode"][message.author.id] = mode.name
    osu_config.save()

    # Clear the scores when disabling mode
    if message.author.id in osu_tracking and mode == UpdateModes.Disabled:
        del osu_tracking[message.author.id]

    await client.say(message, "Set your update notification mode to **{}**.".format(mode.name.lower()))


@osu.command()
async def url(message: discord.Message, member: discord.Member=Annotate.Self,
              section: str.lower=None):
    """ Display the member's osu! profile URL. """
    # Member might not be registered
    assert member.id in osu_config.data["profiles"], "No osu! profile assigned to **{}**!".format(member.name)

    # Send the URL since the member is registered
    await client.say(message, "**{0.display_name}'s profile:** <{1}{2}>".format(
        member, get_user_url(member.id), "#_{}".format(section) if section else ""))


async def pp_(message: discord.Message, beatmap_url: str, *options):
    """ Calculate and return the would be pp using `pyoppai`.

    The beatmap url should either be a link to a beatmap /b/ or /s/, or an
    uploaded .osu file.

    Options are a parsed set of command-line arguments:  /
    `([acc]% | [num_100s]x100 [num_50s]x50) +[mods] [combo]x [misses]m scorev[scoring_version] ar[ar] od[od] cs[cs]`

    **Additionally**, PCBOT includes a *find closest pp* feature. This works as an
    argument in the options, formatted like `[pp_value]pp`
    """
    try:
        pp_stats = await calculate_pp(beatmap_url, *options)
    except ValueError as e:
        await client.say(message, e)
        return

    options = list(options)
    if type(pp_stats) is ClosestPPStats:
        # Remove any accuracy percentage from options as we're setting this manually, and remove unused options
        for opt in options:
            if opt.endswith("%") or opt.endswith("pp") or opt.endswith("x300") or opt.endswith("x100") or opt.endswith("x50"):
                options.remove(opt)

        options.insert(0, "{}%".format(pp_stats.acc))

    await client.say(message, "*{artist} - {title}* **[{version}] {0}** {stars:.02f}\u2605 would be worth `{pp:,.02f}pp`.".format(
        " ".join(options), **pp_stats._asdict()))


if pyoppai is not None:
    plugins.command(name="pp", aliases="oppai")(pp_)
    osu.command(name="pp", aliases="oppai")(pp_)


@osu.command(aliases="map")
async def mapinfo(message: discord.Message, beatmap_url: str):
    """ Display simple beatmap information. """
    try:
        beatmapset = await api.beatmapset_from_url(beatmap_url)
    except Exception as e:
        await client.say(message, e)
        return

    header = "**{artist} - {title}** submitted by **{creator}**".format(**beatmapset[0])
    await client.say(message, header + format_beatmapset_diffs(beatmapset))


def init_server_config(server: discord.Server):
    """ Initializes the config when it's not already set. """
    if server.id not in osu_config.data["server"]:
        osu_config.data["server"][server.id] = {}
        osu_config.save()


@osu.command(aliases="configure cfg")
async def config(message, _: utils.placeholder):
    """ Manage configuration for this plugin. """
    pass


@config.command(alias="score", permissions="manage_server")
async def scores(message: discord.Message, *channels: discord.Channel):
    """ Set which channels to post scores to. """
    init_server_config(message.server)
    osu_config.data["server"][message.server.id]["score-channels"] = list(c.id for c in channels)
    osu_config.save()
    await client.say(message, "**Notifying scores in**: {}".format(
        utils.format_objects(*channels, sep=" ") or "no channels"))


@config.command(alias="map", permissions="manage_server")
async def maps(message: discord.Message, *channels: discord.Channel):
    """ Set which channels to post map updates to. """
    init_server_config(message.server)
    osu_config.data["server"][message.server.id]["map-channels"] = list(c.id for c in channels)
    osu_config.save()
    await client.say(message, "**Notifying map updates in**: {}".format(
        utils.format_objects(*channels, sep=" ") or "no channels"))


@osu.command(owner=True)
async def debug(message: discord.Message):
    """ Display some debug info. """
    await client.say(message, "Sent `{}` requests since the bot started (`{}`).\n"
                              "Spent `{:.3f}` seconds last update.\n"
                              "Members registered for update: {}".format(
        api.requests_sent, client.time_started.ctime(),
        time_elapsed,
        utils.format_objects(*[d["member"] for d in osu_tracking.values()], dec="`")
    ))
