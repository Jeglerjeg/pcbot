import discord
import requests
import time
from plugins.osulib.card.image import draw_card
from plugins.osulib.card.embed import get_card_embed
from plugins.osulib.api import get_user
from plugins.osulib.enums import GameMode


# Adapted from https://github.com/respektive/osualt-bot/blob/main/src/card/, thanks respektive!

def get_avatar_url_from_id(user_id: int):
    return f"https://a.ppy.sh/{user_id}?{int(time.time())}"


def get_image_data_from_url(image_url: str):
    response = requests.get(image_url)
    image_data = response.content
    return image_data


async def get_card(user_id: int, mode: GameMode, color: discord.Colour):
    params = {
        "key": "id",
    }
    user_data = await get_user(user_id, mode.name, params=params)
    assert user_data, "Failed to get user data, please try again later."
    # Fallback to generating an avatar_url if for some reason the url is not set
    avatar_url = user_data.avatar_url or get_avatar_url_from_id(user_id)
    avatar_data = get_image_data_from_url(avatar_url)
    image = await draw_card(user_data, avatar_data, (color.r, color.g, color.b), mode.value)
    embed, file = get_card_embed(image, user_data, avatar_url, color)

    return embed, file
