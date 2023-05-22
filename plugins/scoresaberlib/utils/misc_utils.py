import discord

from plugins.scoresaberlib import config
from plugins.scoresaberlib.models.player import ScoreSaberPlayer

pp_threshold = config.scoresaber_config.data.get("pp_threshold", 0.5)


def check_for_pp_difference(new_scoresaber_user: ScoreSaberPlayer, old_scoresaber_user: ScoreSaberPlayer = None):
    """ Check if user has gained enough PP to notify a score. """
    if not old_scoresaber_user:
        return False

    # Get the difference in pp since the old data
    pp_diff = new_scoresaber_user.pp - old_scoresaber_user.pp

    # If the difference is too small or nothing, move on
    if pp_threshold > pp_diff > -pp_threshold:
        return False

    return True


def get_notify_channels(guild: discord.Guild, data_type: str):
    """ Find the notifying channel or return the guild. """
    if str(guild.id) not in config.scoresaber_config.data["guild"]:
        return None

    if "".join([data_type, "-channels"]) not in config.scoresaber_config.data["guild"][str(guild.id)]:
        return None

    return [guild.get_channel(int(s))
            for s in config.scoresaber_config.data["guild"][str(guild.id)]["".join([data_type, "-channels"])]
            if guild.get_channel(int(s))]


async def init_guild_config(guild: discord.Guild):
    """ Initializes the config when it's not already set. """
    if str(guild.id) not in config.scoresaber_config.data["guild"]:
        config.scoresaber_config.data["guild"][str(guild.id)] = {}
        await config.scoresaber_config.asyncsave()