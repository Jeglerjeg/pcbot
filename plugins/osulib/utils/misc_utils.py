import copy

import discord

from pcbot import Config
from plugins.osulib import enums
from plugins.osulib.config import osu_config
from plugins.osulib.constants import timestamp_pattern, pp_threshold
from plugins.osulib.models.score import OsuScore


def get_diff(old: dict, new: dict, value: str):
    """ Get the difference between old and new osu! user data. """
    if not new or not old or "statistics" not in new or "statistics" not in old:
        return 0.0

    new_value = float(new["statistics"][value]) if new["statistics"][value] else 0.0
    old_value = float(old["statistics"][value]) if old["statistics"][value] else 0.0

    return new_value - old_value


async def save_profile_data(user_data: Config):
    data_copy = copy.deepcopy(user_data.data)
    if not user_data.data:
        await user_data.asyncsave()
    for profile in user_data.data:
        if "scores" not in user_data.data[profile] or "score_list" not in user_data.data[profile]["scores"]:
            continue
        user_data.data[profile]["scores"]["score_list"] = \
            [osu_score.to_dict() for osu_score in user_data.data[profile]["scores"]["score_list"]
             if isinstance(osu_score, OsuScore)]

    await user_data.asyncsave()
    user_data.data = data_copy


def load_profile_data(user_data: dict):
    if not user_data:
        return {}
    for profile in user_data:
        if "scores" not in user_data[profile] or "score_list" not in user_data[profile]["scores"]:
            continue
        user_data[profile]["scores"]["score_list"] = \
            [OsuScore(osu_score, from_file=True) for osu_score in user_data[profile]["scores"]["score_list"]]

    return user_data


def get_notify_channels(guild: discord.Guild, data_type: str):
    """ Find the notifying channel or return the guild. """
    if str(guild.id) not in osu_config.data["guild"]:
        return None

    if "".join([data_type, "-channels"]) not in osu_config.data["guild"][str(guild.id)]:
        return None

    return [guild.get_channel(int(s)) for s in osu_config.data["guild"][str(guild.id)]["".join([data_type,
                                                                                                "-channels"])]
            if guild.get_channel(int(s))]


def get_timestamps_with_url(content: str):
    """ Yield every map timestamp found in a string, and an edditor url.

    :param content: The string to search
    :returns: a tuple of the timestamp as a raw string and an editor url
    """
    for match in timestamp_pattern.finditer(content):
        editor_url = match.group(1).strip(" ").replace(" ", "%20").replace(")", r")")
        yield match.group(0), f"<osu://edit/{editor_url}>"


def calculate_acc(mode: enums.GameMode, osu_score: OsuScore, exclude_misses: bool = False):
    """ Calculate the accuracy using formulas from https://osu.ppy.sh/wiki/Accuracy """

    # Catch accuracy is done a tad bit differently, so we calculate that by itself
    if mode is enums.GameMode.fruits:
        total_numbers_of_fruits_caught = osu_score.count_smalltickhit + osu_score.count_largetickhit +\
                                         osu_score.count_300
        total_numbers_of_fruits = (osu_score.count_miss + osu_score.count_smalltickhit + osu_score.count_largetickhit +
                                   osu_score.count_300 + osu_score.count_smalltickmiss)
        return total_numbers_of_fruits_caught / total_numbers_of_fruits

    total_points_of_hits, total_number_of_hits = 0, 0

    if mode is enums.GameMode.osu:
        total_points_of_hits = osu_score.count_50 * 50 + osu_score.count_100 * 100 + osu_score.count_300 * 300
        total_number_of_hits = ((0 if exclude_misses else osu_score.count_miss) + osu_score.count_50 +
                                osu_score.count_100 + osu_score.count_300)
    elif mode is enums.GameMode.taiko:
        total_points_of_hits = (osu_score.count_miss * 0 + osu_score.count_100 * 0.5 + osu_score.count_300 * 1) * 300
        total_number_of_hits = osu_score.count_miss + osu_score.count_100 + osu_score.count_300
    elif mode is enums.GameMode.mania:
        # In mania, katu is 200s and geki is MAX
        total_points_of_hits = osu_score.count_50 * 50 + osu_score.count_100 * 100 + osu_score.count_200 * 200 +\
                               (osu_score.count_300 + osu_score.count_max) * 300
        total_number_of_hits = (osu_score.count_miss + osu_score.count_50 + osu_score.count_100 + osu_score.count_200 +
                                osu_score.count_300 + osu_score.count_max)

    return total_points_of_hits / (total_number_of_hits * 300)


async def init_guild_config(guild: discord.Guild):
    """ Initializes the config when it's not already set. """
    if str(guild.id) not in osu_config.data["guild"]:
        osu_config.data["guild"][str(guild.id)] = {}
        await osu_config.asyncsave()


def check_for_pp_difference(data: dict):
    """ Check if user has gained enough PP to notify a score. """
    if "old" not in data:
        return False

    # Get the difference in pp since the old data
    old, new = data["old"], data["new"]
    pp_diff = get_diff(old, new, "pp")

    # If the difference is too small or nothing, move on
    if pp_threshold > pp_diff > -pp_threshold:
        return False

    return True


def check_for_new_recent_events(data: dict):
    """ Check if the user has any new recent events. """
    if "old" not in data or not data["old"]:
        return False

    # Get the old and the new events
    old, new = data["old"]["events"], data["new"]["events"]

    # If nothing has changed, move on to the next member
    if old == new:
        return False

    return True
