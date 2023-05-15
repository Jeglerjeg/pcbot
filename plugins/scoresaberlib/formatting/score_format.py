import discord

from pcbot import utils
from plugins.scoresaberlib.models.leaderboard_info import ScoreSaberLeaderboardInfo
from plugins.scoresaberlib.models.score import ScoreSaberScore
from plugins.scoresaberlib.utils import map_utils
from plugins.scoresaberlib.formatting import map_format


class PaginatedScoreList(discord.ui.View):
    def __init__(self, osu_scores: list[(ScoreSaberScore, ScoreSaberLeaderboardInfo)], max_pages: int, embed: discord.Embed):
        super().__init__(timeout=30)
        self.osu_scores = osu_scores
        self.page = 1
        self.offset = 0
        self.max_pages = max_pages
        self.embed = embed

    async def update_message(self, message: discord.Message):
        embed = message.embeds[0]
        embed.description = await get_formatted_score_list(self.osu_scores, 5, offset=self.offset)
        embed.set_footer(text=f"Page {self.page} of {self.max_pages}")
        self.embed = embed
        await message.edit(embed=embed)

    @discord.ui.button(label="<", style=discord.ButtonStyle.blurple)
    async def last_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if self.page == 1:
            self.page = self.max_pages
            self.offset = (self.max_pages - 1) * 5
        else:
            self.page -= 1
            self.offset -= 5
        await self.update_message(interaction.message)

    @discord.ui.button(label=">", style=discord.ButtonStyle.blurple)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if self.page == self.max_pages:
            self.page = 1
            self.offset = 0
        else:
            self.page += 1
            self.offset += 5
        await self.update_message(interaction.message)

    @discord.ui.button(label="⭯", style=discord.ButtonStyle.blurple)
    async def reset(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.page = 1
        self.offset = 0
        await self.update_message(interaction.message)


def format_score_statistics(scoresaber_score: ScoreSaberScore, leaderboard_info: ScoreSaberLeaderboardInfo):
    """" Returns formatted score statistics for each mode. """
    acc = f"{utils.format_number(100 * (scoresaber_score.base_score / leaderboard_info.max_score), 2)}%"
    color = "\u001b[0;32m" if scoresaber_score.full_combo else "\u001b[0;31m"
    return "acc    bad  miss  combo\n" \
           f'{color}{acc:<7}{scoresaber_score.bad_cuts:<5}{scoresaber_score.missed_notes:<6}{scoresaber_score.max_combo}'


def format_score_info(scoresaber_score: ScoreSaberScore, leaderboard_info: ScoreSaberLeaderboardInfo):
    """ Return formatted beatmap information. """
    beatmap_url = map_utils.get_map_url(leaderboard_info.id)
    grade = format_score_rank(100 * (scoresaber_score.base_score / leaderboard_info.max_score))
    difficulty = map_format.format_beatmap_difficulty(leaderboard_info.difficulty.difficulty)
    modslist = scoresaber_score.modifiers if scoresaber_score.modifiers else "Nomod"
    score_pp = utils.format_number(scoresaber_score.pp, 2)
    ranked_score = f'{scoresaber_score.modified_score:,}'
    stars = utils.format_number(float(leaderboard_info.stars), 2)
    artist = leaderboard_info.song_author_name
    title = leaderboard_info.song_name
    i = ("*" if "*" not in leaderboard_info.song_author_name + leaderboard_info.song_name else "")
    return f'[{i}{artist} - {title} [{difficulty}]{i}]({beatmap_url})\n' \
           f'**{score_pp}pp {stars}\u2605, {grade} +{modslist} {ranked_score}**'

def format_new_score(scoresaber_score: ScoreSaberScore, leaderboard_info: ScoreSaberLeaderboardInfo):
    """ Format any score. There should be a member name/mention in front of this string. """
    return (
        f"{format_score_info(scoresaber_score, leaderboard_info)}"
        "```ansi\n"
        f"{format_score_statistics(scoresaber_score, leaderboard_info)}```"
        f"<t:{int(scoresaber_score.time_set.timestamp())}:R>"
    )

def format_score_rank(accuracy: float):
    grade = ""
    if accuracy >= 90.0:
        grade = "SS"
    elif accuracy >= 80.0:
        grade = "S"
    elif accuracy >= 65.0:
        grade = "A"
    elif accuracy >= 50.0:
        grade = "B"
    elif accuracy >= 35.0:
        grade = "C"
    elif accuracy >= 20.0:
        grade = "D"
    else:
        grade = "E"
    return grade

async def get_formatted_score_list(scoresaber_scores: list[(ScoreSaberScore, ScoreSaberLeaderboardInfo)], limit: int, offset: int = 0):
    """ Return a list of formatted scores along with time since the score was set. """
    m = []
    for i, scoresaber_score in enumerate(scoresaber_scores):
        if i < offset:
            continue
        if i > (limit + offset) - 1:
            break

        score = scoresaber_score[0]
        scoresaber_map = scoresaber_score[1]

        # Add score position to the score
        m.append("".join([f"{score.position}.\n", f"{format_new_score(score, scoresaber_map)}\n",
                          "\n" if not i == limit - 1 else ""]))
    return "".join(m)