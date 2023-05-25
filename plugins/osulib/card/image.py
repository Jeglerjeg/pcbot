from PIL import Image, ImageDraw
from plugins.osulib.card.constants import IMAGE_HEIGHT, IMAGE_WIDTH
from plugins.osulib.card.background import draw_background
from plugins.osulib.card.header import draw_header
from plugins.osulib.card.body import draw_body
from plugins.osulib.models.user import OsuUser

image = Image.new("RGBA", (IMAGE_WIDTH, IMAGE_HEIGHT), (0, 0, 0, 0))
draw = ImageDraw.Draw(image)


# Card design is using flyte's Player Card design as a base and builds on top of it
# https://www.figma.com/file/ocltATjJqWQZBravhPuqjB/UI%2FPlayer-Card
async def draw_card(user_data: OsuUser, avatar_data: bytes):
    draw_background(draw)
    draw_header(image, draw, user_data, avatar_data)
    await draw_body(image, user_data)

    return image
