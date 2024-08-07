import asyncio
import logging
import traceback
from math import ceil
from datetime import datetime, timezone
from operator import itemgetter

import aiohttp

from plugins.osulib import enums, api, db
from plugins.osulib.constants import score_request_limit
from plugins.osulib.models.beatmap import Beatmap
from plugins.osulib.models.score import OsuScore
from plugins.osulib.utils import user_utils, misc_utils


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
                     f"{miss}m {osu_score.max_combo}x {get_score_object_count(osu_score)}objects").split()
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


async def get_new_score(member_id: str):
    """ Compare old user scores with new user scores and return the discovered
    new score if there is any. When a score is returned, it's position in the
    player's top plays can be retrieved with score["pos"]. """
    # Download a list of the user's scores
    profile = db.get_linked_osu_profile(int(member_id)).osu_id
    mode = user_utils.get_mode(member_id)
    try:
        fetched_scores = await retrieve_osu_scores(profile, mode)
    except aiohttp.ServerDisconnectedError:
        return None
    except asyncio.TimeoutError:
        logging.warning("Timed out when retrieving osu! scores from %s (%s)", member_id, profile)
        return None
    except ValueError:
        logging.info("Could not retrieve osu! scores from %s (%s)", member_id, profile)
        return None
    except Exception:
        logging.error(traceback.format_exc())
        return None
    if fetched_scores is None:
        return None

    recent_notifications = db.get_recent_events(int(member_id))

    new_scores = []
    # Compare the scores from top to bottom and try to find a new one
    for i, osu_score in enumerate(fetched_scores):
        if osu_score.ended_at.timestamp() > float(recent_notifications.last_pp_notification):
            # If the score is older than 3 hours, don't notify it
            if (datetime.now(tz=timezone.utc) - osu_score.ended_at).total_seconds() > 3600 * 3:
                continue
            # Calculate the difference in pp from the score below
            if i < len(fetched_scores) - 2:
                score_pp = float(osu_score.pp)
                diff = score_pp - float(fetched_scores[i + 1].pp)
            else:
                diff = 0
            osu_score.pp_difference = diff
            new_scores.append(osu_score)

    # Save the updated score list, and if there are new scores, update time_updated
    if new_scores:
        db.update_recent_events(int(member_id), recent_notifications, pp=True)
    return new_scores


def count_score_pages(osu_scores: list[OsuScore], scores_per_page: int):
    return ceil(len(osu_scores) / scores_per_page)
