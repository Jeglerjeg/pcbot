""" Plugin for guild moderation

The bot will perform different tasks when some settings are enabled in a guild:

_____________________________________NSFW Filter_____________________________________
    If enabled on the guild, spots any text containing the keyword nsfw and a link.
    Then tries to delete their message, and post a link to the dedicated nsfw channel.

Commands:
    moderate
    mute
    unmute
    timeout
    suspend
"""

import asyncio
import datetime
import json
import os

import discord
from sqlalchemy.sql import select, insert, update

import bot
import plugins
from pcbot import utils, Annotate
from pcbot.db import engine, db_metadata

client = plugins.client  # type: bot.Client


def migrate():
    with open("config/moderate.json", encoding="utf-8") as f:
        data = json.load(f)
        query_data = []
        for guild_id, settings in data.items():
            query_data.append({"guild_id": guild_id, "nsfwfilter": settings["nsfwfilter"],
                               "changelog": settings["changelog"]})
        with engine.connect() as connection:
            table = db_metadata.tables["moderate"]
            statement = insert(table).values(query_data)
            transaction = connection.begin()
            connection.execute(statement)
            transaction.commit()
    os.remove("config/moderate.json")


if os.path.exists("config/moderate.json"):
    migrate()


def add_new_guild(guild_id: int):
    with engine.connect() as connection:
        table = db_metadata.tables["moderate"]
        statement = insert(table).values(guild_id=guild_id, nsfwfilter=False, changelog=False)
        transaction = connection.begin()
        connection.execute(statement)
        transaction.commit()


def retrieve_guild(guild_id: int):
    with engine.connect() as connection:
        table = db_metadata.tables["moderate"]
        statement = select(table).where(table.c.guild_id == guild_id)
        result = connection.execute(statement)
        return result.fetchone()


def update_setting(guild_id: int, setting: str, new_value: bool):
    with engine.connect() as connection:
        table = db_metadata.tables["moderate"]
        statement = update(table).where(table.c.guild_id == guild_id).values({setting: new_value})
        transaction = connection.begin()
        connection.execute(statement)
        transaction.commit()


def get_guild_config(guild_id: int):
    guild_config = retrieve_guild(guild_id)
    if not guild_config:
        add_new_guild(guild_id)
        guild_config = retrieve_guild(guild_id)
    return guild_config


@plugins.command(name="moderate", permissions="manage_messages")
async def moderate_(message, _: utils.placeholder):
    """ Change moderation settings. """


def add_setting(setting: str, default=True, name=None, permissions=None):
    """ Create a set of subcommands for the given setting (True or False).

    :param setting: display name for the setting.
    :param default: The default value for this setting.
    :param name: optionally set the name of the subcommand.
    :param permissions: what permissions are required to change this setting (list of str). """
    if not name:
        name = setting.lower().replace("\n", "").replace(" ", "")

    @moderate_.command(name=name, usage="[on | off]", permissions=permissions,
                       description=f"Display current {setting} setting or enable/disable it.")
    async def display_setting(message: discord.Message):
        """ The command to display the current setting. """
        guild_config = get_guild_config(message.guild.id)
        current = guild_config.name
        await client.say(message, f'{setting} is **{"enabled" if current else "disabled"}**.')

    @display_setting.command(hidden=True, aliases="true set enable", permissions=permissions)
    async def on(message: discord.Message):
        """ The command to enable this setting. """
        update_setting(message.guild.id, name, True)
        await client.say(message, f"{setting} **enabled**.")

    @display_setting.command(hidden=True, aliases="false unset disable", permissions=permissions)
    async def off(message: discord.Message):
        """ The command to enable this setting. """
        update_setting(message.guild.id, name, False)
        await client.say(message, f"{setting} **disabled**.")


add_setting("NSFW filter", permissions=["manage_guild"])
add_setting("Changelog", permissions=["manage_guild"], default=False)


@plugins.command(pos_check=True, permissions="moderate_members")
async def unmute(message: discord.Message, *members: discord.Member):
    """ Unmute the specified members. """
    assert message.channel.permissions_for(message.guild.me).moderate_members, \
        "I need `Moderate Member` permission to use this command."

    muted_members = []
    for member in members:
        if member.is_timed_out():
            await member.edit(timed_out_until=None)
            muted_members.append(member)
        else:
            await client.say(message, f"{member.display_name} isn't muted.")

    # Some members were unmuted, success!
    if muted_members:
        await client.say(message, f"Unmuted {utils.format_objects(*muted_members, dec='`')}")


@plugins.command(permissions="moderate_members", aliases="mute")
async def timeout(message: discord.Message, member: discord.Member, minutes: float, reason: Annotate.Content):
    """ Timeout a user in minutes (will accept decimal numbers), send them
    the reason for being timed out and post the reason in the guild's
    changelog if it has one. """

    assert message.channel.permissions_for(message.guild.me).moderate_members, \
        "I need `Moderate Member` permission to use this command."

    if member.is_timed_out():
        await client.say(message, "This member is already muted.")
        return

    timeout_duration = datetime.datetime.now(tz=datetime.timezone.utc) + datetime.timedelta(minutes=minutes)
    try:
        await member.timeout(timeout_duration, reason=reason)
    except discord.Forbidden:
        await client.say(message, "I don't have permission to timeout this member.")

    # Do not progress if the members were not successfully muted
    # At this point, manage_mute will have reported any errors
    if not member.is_timed_out():
        return

    changelog_channel = get_changelog_channel(message.guild)

    # Tell the member and post in the changelog
    m = f"You were timed out from **{message.guild}** for **{minutes} minutes**. \n**Reason:** {reason}"
    try:
        await client.send_message(member, m)
    except discord.Forbidden:
        pass

    if changelog_channel:
        await client.send_message(changelog_channel,
                                  f"{message.author.mention} Timed out {member.mention} for **{minutes} minutes**. "
                                  f"**Reason:** {reason}")
    client.loop.create_task(client.delete_message(message))


@plugins.command(aliases="muteall mute* unmuteall unmute*", permissions="manage_messages")
async def suspend(message: discord.Message, channel: discord.TextChannel = Annotate.Self):
    """ Suspends a channel by removing send permission for the guild's default role.
    This function acts like a toggle. """
    assert message.channel.permissions_for(message.guild.me).manage_roles, \
        "I need `Manage Roles` permission to use this command."
    send = channel.overwrites_for(message.guild.default_role).send_messages
    overwrite = discord.PermissionOverwrite(send_messages=False if send is None else not send)
    bot_overwrite = discord.PermissionOverwrite(send_messages=True)
    if channel.overwrites_for(message.guild.me.top_role).send_messages is None:
        await channel.set_permissions(message.guild.me.top_role, overwrite=bot_overwrite)
    await channel.set_permissions(message.guild.default_role, overwrite=overwrite)

    try:
        if overwrite.send_messages:
            await client.say(message, f"{channel.mention} is no longer suspended.")
        else:
            await client.say(message, f"Suspended {channel.mention}.")
    except discord.Forbidden:  # ...
        await client.send_message(message.author, f"You just removed my send permission in {channel.mention}.")


@plugins.argument("{open}member/#channel {suffix}{close}", pass_message=True)
def members_and_channels(message: discord.Message, arg: str):
    """ Look for both members and channel mentions. """
    if utils.channel_mention_pattern.match(arg):
        return utils.find_channel(message.guild, arg)

    return utils.find_member(message.guild, arg)


@plugins.command(permissions="manage_messages", aliases="prune delete")
async def purge(message: discord.Message, *instances: members_and_channels, num: utils.int_range(1, 100)):
    """ Purge the given amount of messages from the specified members or all.
    You may also specify a channel to delete from.

    `num` is a number from 1 to 100. """
    instances = list(instances)

    channel = message.channel
    for instance in instances.copy():
        if isinstance(instance, discord.TextChannel):
            channel = instance
            instances.remove(instance)
            break

    assert not any(i for i in instances if isinstance(i, discord.TextChannel)), "**I can only purge in one channel.**"
    to_delete = []

    async for m in channel.history(before=message):
        if len(to_delete) >= num:
            break

        if not instances or m.author in instances:
            to_delete.append(m)

    deleted = len(to_delete)
    if deleted > 1:
        await client.delete_messages(message.channel, to_delete)
    elif deleted == 1:
        await client.delete_message(to_delete[0])

    m = await client.say(message, f'Purged **{deleted}** message{"" if deleted == 1 else "s"}.')

    # Remove both the command message and the feedback after 5 seconds
    await asyncio.sleep(5)
    await client.delete_messages(message.channel, [m, message])


async def check_nsfw(message: discord.Message):
    """ Check if the message is NSFW (very rough check). """
    # Check if this guild has nsfwfilter enabled
    # Do not check if the channel is designed for nsfw content
    if "nsfw" in message.channel.name or message.channel.is_nsfw():
        return False

    # Check if message includes keyword nsfw and a link
    msg = message.content.lower()
    if "nsfw" in msg and ("http://" in msg or "https://" in msg):
        if message.channel.permissions_for(message.guild.me).manage_messages:
            await client.delete_message(message)

        nsfw_channel = discord.utils.find(lambda c: "nsfw" in c.name, message.guild.channels)

        if nsfw_channel:
            await client.say(message,
                             f"{message.author.mention}: **Please post NSFW content in {nsfw_channel.mention}**")

        return True


@plugins.event()
async def on_message(message: discord.Message):
    """ Check plugin settings. """
    # Do not check in private messages
    if not message.guild:
        return

    guild_config = get_guild_config(message.guild.id)

    if guild_config.nsfwfilter:
        await check_nsfw(message)


def get_changelog_channel(guild: discord.Guild):
    """ Return the changelog channel for a guild. """
    if not guild:
        return None

    guild_config = get_guild_config(guild.id)
    if not guild_config.changelog:
        return None

    channel = discord.utils.get(guild.channels, name="changelog")
    if channel is None:
        return None

    permissions = channel.permissions_for(guild.me)
    if not permissions.send_messages or not permissions.read_messages:
        return None

    return channel


async def log_change(channel: discord.TextChannel, message: str):
    """ Log change to changelog channel. """
    embed = discord.Embed(description=message)
    await client.send_message(channel, embed=embed)


@plugins.event()
async def on_message_delete(message: discord.Message):
    """ Update the changelog with deleted messages. """
    changelog_channel = get_changelog_channel(message.guild)
    # Don't log any message the bot deleted
    for m in client.last_deleted_messages:
        if m.id == message.id:
            return

    if changelog_channel is None:
        return

    if message.channel == changelog_channel:
        return

    if message.author == client.user:
        return

    if message.attachments:
        attachments = ""
        for attachment in message.attachments:
            attachments += attachment.filename + "\n"
        await log_change(
            changelog_channel,
            f"{message.author.mention}'s message was deleted "
            f"in {message.channel.mention}:\n{message.clean_content}\nAttachments:\n``{attachments}``"
        )
    else:
        await log_change(
            changelog_channel,
            f"{message.author.mention}'s message was deleted in {message.channel.mention}:\n{message.clean_content}"
        )


@plugins.event()
async def on_guild_channel_create(channel: discord.TextChannel):
    """ Update the changelog with created channels. """
    if isinstance(channel, discord.abc.PrivateChannel):
        return

    changelog_channel = get_changelog_channel(channel.guild)
    if not changelog_channel:
        return

    # Differ between voice channels and text channels
    if channel.type == discord.ChannelType.text:
        await log_change(changelog_channel, f"Channel {channel.mention} was created.")
    else:
        await log_change(changelog_channel, f"Voice channel **{channel.name}** was created.")


@plugins.event()
async def on_guild_channel_delete(channel: discord.TextChannel):
    """ Update the changelog with deleted channels. """
    if isinstance(channel, discord.abc.PrivateChannel):
        return

    changelog_channel = get_changelog_channel(channel.guild)
    if not changelog_channel:
        return

    # Differ between voice channels and text channels
    if channel.type == discord.ChannelType.text:
        await log_change(changelog_channel, f"Channel **#{channel.name}** was deleted.")
    else:
        await log_change(changelog_channel, f"Voice channel **{channel.name}** was deleted.")


@plugins.event()
async def on_guild_channel_update(before: discord.TextChannel, after: discord.TextChannel):
    """ Update the changelog when a channel changes name. """
    if isinstance(after, discord.abc.PrivateChannel):
        return

    changelog_channel = get_changelog_channel(after.guild)
    if not changelog_channel:
        return

    # We only want to update when a name change is performed
    if before.name == after.name:
        return

    # Differ between voice channels and text channels
    if after.type == discord.ChannelType.text:
        await log_change(
            changelog_channel, f"Channel **#{before.name}** changed name to {after.mention}, **{after.name}**.")
    else:
        await log_change(
            changelog_channel, f"Voice channel **{before.name}** changed name to **{after.name}**.")


@plugins.event()
async def on_member_join(member: discord.Member):
    """ Update the changelog with members joined. """
    changelog_channel = get_changelog_channel(member.guild)
    if not changelog_channel:
        return

    await log_change(changelog_channel, f"{member.mention} joined the guild.")


@plugins.event()
async def on_member_remove(member: discord.Member):
    """ Update the changelog with deleted channels. """
    changelog_channel = get_changelog_channel(member.guild)
    if not changelog_channel:
        return

    await log_change(changelog_channel, f"{member.mention} ({member.name}) left the guild.")


@plugins.event()
async def on_member_update(before: discord.Member, after: discord.Member):
    """ Update the changelog with any changed names and roles. """
    name_change = not before.name == after.name
    nick_change = not before.nick == after.nick
    role_change = not before.roles == after.roles

    changelog_channel = get_changelog_channel(after.guild)
    if not changelog_channel:
        return

    # Format the nickname or username changed
    if name_change:
        m = f"{before.mention} (previously **{before.name}**) changed their username to **{after.name}**."
    elif nick_change:
        if not before.nick:
            m = f"{before.mention} (previously **{before.name}**) got the nickname **{after.nick}**."
        elif not after.nick:
            m = f"{before.mention} (previously **{before.nick}**) no longer has a nickname."
        else:
            m = f"{before.mention} (previously **{before.nick}**) got the nickname **{after.nick}**."
    elif role_change:
        muted_role = discord.utils.get(after.guild.roles, name="Muted")

        if len(before.roles) > len(after.roles):
            role = [r for r in before.roles if r not in after.roles][0]
            if role == muted_role:
                return

            m = f"{after.mention} lost the role **{role.name}**"
        else:
            role = [r for r in after.roles if r not in before.roles][0]
            if role == muted_role:
                return

            m = f"{after.mention} received the role **{role.name}**"
    else:
        return

    await log_change(changelog_channel, m)


@plugins.event()
async def on_member_ban(guild: discord.Guild, member: discord.Member):
    """ Update the changelog with banned members. """
    changelog_channel = get_changelog_channel(guild)
    if not changelog_channel:
        return

    await log_change(changelog_channel,
                     f"{member.mention} ({member.name}) was banned from the guild.")


@plugins.event()
async def on_member_unban(guild: discord.Guild, user: discord.Member):
    """ Update the changelog with unbanned members. """
    changelog_channel = get_changelog_channel(guild)
    if not changelog_channel:
        return

    await log_change(changelog_channel, f"{user.mention} was unbanned from the guild.")
