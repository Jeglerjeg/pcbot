import discord
import bot
import plugins
from pcbot import utils

from plugins.scoresaberlib import api
from plugins.scoresaberlib.formatting import score_format, embed_format
from plugins.scoresaberlib.utils import user_utils

client = plugins.client  # type: bot.Client

@plugins.command()
async def scoresaber(message, _: utils.placeholder):
    """ Score saber plugin. """

@scoresaber.command()
async def score(message: discord.Message, map_id: int, user: str):
    scoresaber_score = await api.get_user_map_score(map_id, user)
    leaderboard_info = await api.get_leaderboard_info(map_id)
    formatted_text = score_format.format_new_score(scoresaber_score, leaderboard_info)
    embed = embed_format.get_embed_from_template(formatted_text,
                                                 message.author.color,
                                                 scoresaber_score.player.name,
                                                 user_utils.get_user_url(scoresaber_score.player.id),
                                                 scoresaber_score.player.profile_picture,
                                                 leaderboard_info.cover_image)
    await client.send_message(message.channel, embed=embed)

@scoresaber.command()
async def recent(message: discord.Message, user: str):
    user = await api.get_user(user)
    assert user, "Couldn't find user."
    scoresaber_scores = await api.get_user_scores(user.id, "recent", 1)
    if not scoresaber_scores or len(scoresaber_scores) <1:
        await client.say(message, "Found no recent score.")
        return
    recent_score = scoresaber_scores[0]
    scoresaber_score = recent_score[0]
    leaderboard_info = recent_score[1]
    formatted_text = score_format.format_new_score(scoresaber_score, leaderboard_info)
    embed = embed_format.get_embed_from_template(formatted_text,
                                                 message.author.color,
                                                 user.name,
                                                 user_utils.get_user_url(user.id),
                                                 user.profile_picture,
                                                 leaderboard_info.cover_image)
    await client.send_message(message.channel, embed=embed)