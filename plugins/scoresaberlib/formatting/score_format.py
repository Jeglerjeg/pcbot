from pcbot import utils
from plugins.scoresaberlib.models.leaderboard_info import ScoreSaberLeaderboardInfo
from plugins.scoresaberlib.models.score import ScoreSaberScore
from plugins.scoresaberlib.utils import map_utils
from plugins.scoresaberlib.formatting import map_format


def format_score_statistics(scoresaber_score: ScoreSaberScore, leaderboard_info: ScoreSaberLeaderboardInfo):
    """" Returns formatted score statistics for each mode. """
    acc = f"{utils.format_number(100 * (scoresaber_score.modified_score / leaderboard_info.max_score), 2)}%"
    color = "\u001b[0;32m" if scoresaber_score.full_combo else "\u001b[0;31m"
    return "acc    bad  miss  combo\n" \
           f'{color}{acc:<7}{scoresaber_score.bad_cuts:<5}{scoresaber_score.missed_notes:<6}{scoresaber_score.max_combo}'


def format_score_info(scoresaber_score: ScoreSaberScore, leaderboard_info: ScoreSaberLeaderboardInfo):
    """ Return formatted beatmap information. """
    beatmap_url = map_utils.get_map_url(leaderboard_info.id)
    difficulty = map_format.format_beatmap_difficulty(leaderboard_info.difficulty.difficulty)
    modslist = scoresaber_score.modifiers if scoresaber_score.modifiers else "Nomod"
    score_pp = utils.format_number(scoresaber_score.pp, 2)
    ranked_score = f'{scoresaber_score.modified_score:,}'
    stars = utils.format_number(float(leaderboard_info.stars), 2)
    artist = leaderboard_info.song_author_name
    title = leaderboard_info.song_name
    i = ("*" if "*" not in leaderboard_info.song_author_name + leaderboard_info.song_name else "")
    return f'[{i}{artist} - {title} [{difficulty}]{i}]({beatmap_url})\n' \
           f'**{score_pp}pp {stars}\u2605, +{modslist} {ranked_score}**'

def format_new_score(scoresaber_score: ScoreSaberScore, leaderboard_info: ScoreSaberLeaderboardInfo):
    """ Format any score. There should be a member name/mention in front of this string. """
    return (
        f"{format_score_info(scoresaber_score, leaderboard_info)}"
        "```ansi\n"
        f"{format_score_statistics(scoresaber_score, leaderboard_info)}```"
    )