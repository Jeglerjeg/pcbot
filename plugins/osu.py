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
import traceback
from datetime import datetime, timezone
from textwrap import wrap
from operator import itemgetter
import aiohttp
import discord


import bot
import plugins
from pcbot import utils, Annotate
from plugins.osulib import api, pp, ordr, enums
from plugins.osulib.tracking import osu_tracking, osu_profile_cache, update_user_data, notify_pp, notify_recent_events
from plugins.osulib.constants import update_interval, cache_user_profiles, minimum_pp_required, host
from plugins.osulib.formatting import beatmap_format, embed_format, misc_format, score_format
from plugins.osulib.utils import misc_utils, beatmap_utils, score_utils, user_utils
from plugins.osulib.config import osu_config

client = plugins.client  # type: bot.Client

last_rendered = {}  # Saves when the member last rendered a replay
time_elapsed = 0  # The registered time it takes to process all information between updates (changes each update)
previous_update = None  # The time osu user data was last updated. None until first update has run


async def on_ready():
    """ Handle every event. """
    global time_elapsed, previous_update
    api_available = False

    await client.wait_until_ready()
    await ordr.establish_ws_connection()

    # Notify the owner when they have not set their API key
    if osu_config.data["client_secret"] == "change to your client secret" or \
            osu_config.data["client_id"] == "change to your client ID":
        logging.warning("osu! functionality is unavailable until a "
                        "client ID and client secret is provided (config/osu.json)")
    else:
        await api.get_access_token(osu_config.data.get("client_id"), osu_config.data.get("client_secret"))
        client.loop.create_task(api.refresh_access_token(osu_config.data.get("client_id"),
                                                         osu_config.data.get("client_secret")))
        api_available = True

    while not client.loop.is_closed() and api_available:
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
    global time_elapsed, previous_update, last_rendered
    local_renders = last_rendered
    local_requests = api.requests_sent
    local_update_time_elapsed = time_elapsed
    local_update_time = previous_update

    importlib.reload(plugins.osulib.api)
    importlib.reload(plugins.osulib.args)
    importlib.reload(plugins.osulib.pp)
    await plugins.reload(name)

    api.requests_sent = local_requests
    last_rendered = local_renders
    time_elapsed = local_update_time_elapsed
    previous_update = local_update_time


@plugins.event()
async def on_message(message: discord.Message):
    """ Automatically post editor timestamps with URL. """
    # Ignore commands
    if message.content.startswith("!"):
        return

    timestamps = [f"{stamp} {editor_url}" for stamp, editor_url in misc_utils.get_timestamps_with_url(message.content)]
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
        member = user_utils.get_user(message, value, osu_tracking)
        if member:
            continue

        mode = enums.GameMode.get_mode(value)

    if member is None:
        member = message.author

    # Make sure the member is assigned
    assert str(member.id) in osu_config.data["profiles"], user_utils.get_missing_user_string(member)

    user_id = osu_config.data["profiles"][str(member.id)]
    mode = user_utils.get_mode(str(member.id)) if mode is None else mode

    member_rgb = member.color.to_rgb()
    # Set the signature color to that of the role color
    color = "pink" if member.color == discord.Color.default() \
        else f"#{member_rgb[0]:02x}{member_rgb[1]:02x}{member_rgb[2]:02x}"

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
    embed.set_author(name=member.display_name, icon_url=member.display_avatar.url,
                     url=user_utils.get_user_url(str(member.id)))
    embed.set_image(url=signature.url)
    await client.send_message(message.channel, embed=embed)


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
    mode = enums.GameMode.get_mode(osu_user["playmode"])

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

        mode = enums.GameMode.get_mode(reply.content)
        assert mode is not None, "**The given gamemode is invalid.**"
        assert await user_utils.has_enough_pp(user=user_id, mode=mode.name), \
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
    """ Wipe all tracked members or just the specified member, as well as the map cache in osu.json. """
    osu_config.data["map_cache"] = {}
    await osu_config.asyncsave()
    if member:
        if str(member.id) in osu_tracking:
            osu_tracking[str(member.id)]["schedule_wipe"] = True
            await client.say(message, f"Scheduled wipe from tracking for {member.name} during the next update.")
        else:
            await client.say(message, "User not in tracking.")
    else:
        tracking_length = len(osu_tracking)
        for entry in list(osu_tracking):
            osu_tracking[entry]["schedule_wipe"] = True
        await client.say(message, f"Scheduled {tracking_length} entries for wiping during the next update.")


@osu.command(aliases="unset")
async def unlink(message: discord.Message, member: discord.Member = Annotate.Self):
    """ Unlink your osu! account or unlink the member specified (**Owner only**). """
    # The message author is allowed to unlink himself
    # If a member is specified and the member is not the owner, set member to the author
    if not plugins.is_owner(message.author):
        member = message.author

    # The member might not be linked to any profile
    assert str(member.id) in osu_config.data["profiles"], user_utils.get_missing_user_string(member)

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


gamemodes = ', '.join(misc_format.format_mode_name(gm) for gm in enums.GameMode)


@osu.command(aliases="mode m track", error=f"Valid gamemodes: `{gamemodes}`", doc_args=dict(modes=gamemodes))
async def gamemode(message: discord.Message, mode: enums.GameMode.get_mode):
    """ Sets the command executor's gamemode.

    Gamemodes are: `{modes}`. """
    assert str(message.author.id) in osu_config.data["profiles"], user_utils.get_missing_user_string(message.author)

    user_id = osu_config.data["profiles"][str(message.author.id)]

    mode_name = misc_format.format_mode_name(mode)

    assert await user_utils.has_enough_pp(user=user_id, mode=mode.name), \
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


@osu.command()
async def info(message: discord.Message, member: discord.Member = Annotate.Self):
    """ Display configuration info. """
    # Make sure the member is assigned
    assert str(member.id) in osu_config.data["profiles"], user_utils.get_missing_user_string(member)

    user_id = osu_config.data["profiles"][str(member.id)]
    mode = user_utils.get_mode(str(member.id))
    update_mode = user_utils.get_update_mode(str(member.id))
    if str(member.id) in osu_tracking and "new" in osu_tracking[str(member.id)]:
        timestamp = datetime.fromisoformat(osu_tracking[str(member.id)]["new"]["time_updated"])
    else:
        timestamp = None
    if timestamp:
        e = discord.Embed(color=member.color, timestamp=timestamp)
        e.set_footer(text="User data last updated:\n")
    else:
        e = discord.Embed(color=member.color)
    e.set_author(name=member.display_name, icon_url=member.display_avatar.url, url="".join([host, "users/",
                                                                                            user_id]))
    e.add_field(name="Game Mode", value=misc_format.format_mode_name(mode))
    e.add_field(name="Notification Mode", value=update_mode.name)
    e.add_field(name="Playing osu!", value="YES" if user_utils.is_playing(member) else "NO")
    e.add_field(name="Notifying leaderboard scores", value="YES"
                if user_utils.get_leaderboard_update_status(str(member.id)) else "NO")
    e.add_field(name="Notifying beatmap updates", value="YES"
                if user_utils.get_beatmap_update_status(str(member.id)) else "NO")

    await client.send_message(message.channel, embed=e)


doc_modes = ", ".join(m.name.lower() for m in enums.UpdateModes)


@osu.command(aliases="n updatemode", error=f"Valid modes: `{doc_modes}`", doc_args=dict(modes=doc_modes))
async def notify(message: discord.Message, mode: enums.UpdateModes.get_mode):
    """ Sets the command executor's update notification mode. This changes
    how much text is in each update, or if you want to disable them completely.

    Update modes are: `{modes}`. """
    assert str(message.author.id) in osu_config.data["profiles"], user_utils.get_missing_user_string(message.author)

    osu_config.data["update_mode"][str(message.author.id)] = mode.name
    await osu_config.asyncsave()

    # Clear the scores when disabling mode
    if str(message.author.id) in osu_tracking and mode == enums.UpdateModes.Disabled:
        del osu_tracking[str(message.author.id)]

    await client.say(message, f"Set your update notification mode to **{mode.name.lower()}**.")


@osu.command()
async def url(message: discord.Message, member: discord.Member = Annotate.Self,
              section: str.lower = None):
    """ Display the member's osu! profile URL. """
    # Member might not be registered
    assert str(member.id) in osu_config.data["profiles"], user_utils.get_missing_user_string(member)

    # Send the URL since the member is registered
    await client.say(message, f"**{member.display_name}'s profile:** "
                              f"<{user_utils.get_user_url(str(member.id))}{f'#_{section}' if section else ''}>")


async def pp_(message: discord.Message, beatmap_url: str, *options):
    """ Calculate and return the would be pp using `rosu-pp`.

    Options are a parsed set of command-line arguments:  /
    `([acc]% | [num_100s]x100 [num_50s]x50) +[mods] [combo]x [misses]m hp[hp] ar[ar] od[od] cs[cs] [clock_rate]*`

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

        pp_stats = await pp.calculate_pp(beatmap_url, *options, mode=beatmap_info.gamemode,
                                         ignore_osu_cache=not bool(beatmap["status"] == "ranked" or
                                                                   beatmap["status"] == "approved"))
    except ValueError as e:
        await client.say(message, str(e))
        return

    options = list(options)
    if isinstance(pp_stats, pp.ClosestPPStats):
        # Remove any accuracy percentage from options as we're setting this manually, and remove unused options
        for opt in options.copy():
            if opt.endswith("%") or opt.endswith("pp") or opt.endswith("x300") or opt.endswith("x100") or opt.endswith(
                    "x50"):
                options.remove(opt)

        options.insert(0, f"{pp_stats.acc}%")
    for opt in options.copy():
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


async def recent(message: discord.Message, user: str = None):
    """ Display your or another member's most recent score. """
    if not user:
        member = message.author
    else:
        member = user_utils.get_user(message, user, osu_tracking)
    if not member:
        member = message.author
    assert str(member.id) in osu_config.data["profiles"], user_utils.get_missing_user_string(member)

    user_id = osu_config.data["profiles"][str(member.id)]
    mode = user_utils.get_mode(str(member.id))

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

    embed = await embed_format.create_score_embed_with_pp(member, osu_score, beatmap, mode, osu_tracking,
                                                          twitch_link=osu_score["passed"])
    await client.send_message(message.channel, embed=embed)


plugins.command(aliases="last new r rs")(recent)
osu.command(aliases="last new r rs")(recent)


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
        await placeholder_msg.edit(content="An error occured when sending this replay. Please try again later.")
        return

    if "renderID" not in render_job:
        await placeholder_msg.edit(content="\n".join(["An error occured when sending this replay.",
                                                     ordr.get_render_error(int(render_job["errorCode"]))]))
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
            member = user_utils.get_user(message, value, osu_tracking)

    if not member:
        member = message.author

    assert str(member.id) in osu_config.data["profiles"], user_utils.get_missing_user_string(member)

    # Attempt to find beatmap URL in previous messages
    if not beatmap_url:
        beatmap_info = await beatmap_utils.find_beatmap_info(message.channel)
        # Check if URL was found
        assert beatmap_info, "No beatmap link found"
    else:
        try:
            beatmap_info = await api.beatmap_from_url(beatmap_url, return_type="info")
        except SyntaxError as e:
            await client.say(message, str(e))
            return

    user_id = osu_config.data["profiles"][str(member.id)]
    mode = user_utils.get_mode(str(member.id))
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

    embed = await embed_format.create_score_embed_with_pp(member, osu_score, beatmap, beatmap_info.gamemode
                                                          if beatmap_info.gamemode else mode, osu_tracking,
                                                          scoreboard_rank, time=bool(not mods))
    await client.send_message(message.channel, embed=embed)

plugins.command(name="score", usage="[member] <url> +<mods>")(score)
osu.command(name="score", usage="[member] <url> +<mods>")(score)


async def scores(message: discord.Message, *options):
    """ Display all of your own or the member's scores on a beatmap. Add mods to only show the score with those mods.
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
            member = user_utils.get_user(message, value, osu_tracking)
    if not member:
        member = message.author

    assert str(member.id) in osu_config.data["profiles"], user_utils.get_missing_user_string(member)
    assert str(member.id) in osu_tracking and "new" in osu_tracking[str(member.id)], \
        "This command requires user data to have been fetched. Please wait a bit and try again."

    # Attempt to find beatmap URL in previous messages
    if not beatmap_url:
        beatmap_info = await beatmap_utils.find_beatmap_info(message.channel)
        # Check if URL was found
        assert beatmap_info, "No beatmap link found"
    else:
        try:
            beatmap_info = await api.beatmap_from_url(beatmap_url, return_type="info")
        except SyntaxError as e:
            await client.say(message, str(e))
            return

    user_id = osu_config.data["profiles"][str(member.id)]
    mode = user_utils.get_mode(str(member.id))
    params = {
        "mode": beatmap_info.gamemode.name if beatmap_info.gamemode else mode.name,
    }
    fetched_osu_scores = await api.get_user_beatmap_scores(beatmap_info.beatmap_id, user_id, params=params)
    assert fetched_osu_scores["scores"], f"Found no scores by **{member.name}**."

    params = {
        "beatmap_id": beatmap_info.beatmap_id,
    }
    beatmap = (await api.beatmap_lookup(params=params, map_id=beatmap_info.beatmap_id,
                                        mode=beatmap_info.gamemode.name if beatmap_info.gamemode else mode.name))
    if mods:
        modslist = wrap(mods, 2)
        for osu_score in fetched_osu_scores["scores"]:
            if set(osu_score["mods"]) == set(modslist):
                matching_score = osu_score
                break
        else:
            await client.send_message(message.channel, content=f"Found no scores with +{mods} by **{member.name}**")
            return

        # Add a beatmap ID and user to the score so formatting will work properly.
        matching_score["beatmap"] = {}
        matching_score["beatmap"]["id"] = beatmap_info.beatmap_id
        matching_score["user"] = osu_tracking[str(member.id)]["new"]
        embed = await embed_format.create_score_embed_with_pp(member, osu_score, beatmap, beatmap_info.gamemode
                                                              if beatmap_info.gamemode else mode, osu_tracking,
                                                              time=bool(not mods))
    elif len(fetched_osu_scores["scores"]) == 1:
        osu_score = fetched_osu_scores["scores"][0]
        # Add a beatmap ID and user to the score so formatting will work properly.
        osu_score["beatmap"] = {}
        osu_score["beatmap"]["id"] = beatmap_info.beatmap_id
        osu_score["user"] = osu_tracking[str(member.id)]["new"]
        embed = await embed_format.create_score_embed_with_pp(member, osu_score, beatmap, beatmap_info.gamemode
                                                              if beatmap_info.gamemode else mode, osu_tracking,
                                                              time=bool(not mods))
    else:
        osu_score_list = fetched_osu_scores["scores"]
        sorted_scores = score_utils.get_sorted_scores(osu_score_list, "pp")
        # Add a beatmap ID and position to the scores so formatting the score list will work properly.
        for i, osu_score in enumerate(osu_score_list):
            osu_score["pos"] = i + 1
            osu_score["beatmap"] = {}
            osu_score["beatmap"]["id"] = beatmap_info.beatmap_id
        embed = embed_format.get_embed_from_template(await score_format.get_formatted_score_list(mode,
                                                                                                 sorted_scores, 5),
                                                     member.color,
                                                     osu_tracking[str(member.id)]["new"]["username"],
                                                     user_utils.get_user_url(str(member.id)),
                                                     osu_tracking[str(member.id)]["new"]["avatar_url"],
                                                     thumbnail_url=beatmap["beatmapset"]["covers"]["list@2x"])
    await client.send_message(message.channel, embed=embed)

plugins.command(name="scores", usage="[member] <url> <+mods>")(scores)
osu.command(name="scores", usage="[member] <url> <+mods>")(scores)


@osu.command(aliases="map")
async def mapinfo(message: discord.Message, beatmap_url: str, mods: str = "+Nomod"):
    """ Display simple beatmap information. """
    try:
        beatmapset = await api.beatmapset_from_url(beatmap_url)
    except Exception as e:
        await client.say(message, str(e))
        return

    await pp.calculate_pp_for_beatmapset(beatmapset, osu_config, mods=mods)
    status = "[**{artist} - {title}**]({host}beatmapsets/{id}) submitted by [**{name}**]({host}users/{user_id})"
    embed = await beatmap_format.format_map_status(status_format=status, beatmapset=beatmapset, minimal=False,
                                                   member=message.author, mods=mods)
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
            member = user_utils.get_user(message, value, osu_tracking)

    if not member:
        member = message.author
    mode = user_utils.get_mode(str(member.id))
    assert str(member.id) in osu_config.data["profiles"], user_utils.get_missing_user_string(member)
    assert str(member.id) in osu_tracking and "scores" in osu_tracking[str(member.id)], \
        "Scores have not been retrieved for this user yet. Please wait a bit and try again."
    assert mode is enums.GameMode.osu if nochoke else True, \
        "No-choke lists are only supported for osu!standard."
    assert not list_type == "score" if nochoke else True, "No-choke lists can't be sorted by score."
    if nochoke:
        async with message.channel.typing():
            osu_scores = await pp.calculate_no_choke_top_plays(copy.deepcopy(osu_tracking[str(member.id)]["scores"]),
                                                               str(member.id))
            full_osu_score_list = generate_full_no_choke_score_list(
                osu_scores["score_list"], copy.deepcopy(osu_tracking[str(member.id)]["scores"]["score_list"]))
            new_total_pp = pp.calculate_total_user_pp(full_osu_score_list, str(member.id), osu_tracking)
            author_text = "{} ({} => {}, {:+})".format(osu_tracking[str(member.id)]["new"]["username"],
                                                       utils.format_number(
                                                          osu_tracking[str(member.id)]["new"]["statistics"]["pp"], 2),
                                                       utils.format_number(new_total_pp, 2),
                                                       utils.format_number(
                                                          new_total_pp -
                                                          osu_tracking[str(member.id)]["new"]["statistics"]["pp"], 2))
    else:
        osu_scores = osu_tracking[str(member.id)]["scores"]
        author_text = osu_tracking[str(member.id)]["new"]["username"]
    sorted_scores = score_utils.get_sorted_scores(osu_scores["score_list"], list_type)
    m = await score_format.get_formatted_score_list(mode, sorted_scores, 5)
    e = embed_format.get_embed_from_template(m, member.color, author_text, user_utils.get_user_url(str(member.id)),
                                             osu_tracking[str(member.id)]["new"]["avatar_url"],
                                             osu_tracking[str(member.id)]["new"]["avatar_url"])
    await client.send_message(message.channel, embed=e)


plugins.command(name="top", usage="[member] <sort_by>", aliases="osutop")(top)
osu.command(name="top", usage="[member] <sort_by>", aliases="osutop")(top)


@osu.command()
async def tracking(message: discord.Message, _: utils.placeholder):
    """ Manage what types of osu events are tracked. """


@tracking.command(usage="<on/off>")
async def beatmap_updates(message: discord.Message, notify_setting: str):
    """ When beatmap updates are enabled, the bot will post updates to your beatmaps. """
    member = message.author
    # Make sure the member is assigned
    assert str(member.id) in osu_config.data["profiles"], user_utils.get_missing_user_string(member)

    if notify_setting.lower() == "on":
        osu_config.data["beatmap_updates"][str(member.id)] = True
        await client.say(message, "Enabled leaderboard updates.")
    elif notify_setting.lower() == "off":
        osu_config.data["beatmap_updates"][str(member.id)] = False
        await client.say(message, "Disabled leaderboard updates.")
    else:
        await client.say(message, "Invalid setting selected. Valid settings are on and off.")

    await osu_config.asyncsave()


@tracking.command(usage="<on/off>")
async def leaderboard_scores(message: discord.Message, notify_setting: str):
    """ When leaderboard updates are enabled, the bot will post your top50 scores on maps unless
    it's in your top100 PP scores. """
    member = message.author
    # Make sure the member is assigned
    assert str(member.id) in osu_config.data["profiles"], user_utils.get_missing_user_string(member)

    if notify_setting.lower() == "on":
        osu_config.data["leaderboard"][str(member.id)] = True
        await client.say(message, "Enabled leaderboard updates.")
    elif notify_setting.lower() == "off":
        osu_config.data["leaderboard"][str(member.id)] = False
        await client.say(message, "Disabled leaderboard updates.")
    else:
        await client.say(message, "Invalid setting selected. Valid settings are on and off.")

    await osu_config.asyncsave()


@osu.command(aliases="configure cfg")
async def config(message, _: utils.placeholder):
    """ Manage configuration for this plugin. """


@config.command(name="scores", alias="score", permissions="manage_guild")
async def config_scores(message: discord.Message, *channels: discord.TextChannel):
    """ Set which channels to post scores to. """
    await misc_utils.init_guild_config(message.guild)
    osu_config.data["guild"][str(message.guild.id)]["score-channels"] = list(str(c.id) for c in channels)
    await osu_config.asyncsave()
    await client.say(message, f"**Notifying scores in**: {utils.format_objects(*channels, sep=' ') or 'no channels'}")


@config.command(alias="map", permissions="manage_guild")
async def maps(message: discord.Message, *channels: discord.TextChannel):
    """ Set which channels to post map updates to. """
    await misc_utils.init_guild_config(message.guild)
    osu_config.data["guild"][str(message.guild.id)]["map-channels"] = list(c.id for c in channels)
    await osu_config.asyncsave()
    await client.say(message, f"**Notifying map updates in**: "
                              f"{utils.format_objects(*channels, sep=' ') or 'no channels'}")


@osu.command(owner=True)
async def debug(message: discord.Message):
    """ Display some debug info. """
    client_time = f"<t:{int(client.time_started.timestamp())}:F>"
    member_list = [f"`{d['member'].name}`" for d in osu_tracking.values()
                   if "member" in d and user_utils.is_playing(d["member"])]
    await client.say(message, "Sent `{}` requests since the bot started ({}).\n"
                              "Sent an average of `{}` requests per minute. \n"
                              "Spent `{:.3f}` seconds last update.\n"
                              "Last update happened at: {}\n"
                              "Members registered as playing: {}\n"
                              "Total members tracked: `{}`".format(
                               api.requests_sent, client_time,
                               utils.format_number(api.requests_sent /
                                                   ((discord.utils.utcnow() -
                                                     client.time_started).total_seconds() / 60.0), 2)
                               if api.requests_sent > 0 else 0,
                               time_elapsed,
                               f"<t:{int(previous_update.timestamp())}:F>"
                               if previous_update else "Not updated yet.",
                               ", ".join(member_list) if member_list else "None", len(osu_tracking)
                               )
                     )
