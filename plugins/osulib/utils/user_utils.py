from datetime import datetime

import discord

from pcbot import config
from plugins.osulib import enums, api
from plugins.osulib.config import osu_config
from plugins.osulib.constants import host, minimum_pp_required
from plugins.osulib.db import get_linked_osu_profile
from plugins.osulib.enums import GameMode


def get_missing_user_string(guild: discord.Guild):
    """ Format missing user text for all commands needing it. """
    return f"No osu! profile assigned! Please assign a profile using " \
           f"**{config.guild_command_prefix(guild)}osu link <username>**"


async def get_user(message: discord.Message, member: discord.Member, username: str = None, mode: GameMode = None):
    """ Get member by discord username or osu username. """
    if username:
        osu_user = await api.get_user(f"@{username}", mode.name if mode else "")
    else:
        linked_profile = get_linked_osu_profile(member.id)
        assert linked_profile, get_missing_user_string(message.guild)
        osu_user = await api.get_user(linked_profile.osu_id, mode.name if mode else GameMode(linked_profile.mode).name)

    assert osu_user, "Failed to get user data. Please try again later."

    return osu_user


async def retrieve_user_profile(profile: str, mode: enums.GameMode, timestamp: datetime = None):
    user_data = await api.get_user(profile, mode.name)
    if not user_data:
        return None
    if timestamp:
        user_data.set_time_cached(timestamp)
    return user_data


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


def get_leaderboard_update_status(member_id: str):
    """ Return whether the user should have leaderboard scores posted automatically. """
    if member_id in osu_config.data["leaderboard"]:
        return osu_config.data["leaderboard"][member_id]

    return not bool(osu_config.data["opt_in_leaderboard"])


def get_beatmap_update_status(member_id: str):
    """ Return whether the user should have leaderboard scores posted automatically. """
    if member_id in osu_config.data["beatmap_updates"]:
        return osu_config.data["beatmap_updates"][member_id]

    return not bool(osu_config.data["opt_in_beatmaps"])


def get_mode(member_id: str):
    """ Return the enums.GameMode for the member with this id. """
    linked_profile = get_linked_osu_profile(int(member_id))
    if not linked_profile:
        mode = enums.GameMode.osu
        return mode

    return GameMode(linked_profile.mode)


def get_update_mode(member_id: str):
    """ Return the member's update mode. """
    linked_profile = get_linked_osu_profile(int(member_id))
    if not linked_profile or not linked_profile.update_mode:
        return enums.UpdateModes.Full

    return enums.UpdateModes.get_mode(linked_profile.update_mode)


def get_user_url(osu_id: str):
    """ Return the user website URL. """
    return "".join([host, "/users/", str(osu_id)])


async def has_enough_pp(user: str, mode: enums.GameMode, **params):
    """ Lookup the given member and check if they have enough pp to register.
    params are just like api.get_user. """
    osu_user = await api.get_user(user, mode, params=params)
    return osu_user.pp or 0.0 >= minimum_pp_required


def user_exists(member: discord.Member, member_id: str, profile: str):
    """ Check if the bot can see a member, and that the member exists in config files. """
    linked_profile = get_linked_osu_profile(int(member_id))
    return member is None or not linked_profile or int(profile) != linked_profile.osu_id


def user_unlinked_during_iteration(member_id: int):
    """ Check if the member was unlinked after iteration started. """
    return not bool(get_linked_osu_profile(member_id))
