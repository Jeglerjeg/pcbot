import logging
from datetime import datetime

import discord

from pcbot import utils
from plugins.osulib import pp, enums, api
from plugins.osulib.formatting import misc_format
from plugins.osulib.utils import beatmap_utils, score_utils

try:
    import pendulum
except ImportError:
    pendulum = None


class PaginatedScoreList(discord.ui.View):
    def __init__(self, osu_scores: list, mode: enums.GameMode, pages: int, embed: discord.Embed, nochoke: bool = False):
        super().__init__(timeout=30)
        self.osu_scores = osu_scores
        self.page = 1
        self.offset = 0
        self.mode = mode
        self.pages = pages
        self.embed = embed
        self.nochoke = nochoke

    async def update_message(self, message: discord.Message):
        embed = message.embeds[0]
        embed.description = await get_formatted_score_list(self.mode, self.osu_scores, 5, offset=self.offset,
                                                           nochoke=self.nochoke)
        embed.set_footer(text=f"Page {self.page} of {self.pages}")
        self.embed = embed
        await message.edit(embed=embed)

    @discord.ui.button(label="<", style=discord.ButtonStyle.blurple)
    async def last_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if self.page == 1:
            return
        self.page -= 1
        self.offset -= 5
        await self.update_message(interaction.message)

    @discord.ui.button(label=">", style=discord.ButtonStyle.blurple)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if self.page == self.pages:
            return
        self.page += 1
        self.offset += 5
        await self.update_message(interaction.message)

    @discord.ui.button(label="⭯", style=discord.ButtonStyle.blurple)
    async def reset(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.page = 1
        self.offset = 0
        await self.update_message(interaction.message)


def format_potential_pp(score_pp: pp.PPStats, osu_score: dict):
    """ Formats potential PP for scores. """
    if score_pp is not None and score_pp.max_pp is not None and (osu_score["pp"] / score_pp.max_pp) * 100 < 99\
            and not osu_score["legacy_perfect"]:
        potential_string = f"Potential: {utils.format_number(score_pp.max_pp, 2):,}pp, " \
                           f"{utils.format_number(score_pp.max_pp - osu_score['pp'], 2):+}pp"
    else:
        potential_string = None
    return potential_string


def get_formatted_score_time(osu_score: dict):
    """ Returns formatted time since score was set. """
    time_string = ""
    if pendulum:
        score_time = pendulum.now("UTC").diff(pendulum.parse(osu_score["ended_at"]))
        if score_time.in_seconds() < 60:
            time_string = f"""{"".join([str(score_time.in_seconds()),
                                        (" seconds" if score_time.in_seconds() > 1 else " second")])} ago"""
        elif score_time.in_minutes() < 60:
            time_string = f"""{"".join([str(score_time.in_minutes()),
                                        (" minutes" if score_time.in_minutes() > 1 else " minute")])} ago"""
        elif score_time.in_hours() < 24:
            time_string = f"""{"".join([str(score_time.in_hours()),
                                        (" hours" if score_time.in_hours() > 1 else " hour")])} ago"""
        elif score_time.in_days() <= 31:
            time_string = f"""{"".join([str(score_time.in_days()),
                                        (" days" if score_time.in_days() > 1 else " day")])} ago"""
        elif score_time.in_months() < 12:
            time_string = f"""{"".join([str(score_time.in_months()),
                                        (" months" if score_time.in_months() > 1 else " month")])} ago"""
        else:
            time_string = f"""{"".join([str(score_time.in_years()),
                                        (" years" if score_time.in_years() > 1 else " year")])} ago"""

    return time_string


def format_score_statistics(osu_score: dict, beatmap: dict, mode: enums.GameMode):
    """" Returns formatted score statistics for each mode. """
    sign = "!" if osu_score["accuracy"] == 1 else ("+" if osu_score["legacy_perfect"] and osu_score["passed"] else "-")
    acc = f"{utils.format_number(osu_score['accuracy'] * 100, 2)}%"
    perfect = osu_score["statistics"]["perfect"]
    great = osu_score["statistics"]["great"]
    good = osu_score["statistics"]["good"]
    ok = osu_score["statistics"]["ok"]
    meh = osu_score["statistics"]["meh"]
    miss = osu_score["statistics"]["miss"]
    large_tick_hit = osu_score["statistics"]["large_tick_hit"]
    large_tick_miss = osu_score["statistics"]["large_tick_miss"]
    small_tick_miss = osu_score["statistics"]["small_tick_miss"]
    maxcombo = osu_score["max_combo"]
    max_combo = f"/{beatmap['max_combo']}" if "max_combo" in beatmap and beatmap["max_combo"] is not None else ""
    if mode is enums.GameMode.osu:
        return "  acc     300s  100s  50s  miss  combo\n" \
              f'{sign} {acc:<8}{great:<6}{ok:<6}{meh:<5}{miss:<6}{maxcombo}{max_combo}'
    if mode is enums.GameMode.taiko:
        return "  acc     great  good  miss  combo\n" \
              f"{sign} {acc:<8}{great:<7}{ok:<6}{miss:<6}{maxcombo}{max_combo}"
    if mode is enums.GameMode.mania:
        return "  acc     max   300s  200s  100s  50s  miss\n" \
              f"{sign} {acc:<8}{perfect:<6}{great:<6}{good:<6}{ok:<6}{meh:<5}{miss:<6}"
    return "  acc     fruits ticks drpmiss miss combo\n" \
           f"{sign} {acc:<8}{great:<7}{large_tick_hit:<6}{small_tick_miss:<8}{miss+large_tick_miss:<5}{maxcombo}" \
           f"{max_combo}"


def format_score_info(osu_score: dict, beatmap: dict, rank: int = None):
    """ Return formatted beatmap information. """
    beatmap_url = beatmap_utils.get_beatmap_url(osu_score["beatmap"]["id"], enums.GameMode(osu_score["ruleset_id"]))
    modslist = enums.Mods.format_mods(osu_score["mods"])
    score_pp = utils.format_number(osu_score["pp"], 2) if "new_pp" not in osu_score else osu_score["new_pp"]
    ranked_score = f'{osu_score["total_score"]:,}' if "total_score" in osu_score else ""
    stars = utils.format_number(float(beatmap["difficulty_rating"]), 2)
    scoreboard_rank = f"#{rank} " if rank else ""
    failed = "(Failed) " if osu_score["passed"] is False and osu_score["rank"] != "F" else ""
    artist = osu_score["beatmapset"]["artist"].replace("_", r"\_") if bool("beatmapset" in osu_score) else \
        beatmap["beatmapset"]["artist"].replace("_", r"\_")
    title = osu_score["beatmapset"]["title"].replace("_", r"\_") if bool("beatmapset" in osu_score) else \
        beatmap["beatmapset"]["title"].replace("_", r"\_")
    i = ("*" if "*" not in osu_score["beatmapset"]["artist"] + osu_score["beatmapset"]["title"] else "") if \
        bool("beatmapset" in osu_score) else \
        ("*" if "*" not in beatmap["beatmapset"]["artist"] + beatmap["beatmapset"]["title"] else "")
    return f'[{i}{artist} - {title} [{beatmap["version"]}]{i}]({beatmap_url})\n' \
           f'**{score_pp}pp {stars}\u2605, {osu_score["rank"]} {scoreboard_rank}{failed}+{modslist} {ranked_score}**'


async def format_new_score(mode: enums.GameMode, osu_score: dict, beatmap: dict, rank: int = None,
                           member: discord.Member = None):
    """ Format any score. There should be a member name/mention in front of this string. """
    return (
        f"{format_score_info(osu_score, beatmap, rank)}"
        "```diff\n"
        f"{format_score_statistics(osu_score, beatmap, mode)}```"
        f"{await misc_format.format_stream(member, osu_score, beatmap) if member else ''}"
    )


async def format_minimal_score(osu_score: dict, beatmap: dict, rank: int, member: discord.Member):
    """ Format any osu! score with minimal content.
    There should be a member name/mention in front of this string. """
    return (
        "[*{artist} - {title} [{version}]*]({url})\n"
        "**{pp}pp {stars}\u2605, {maxcombo}{max_combo} {rank} {acc} {scoreboard_rank}+{mods}**"
        "{live}"
    ).format(
        url=beatmap_utils.get_beatmap_url(osu_score["beatmap"]["id"], enums.GameMode(osu_score["ruleset_id"])),
        mods=enums.Mods.format_mods(osu_score["mods"]),
        acc=f"{utils.format_number(osu_score['accuracy'] * 100, 2)}%",
        artist=beatmap["beatmapset"]["artist"].replace("*", r"\*").replace("_", r"\_"),
        title=beatmap["beatmapset"]["title"].replace("*", r"\*").replace("_", r"\_"),
        version=beatmap["version"],
        maxcombo=osu_score["max_combo"],
        max_combo=f"/{beatmap['max_combo']}" if "max_combo" in beatmap and beatmap["max_combo"] is not None
        else "",
        rank=osu_score["rank"],
        stars=utils.format_number(float(beatmap["difficulty_rating"]), 2),
        scoreboard_rank=f"#{rank} " if rank else "",
        live=await misc_format.format_stream(member, osu_score, beatmap),
        pp=utils.format_number(osu_score["pp"], 2)
    )


def format_completion_rate(osu_score: dict, pp_stats: pp.PPStats):
    completion_rate = ""
    if osu_score and pp_stats and osu_score["passed"] is False \
            and enums.GameMode(osu_score["ruleset_id"]) is not enums.GameMode.fruits:
        beatmap_objects = (osu_score["beatmap"]["count_circles"] + osu_score["beatmap"]["count_sliders"] +
                           osu_score["beatmap"]["count_spinners"])
        objects = score_utils.get_score_object_count(osu_score)
        completion_rate = f"Completion rate: {(objects / beatmap_objects) * 100:.2f}% " \
                          f"({utils.format_number(pp_stats.partial_stars, 2)}\u2605)"
    return completion_rate


async def get_formatted_score_list(mode: enums.GameMode, osu_scores: list, limit: int, no_time: bool = False,
                                   offset: int = 0, nochoke: bool = False):
    """ Return a list of formatted scores along with time since the score was set. """
    m = []
    for i, osu_score in enumerate(osu_scores):
        if i < offset:
            continue
        if i > (limit + offset) - 1:
            break
        params = {
            "beatmap_id": osu_score["beatmap"]["id"]
        }
        mods = enums.Mods.format_mods(osu_score["mods"])
        beatmap = (await api.beatmap_lookup(params=params, map_id=osu_score["beatmap"]["id"], mode=mode.name))
        if not nochoke:
            score_pp = await pp.get_score_pp(osu_score, mode, beatmap)
            if score_pp is not None:
                beatmap["difficulty_rating"] = pp.get_beatmap_sr(score_pp, beatmap, mods)
            if ("max_combo" not in beatmap or not beatmap["max_combo"]) and score_pp and score_pp.max_combo:
                beatmap["max_combo"] = score_pp.max_combo
            # Add potential pp to the score
            potential_string = format_potential_pp(score_pp, osu_score)
        else:
            beatmap["difficulty_rating"] = osu_score["beatmap"]["difficulty_rating"]
            beatmap["max_combo"] = osu_score["max_combo"]
            potential_string = ""

        # Add time since play to the score
        score_datetime = datetime.fromisoformat(osu_score["ended_at"])
        time_since_string = f"<t:{int(score_datetime.timestamp())}:R>"

        # Add score position to the score
        pos = f"{osu_score['pos']}." if "diff" not in osu_score else \
            f"{osu_score['pos']}. ({utils.format_number(osu_score['diff'], 2):+}pp)"

        m.append("".join([f"{pos}\n", await format_new_score(mode, osu_score, beatmap),
                          ("".join([potential_string, "\n"]) if potential_string is not None else ""),
                          "".join([time_since_string, "\n"]) if not no_time else "",
                          "\n" if not i == limit - 1 else ""]))
    return "".join(m)
