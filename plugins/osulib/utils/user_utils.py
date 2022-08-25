import discord

from pcbot import config, utils
from plugins.osulib import enums, api
from plugins.osulib.constants import host, minimum_pp_required
from plugins.osulib.config import osu_config


def get_missing_user_string(member: discord.Member):
    """ Format missing user text for all commands needing it. """
    return f"No osu! profile assigned to **{member.name}**! Please assign a profile using " \
           f"**{config.guild_command_prefix(member.guild)}osu link <username>**"


def get_user(message: discord.Message, username: str, osu_tracking: dict):
    """ Get member by discord username or osu username. """
    member = utils.find_member(guild=message.guild, name=username)
    if not member:
        for key, value in osu_tracking.items():
            if value["new"]["username"].lower() == username.lower():
                member = discord.utils.get(message.guild.members, id=int(key))
    return member


async def retrieve_user_proile(profile: str, mode: enums.GameMode, timestamp: str):
    params = {
        "key": "id"
    }
    user_data = await api.get_user(profile, mode.name, params=params)
    if not user_data:
        return None
    user_data["time_updated"] = timestamp
    if "monthly_playcounts" in user_data:
        del user_data["monthly_playcounts"]
    if "page" in user_data:
        del user_data["page"]
    if "replays_watched_counts" in user_data:
        del user_data["replays_watched_counts"]
    if "user_achievements" in user_data:
        del user_data["user_achievements"]
    if "rankHistory" in user_data:
        del user_data["rankHistory"]
    if "rank_history" in user_data:
        del user_data["rank_history"]
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


def get_primary_guild(member_id: str):
    """ Return the primary guild for a member or None. """
    return osu_config.data["primary_guild"].get(member_id, None)


def get_mode(member_id: str):
    """ Return the enums.GameMode for the member with this id. """
    if member_id not in osu_config.data["mode"]:
        mode = enums.GameMode.osu
        return mode

    value = int(osu_config.data["mode"][member_id])
    mode = enums.GameMode(value)
    return mode


def get_update_mode(member_id: str):
    """ Return the member's update mode. """
    if member_id not in osu_config.data["update_mode"]:
        return enums.UpdateModes.Full

    return enums.UpdateModes.get_mode(osu_config.data["update_mode"][member_id])


def get_user_url(member_id: str):
    """ Return the user website URL. """
    user_id = osu_config.data["profiles"][member_id]

    return "".join([host, "users/", user_id])


async def has_enough_pp(user: str, mode: enums.GameMode, **params):
    """ Lookup the given member and check if they have enough pp to register.
    params are just like api.get_user. """
    osu_user = await api.get_user(user, mode, params=params)
    return osu_user["statistics"]["pp"] >= minimum_pp_required


def user_exists(member: discord.Member, member_id: str, profile: str):
    """ Check if the bot can see a member, and that the member exists in config files. """
    return (member is None or member_id not in osu_config.data["profiles"]
            or profile not in osu_config.data["profiles"][member_id])


def user_unlinked_during_iteration(member_id: str, data: dict):
    """ Check if the member was unlinked after iteration started. """
    return (member_id in data and "new" in data[member_id] and data[member_id]["new"]
            and "id" in data[member_id]["new"]
            and str(data[member_id]["new"]["id"]) not in osu_config.data["profiles"][member_id])
