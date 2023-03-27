from datetime import datetime

import discord

from pcbot import config, utils
from plugins.osulib import enums, api
from plugins.osulib.config import osu_config
from plugins.osulib.constants import host, minimum_pp_required
from plugins.osulib.db import get_linked_osu_profile, get_osu_users, get_linked_osu_profile_accounts
from plugins.osulib.enums import GameMode


def get_missing_user_string(member: discord.Member):
    """ Format missing user text for all commands needing it. """
    return f"No osu! profile assigned to **{member.name}**! Please assign a profile using " \
           f"**{config.guild_command_prefix(member.guild)}osu link <username>**"


def get_user(message: discord.Message, username: str):
    """ Get member by discord username or osu username. """
    member = utils.find_member(guild=message.guild, name=username)
    if not member:
        osu_users = get_osu_users()
        for osu_user in osu_users:
            if osu_user.username.lower() == username.lower():
                linked_profiles = get_linked_osu_profile_accounts(osu_user.id)
                for linked_profile in linked_profiles:
                    member = discord.utils.get(message.guild.members, id=int(linked_profile.id))
                    if not member:
                        continue
                if not member:
                    continue

    return member


async def retrieve_user_proile(profile: str, mode: enums.GameMode, timestamp: datetime):
    params = {
        "key": "id"
    }
    user_data = await api.get_user(profile, mode.name, params=params)
    if not user_data:
        return None
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
    """ Return whether or not the user should have leaderboard scores posted automatically. """
    if member_id in osu_config.data["leaderboard"]:
        return osu_config.data["leaderboard"][member_id]

    return not bool(osu_config.data["opt_in_leaderboard"])


def get_beatmap_update_status(member_id: str):
    """ Return whether or not the user should have leaderboard scores posted automatically. """
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


def get_user_url(member_id: str):
    """ Return the user website URL. """
    user_id = get_linked_osu_profile(int(member_id)).osu_id

    return "".join([host, "/users/", str(user_id)])


async def has_enough_pp(user: str, mode: enums.GameMode, **params):
    """ Lookup the given member and check if they have enough pp to register.
    params are just like api.get_user. """
    osu_user = await api.get_user(user, mode, params=params)
    return osu_user.pp >= minimum_pp_required


def user_exists(member: discord.Member, member_id: str, profile: str):
    """ Check if the bot can see a member, and that the member exists in config files. """
    linked_profile = get_linked_osu_profile(int(member_id))
    return member is None or not linked_profile or int(profile) != linked_profile.osu_id


def user_unlinked_during_iteration(member_id: int):
    """ Check if the member was unlinked after iteration started. """
    return not bool(get_linked_osu_profile(member_id))
