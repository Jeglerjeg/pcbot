import discord

from pcbot import config


def get_user_url(user_id: int):
    return f"https://scoresaber.com/u/{user_id}"

def get_missing_user_string(member: discord.Member):
    """ Format missing user text for all commands needing it. """
    return f"No scoresaber profile assigned to **{member.name}**! Please assign a profile using " \
           f"**{config.guild_command_prefix(member.guild)}scoresaber link <username>**"