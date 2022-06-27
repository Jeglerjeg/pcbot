import discord

from plugins.osulib import enums
from plugins.osulib.constants import timestamp_pattern, pp_threshold
from plugins.osulib.config import osu_config


def get_diff(old: dict, new: dict, value: str, statistics=False):
    """ Get the difference between old and new osu! user data. """
    if not new or not old or not new["statistics"] or not old["statistics"]:
        return 0.0
    if statistics:
        new_value = float(new["statistics"][value]) if new["statistics"][value] else 0.0
        old_value = float(old["statistics"][value]) if old["statistics"][value] else 0.0
    else:
        new_value = float(new[value]) if new[value] else 0.0
        old_value = float(old[value]) if old[value] else 0.0

    return new_value - old_value


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


def calculate_acc(mode: enums.GameMode, osu_score: dict, exclude_misses: bool = False):
    """ Calculate the accuracy using formulas from https://osu.ppy.sh/wiki/Accuracy """
    # Parse data from the score: 50s, 100s, 300s, misses, katu and geki
    keys = ("count_300", "count_100", "count_50", "count_miss", "count_katu", "count_geki")
    c300, c100, c50, miss, katu, geki = map(int, (osu_score["statistics"][key] for key in keys))

    # Catch accuracy is done a tad bit differently, so we calculate that by itself
    if mode is enums.GameMode.fruits:
        total_numbers_of_fruits_caught = c50 + c100 + c300
        total_numbers_of_fruits = miss + c50 + c100 + c300 + katu
        return total_numbers_of_fruits_caught / total_numbers_of_fruits

    total_points_of_hits, total_number_of_hits = 0, 0

    if mode is enums.GameMode.osu:
        total_points_of_hits = c50 * 50 + c100 * 100 + c300 * 300
        total_number_of_hits = (0 if exclude_misses else miss) + c50 + c100 + c300
    elif mode is enums.GameMode.taiko:
        total_points_of_hits = (miss * 0 + c100 * 0.5 + c300 * 1) * 300
        total_number_of_hits = miss + c100 + c300
    elif mode is enums.GameMode.mania:
        # In mania, katu is 200s and geki is MAX
        total_points_of_hits = c50 * 50 + c100 * 100 + katu * 200 + (c300 + geki) * 300
        total_number_of_hits = miss + c50 + c100 + katu + c300 + geki

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
    pp_diff = get_diff(old, new, "pp", statistics=True)

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
