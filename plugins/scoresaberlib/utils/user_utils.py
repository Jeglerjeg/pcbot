import discord

from pcbot import config, utils
from plugins.scoresaberlib import db, api


def get_user_url(user_id: int):
    return f"https://scoresaber.com/u/{user_id}"


def get_missing_user_string(member: discord.Member):
    """ Format missing user text for all commands needing it. """
    return f"No scoresaber profile assigned to **{member.name}**! Please assign a profile using " \
           f"**{config.guild_command_prefix(member.guild)}scoresaber link <username>**"


async def get_user(message: discord.Message, username: str):
    """ Get member by discord username or scoresaber username. """
    member = utils.find_member(guild=message.guild, name=username)
    if not member:
        user = await api.get_user(username)
    else:
        linked_profile = db.get_linked_scoresaber_profile(member.id)
        if not linked_profile:
            user = await api.get_user(username)
        else:
            user = await api.get_user_by_id(linked_profile.scoresaber_id)
    return user


def is_playing(member: discord.Member):
    """ Check if a member has "BeatSaber" in their Game name. """
    # See if the member is playing
    for activity in member.activities:
        if activity is not None and activity.name is not None:
            if "beat saber" in activity.name.lower():
                return True
            if activity == discord.ActivityType.streaming and "beat saber" in activity.game.lower():
                return True

    return False