from math import ceil
from operator import itemgetter

from plugins.scoresaberlib.models.leaderboard_info import ScoreSaberLeaderboardInfo
from plugins.scoresaberlib.models.score import ScoreSaberScore

def count_score_pages(osu_scores: list[ScoreSaberScore], scores_per_page: int):
    return ceil(len(osu_scores) / scores_per_page)