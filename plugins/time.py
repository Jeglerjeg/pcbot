""" Module for time commands and reminders and such.

    Commands:
        when
        countdown
"""

import asyncio
from operator import itemgetter

import discord
import pendulum
from pytz import all_timezones

import bot
import plugins
from pcbot import Config, Annotate

client = plugins.client  # type: bot.Client

time_cfg = Config("time", data=dict(countdown={}, timezone={}))
dt_format = "%A, %d %B %Y %H:%M:%S"


@plugins.argument()
def tz_arg(timezone: str):
    """ Get timezone from a string. """
    for tz in all_timezones:
        if tz.lower().endswith(timezone.lower()):
            return tz
    return None


def reverse_gmt(timezone: str):
    """ POSIX is stupid so these are reversed. """
    if "+" in timezone:
        timezone = timezone.replace("+", "-")
    elif "-" in timezone:
        timezone = timezone.replace("-", "+")

    return timezone


async def init_dt(message: discord.Message, time: str, timezone: str):
    """ Setup the datetime and timezone properly. """
    timezone = reverse_gmt(timezone)

    try:
        dt = pendulum.parse(time, tz=timezone, strict=False)
    except ValueError:
        await client.say(message, "Time format not recognized.")
        return None, None

    return dt, timezone


def format_when(dt: pendulum.datetime, timezone: str = "UTC"):
    """ Format when something will happen"""
    now = pendulum.now("UTC")

    diff = dt.diff(now)
    major_diff = dt.diff_for_humans(absolute=True)
    detailed_diff = diff.in_words().replace("-", "")

    return "`{time} {tz}` {pronoun} **{major}{diff}{pronoun2}**.".format(
        time=dt.strftime(dt_format),
        tz=timezone,
        pronoun="is in" if dt > now else "was",
        major="~" + major_diff + "** / **" if major_diff not in detailed_diff else "",
        diff=detailed_diff,
        pronoun2=" ago" if dt < now else ""
    )


@plugins.command(aliases="timezone")
async def when(message: discord.Message, *time, timezone: tz_arg = "UTC"):
    """ Convert time from specified timezone or UTC to formatted string of e.g.
    `2 hours from now`. """
    timezone_name = timezone

    if time:
        dt, timezone = await init_dt(message, " ".join(time), timezone)
        if dt is None or timezone is None:
            return

        await client.say(message, format_when(dt, timezone_name))
    else:
        timezone = reverse_gmt(timezone)
        dt = pendulum.now(timezone)

        await client.say(message, f'`{dt.strftime(dt_format)} {timezone_name}` is '
                                  f'**UTC{"-" if dt.offset_hours < 0 else ("+" if dt.offset_hours > 0 else "")}'
                                  f'{abs(dt.offset_hours) if dt.offset_hours else ""}**.')


@plugins.argument()
def tag_arg(tag: str):
    """ A countdown tag. """
    return tag.lower().replace(" ", "")


@plugins.command(aliases="cd downcount")
async def countdown(message: discord.Message, tag: Annotate.Content):
    """ Display a countdown with the specified tag. """
    tag = tag_arg(tag)
    assert tag in time_cfg.data["countdown"], f"Countdown with tag `{tag}` does not exist."

    cd = time_cfg.data["countdown"][tag]
    dt = pendulum.parse(cd["time"], tz=cd["tz"])
    timezone_name = cd["tz_name"]

    await client.say(message, format_when(dt, timezone_name))


@plugins.command()
async def created(message: discord.Message, member: discord.Member = Annotate.Self):
    """ When your or the selected member's discord account was created. """
    member_created = pendulum.instance(member.created_at)
    channel = message.channel
    embed = discord.Embed(description=f'**Created {member_created.diff_for_humans()}**', timestamp=member.created_at,
                          color=member.color)
    embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
    await client.send_message(channel, embed=embed)


@plugins.command()
async def joined(message: discord.Message, member: discord.Member = Annotate.Self):
    """ When your or the selected member joined the guild. """
    member_joined = pendulum.instance(member.joined_at)
    channel = message.channel
    embed = discord.Embed(description=f'**Joined {member_joined.diff_for_humans()}**', timestamp=member.joined_at,
                          color=member.color)
    embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
    await client.send_message(channel, embed=embed)


@countdown.command(aliases="add", pos_check=True)
async def create(message: discord.Message, tag: tag_arg, *time, timezone: tz_arg = "UTC"):
    """ Create a countdown with the specified tag, using the same format as `{pre}when`. """
    assert tag not in time_cfg.data["countdown"], f"Countdown with tag `{tag}` already exists."

    timezone_name = timezone
    dt, timezone = await init_dt(message, " ".join(time), timezone)
    if dt is None or timezone is None:
        return

    seconds = (dt.diff(pendulum.now(timezone)).in_seconds())
    assert dt > pendulum.now(timezone), "A countdown has to be set in the future."

    cd = dict(time=dt.to_datetime_string(), tz=timezone, tz_name=timezone_name, tag=tag,
              author=str(message.author.id), channel=str(message.channel.id))
    time_cfg.data["countdown"][tag] = cd
    await time_cfg.asyncsave()
    await client.say(message, f"Added countdown with tag `{tag}`.")

    client.loop.create_task(wait_for_reminder(cd, seconds))


@countdown.command(aliases="remove")
async def delete(message: discord.Message, tag: Annotate.Content):
    """ Remove a countdown with the specified tag. You need to be the author of a tag
    in order to remove it. """
    tag = tag_arg(tag)
    assert tag in time_cfg.data["countdown"], f"Countdown with tag `{tag}` does not exist."

    author_id = time_cfg.data["countdown"][tag]["author"]
    assert str(message.author.id) == author_id, \
        'You are not the author of this tag ' \
        f'({getattr(discord.utils.get(client.get_all_members(), id=author_id), "name", None) or "~~Unknown~~"}).'

    del time_cfg.data["countdown"][tag]
    await time_cfg.asyncsave()
    await client.say(message, f"Countdown with tag `{tag}` removed.")


@countdown.command(name="list")
async def countdown_list(message: discord.Message, author: discord.Member = None):
    """ List all countdowns or all countdowns by the specified author. """
    assert time_cfg.data["countdown"], "There are no countdowns created."

    if author:
        tags = (tag for tag, value in time_cfg.data["countdown"].items() if value["author"] == str(author.id))
    else:
        tags = (tag for tag in time_cfg.data["countdown"].keys())

    await client.say(message, "**{}countdown tags**:```\n{}```".format(
        f"{author.name}'s " if author else "", ", ".join(tags)))


async def wait_for_reminder(cd, seconds):
    """ Wait for and send the reminder. This is a separate function so that . """
    try:
        await asyncio.sleep(seconds)
    except asyncio.CancelledError:
        return

    channel = client.get_channel(int(cd["channel"]))
    author = channel.guild.get_member(int(cd["author"]))

    msg = f"Hey {author.mention}, your countdown **{cd['tag']}** at `{cd['time']} {cd['tz_name']}` is over!"
    await client.send_message(channel, msg)

    del time_cfg.data["countdown"][cd["tag"]]
    await time_cfg.asyncsave()


async def handle_countdown_reminders():
    """ Handle countdowns after starting.
    Countdowns created afterwards are handled by the cd create command.
    """
    reminders = []
    for tag, cd in dict(time_cfg.data["countdown"]).items():
        dt = pendulum.parse(cd["time"], tz=cd["tz"])

        cd = dict(cd)
        cd["tag"] = tag
        cd["dt"] = dt
        reminders.append(cd)

    if not reminders:
        return

    # Go through the reminders starting at the newest one
    for cd in sorted(reminders, key=itemgetter("dt")):
        # Find in how many seconds the countdown will finish
        seconds = (cd["dt"].diff(pendulum.now(cd["tz"])).in_seconds())

        # If the next reminder is in longer than a month, don't bother waiting,
        if seconds > 60 * 60 * 24 * 30:
            return

        # In case of multiple countdowns at once, set a threshold at -10 seconds
        # If below, remove the countdown and continue
        if seconds < -10:
            del time_cfg.data["countdown"][cd["tag"]]
            await time_cfg.asyncsave()
            continue
        seconds = max(seconds, 0)

        await wait_for_reminder(cd, seconds)


async def on_ready():
    """ Start a task for startup countdowns. """
    client.loop.create_task(handle_countdown_reminders())
