import numpy as np
from PIL import Image, ImageDraw, ImageFont

from pcbot import utils
from plugins.osulib.api import respektive_score_rank
from plugins.osulib.card.constants import IMAGE_HEIGHT, IMAGE_WIDTH, TORUS_SEMIBOLD, TORUS_REGULAR
from plugins.osulib.card.helpers import get_rank_tier
from plugins.osulib.models.user import OsuUser, RespektiveScoreRank


async def draw_body(image: Image, user_data: OsuUser, mode: int):
    await draw_ranks(image, user_data, mode)
    draw_stats(image, user_data)
    draw_grades(image, user_data)


def draw_score_rank(score_rank: RespektiveScoreRank):
    header_font_size = 48
    rank_font_size = 96
    tier = get_rank_tier(score_rank.rank)
    colors = tier["colors"]
    header_text = "Score Rank"
    rank_text = f"#{score_rank.rank:,}" if score_rank and score_rank.rank > 0 else "-"

    font_header = ImageFont.truetype(TORUS_SEMIBOLD, header_font_size)
    font_rank = ImageFont.truetype(tier["font_path"], rank_font_size)

    _, _, header_width, _ = font_header.getbbox(header_text)
    _, _, value_width, value_height = font_rank.getbbox(rank_text)

    width = max(header_width, value_width)
    height = 180

    rank_image = Image.new("RGBA", (width, height))
    rank_draw = ImageDraw.Draw(rank_image)

    rank_draw.text((0, 0), header_text, font=font_header, fill="white")

    if len(colors) < 2:
        rank_draw.text((0, 52), rank_text, font=font_rank, fill=colors[0])

        return rank_image

    start_color = colors[0]
    end_color = colors[1]

    gradient = np.linspace(0, 1, value_height)

    gradient_image = Image.new("RGBA", (value_width, value_height))
    gradient_draw = ImageDraw.Draw(gradient_image)

    for j in range(value_height):
        r = int(start_color[0] + (end_color[0] - start_color[0]) * gradient[j])
        g = int(start_color[1] + (end_color[1] - start_color[1]) * gradient[j])
        b = int(start_color[2] + (end_color[2] - start_color[2]) * gradient[j])
        gradient_color = (r, g, b)

        gradient_draw.line([(0, j), (value_width, j)], fill=gradient_color, width=1)

    alpha_image = Image.new("L", (value_width, value_height))
    alpha_draw = ImageDraw.Draw(alpha_image)
    alpha_draw.text((0, 0), rank_text, font=font_rank, fill=255)

    gradient_image.putalpha(alpha_image)
    rank_image.alpha_composite(gradient_image, (0, 52))

    return rank_image


def draw_generic_rank(text: str, rank: int):
    header_font_size = 48
    rank_font_size = 96

    rank_text = f"#{rank:,}" if rank and rank > 0 else "-"

    font_header = ImageFont.truetype(TORUS_SEMIBOLD, header_font_size)
    font_rank = ImageFont.truetype(TORUS_REGULAR, rank_font_size)

    _, _, header_width, _ = font_header.getbbox(text)
    _, _, value_width, _ = font_rank.getbbox(rank_text)

    width = max(header_width, value_width)
    height = 180

    rank_image = Image.new("RGBA", (width, height))
    rank_draw = ImageDraw.Draw(rank_image)

    rank_draw.text((0, 0), text, font=font_header, fill="white")
    rank_draw.text((0, 52), rank_text, font=font_rank, fill="#DBF0E9")

    return rank_image


async def draw_ranks(image: Image, user_data: OsuUser, mode: int):
    score_rank = await respektive_score_rank(user_data.id, mode)
    ranks = [
        draw_score_rank(score_rank),
        draw_generic_rank("Global Rank", user_data.global_rank),
        draw_generic_rank("Country Rank", user_data.country_rank),
    ]

    total_ranks_width = sum(rank.width for rank in ranks)
    num_ranks = len(ranks)
    spacing = (IMAGE_WIDTH - total_ranks_width) // (num_ranks + 1)

    padding = IMAGE_HEIGHT // 30
    y = (IMAGE_HEIGHT // 4) + padding
    x_offset = spacing
    for rank in ranks:
        image.alpha_composite(rank, (x_offset, y))
        x_offset += rank.width + spacing


def draw_stat(header: str, value: float):
    height = 128
    header_font = ImageFont.truetype(TORUS_SEMIBOLD, 44)
    stat_font = ImageFont.truetype(TORUS_REGULAR, 60)

    if header in ("Accuracy", "Completion"):
        stat_text = f"{value}%"
    elif header == "Play Time":
        hours = value // 3600
        minutes = (value % 3600) // 60
        stat_text = f"{hours}h {minutes}m"
    else:
        stat_text = f"{value:,}"

    if not header in ("Ranked Score", "Total Score"):
        _, _, header_width, _ = header_font.getbbox(header)
        _, _, value_width, _ = stat_font.getbbox(stat_text)

        width = max(header_width, value_width)

        stat_image = Image.new("RGBA", (width, height))
        stat_draw = ImageDraw.Draw(stat_image)

        stat_draw.text((0, 0), header, font=header_font, fill="white")
        stat_draw.text((0, 112), stat_text, font=stat_font, fill="#DBF0E9", anchor="ls")

        return stat_image

    numbers = stat_text.split(",")
    score_font_size = 60
    _, _, header_width, _ = header_font.getbbox(header)
    initial_width = max(
        header_width,
        (
                sum(len(number) for number in numbers) * score_font_size
                + (len(numbers) - 1) * score_font_size // 2
        ),
    )
    stat_image = Image.new("RGBA", (initial_width, height))
    stat_draw = ImageDraw.Draw(stat_image)

    stat_draw.text((0, 0), header, font=header_font, fill="white")

    x = 0
    y = 112
    for i, number in enumerate(numbers):
        font = ImageFont.truetype(TORUS_REGULAR, score_font_size)
        _, _, number_width, _ = font.getbbox(number)

        stat_draw.text((x, y), number, font=font, fill="#DBF0E9", anchor="ls")

        comma_width = 0
        if i < len(numbers) - 1:
            _, _, comma_width, _ = font.getbbox(",")
            stat_draw.text(
                (x + number_width, y), ",", font=font, fill="#DBF0E9", anchor="ls"
            )

        score_font_size -= 4

        x += number_width + comma_width

    width = max(header_width, x)
    stat_image = stat_image.crop((0, 0, width, height))

    return stat_image


def draw_stats_row(image: Image, stats: list, y_offset=0):
    total_stats_width = sum(stat.width for stat in stats)
    num_stats = len(stats)
    spacing = (IMAGE_WIDTH - total_stats_width) // (num_stats + 1)

    y = int(IMAGE_HEIGHT / 2.1) + y_offset
    x_offset = spacing
    for stat in stats:
        image.alpha_composite(stat, (x_offset, y))
        x_offset += stat.width + spacing


def draw_stats(image: Image, user_data: OsuUser):
    clears = (user_data.grades.ssh + user_data.grades.ss + user_data.grades.sh + user_data.grades.s
              + user_data.grades.a) if user_data.grades else 0
    row1 = [
        draw_stat("Medals", user_data["medal_count"]),
        draw_stat("pp", utils.format_number(user_data.pp, 0)),
        draw_stat("Play Time", user_data.play_time),
        draw_stat("Play Count", user_data.play_count),
        draw_stat("Accuracy", utils.format_number(user_data.accuracy, 2)),
    ]
    row2 = [
        draw_stat("Ranked Score", user_data.ranked_score),
        draw_stat("Total Score", user_data.total_score),
        draw_stat("Clears", clears)
    ]

    draw_stats_row(image, row1)
    draw_stats_row(image, row2, 144)


def draw_grade(grade: str, count: int):
    grade_image = Image.open(f"plugins/osulib/image_resources/images/grades/{grade}.png").convert("RGBA")
    grade_image.thumbnail((IMAGE_HEIGHT // 8, IMAGE_HEIGHT // 8), Image.Resampling.LANCZOS)
    font = ImageFont.truetype(TORUS_SEMIBOLD, 48)
    padding = 10
    count_text = f"{count:,}"
    _, _, count_width, count_height = font.getbbox(count_text)

    width = max(count_width, grade_image.width)
    height = count_height + grade_image.height + padding

    count_image = Image.new("RGBA", (width, height))
    count_draw = ImageDraw.Draw(count_image)

    count_image.alpha_composite(grade_image, ((width - grade_image.width) // 2, 0))

    x = width // 2
    y = grade_image.height + padding

    count_draw.text((x, y), count_text, font=font, fill="white", anchor="mt")

    return count_image


def draw_grades(image: Image, user_data: OsuUser):
    grades = [
        draw_grade("XH", user_data.grades.ssh if user_data.grades else 0),
        draw_grade("X", user_data.grades.ss if user_data.grades else 0),
        draw_grade("SH", user_data.grades.sh if user_data.grades else 0),
        draw_grade("S", user_data.grades.s if user_data.grades else 0),
        draw_grade("A", user_data.grades.a if user_data.grades else 0),
    ]

    draw_stats_row(image, grades, 320)
