from math import ceil
from operator import itemgetter
from bisect import bisect


from plugins.osulib import enums, api
from plugins.osulib.constants import score_request_limit
from plugins.osulib.models.beatmap import Beatmap
from plugins.osulib.models.score import OsuScore, ScoreStatistics
from plugins.osulib.utils import misc_utils


def get_sorted_scores(osu_scores: list[OsuScore], list_type: str):
    """ Sort scores by newest or oldest scores. """
    if list_type == "oldest":
        sorted_scores = sorted(osu_scores, key=itemgetter("ended_at"))
    elif list_type == "newest":
        sorted_scores = sorted(osu_scores, key=itemgetter("ended_at"), reverse=True)
    elif list_type == "acc":
        sorted_scores = sorted(osu_scores, key=itemgetter("accuracy"), reverse=True)
    elif list_type == "combo":
        sorted_scores = sorted(osu_scores, key=itemgetter("max_combo"), reverse=True)
    elif list_type == "score":
        sorted_scores = sorted(osu_scores, key=itemgetter("score"), reverse=True)
    elif list_type == "pp":
        sorted_scores = sorted(osu_scores, key=itemgetter("pp"), reverse=True)
    else:
        sorted_scores = osu_scores
    return sorted_scores


def is_perfect(statistics: ScoreStatistics):
    if statistics.miss > 0 or statistics.large_tick_miss > 0 or statistics.combo_break > 0:
        return False
    return True



def get_maximum_score_combo(osu_score: OsuScore, beatmap: Beatmap):
    if hasattr(osu_score, "maximum_statistics") and osu_score.maximum_statistics:
        combo = osu_score.maximum_statistics.perfect + osu_score.maximum_statistics.great + osu_score.maximum_statistics.large_tick_hit + \
                osu_score.maximum_statistics.legacy_combo_increase + osu_score.maximum_statistics.ignore_hit
        if combo > 0:
            return combo
    return beatmap.max_combo if hasattr(beatmap, "max_combo") and beatmap.max_combo is not None else None


async def retrieve_osu_scores(profile: str, mode: enums.GameMode):
    """ Retrieves"""
    params = {
        "mode": mode.name,
        "limit": score_request_limit,
    }
    fetched_scores = await api.get_user_scores(profile, "best", params=params)
    if fetched_scores is not None:
        for i, osu_score in enumerate(fetched_scores):
            osu_score.add_position(i + 1)
    return fetched_scores


def get_no_choke_scorerank(mods: list, acc: float):
    """ Get the scorerank of an unchoked play. """
    mods = [mod["acronym"] for mod in mods]
    if ("HD" in mods or "FL" in mods) and acc == 1:
        scorerank = "XH"
    elif "HD" in mods or "FL" in mods:
        scorerank = "SH"
    elif acc == 1:
        scorerank = "X"
    else:
        scorerank = "S"
    return scorerank


def get_score_object_count(osu_score: OsuScore):
    perfect = osu_score.statistics.perfect
    great = osu_score.statistics.great
    good = osu_score.statistics.good
    ok = osu_score.statistics.ok
    meh = osu_score.statistics.meh
    miss = osu_score.statistics.miss
    if osu_score.mode is enums.GameMode.osu:
        objects = great + ok + meh + miss
    elif osu_score.mode is enums.GameMode.taiko:
        objects = great + ok + miss
    elif osu_score.mode is enums.GameMode.mania:
        objects = perfect + great + good + ok + meh + miss
    else:
        objects = 0
    return objects


def process_score_args(osu_score: OsuScore):
    great = osu_score.statistics.great
    ok = osu_score.statistics.ok
    miss = osu_score.statistics.miss
    acc = osu_score.accuracy
    meh = osu_score.statistics.meh

    if osu_score.mode is enums.GameMode.osu:
        potential_acc = misc_utils.calculate_acc(osu_score.mode, osu_score, exclude_misses=True)
        args_list = (f"{acc:.2%} {potential_acc:.2%}pot {great}x300 {ok}x100 {meh}x50 "
                     f"{miss}m {osu_score.max_combo}x {get_score_object_count(osu_score)}objects "
                     f"{osu_score.statistics.large_tick_hit}xlargetick "
                     f"{osu_score.statistics.small_tick_hit}xsmalltick "
                     f"{osu_score.statistics.slider_tail_hit}xsliderend").split()
    elif osu_score.mode is enums.GameMode.taiko:
        args_list = (f"{acc:.2%} {great}x300 {ok}x100 "
                     f"{miss}m {osu_score.max_combo}x {get_score_object_count(osu_score)}objects").split()
    elif osu_score.mode is enums.GameMode.mania:
        args_list = f"{osu_score.statistics.perfect}xgeki {great}x300 " \
                    f"{osu_score.statistics.good}xkatu {ok}x100 {meh}x50 " \
                    f"{miss}m {get_score_object_count(osu_score)}objects".split()
    else:
        large_tick_hit = osu_score.statistics.large_tick_hit
        small_tick_hit = osu_score.statistics.small_tick_hit
        small_tick_miss = osu_score.statistics.small_tick_miss
        args_list = (f"{great}x300 {large_tick_hit}x100 {small_tick_hit}x50 {small_tick_miss}xkatu "
                     f"{miss}m {osu_score.max_combo}x").split()
    return args_list


def calculate_potential_pp(osu_score: OsuScore, mode: enums.GameMode):
    return mode == enums.GameMode.osu and (not osu_score.legacy_perfect or not osu_score.passed)


def add_score_position(osu_scores: list[OsuScore]):
    for i, osu_score in enumerate(osu_scores):
        osu_score.add_position(i + 1)
    return osu_scores

def find_score_position(osu_score: OsuScore, osu_scores: list[OsuScore]):
    found_index = None
    for i, api_score in enumerate(osu_scores):
        if osu_score.id == api_score.id:
            found_index = i + 1
            break
    if not found_index:
        osu_scores.append(osu_score)
        sorted_scores = get_sorted_scores(osu_scores, "pp")
        found_index = sorted_scores.index(osu_score) + 1
    return found_index



def count_score_pages(osu_scores: list[OsuScore], scores_per_page: int):
    return ceil(len(osu_scores) / scores_per_page)
