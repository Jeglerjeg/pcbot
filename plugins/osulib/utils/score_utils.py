import asyncio
import copy
import logging
import traceback
from datetime import timezone, datetime
from operator import itemgetter

import aiohttp

from pcbot import Config
from plugins.osulib import enums, api
from plugins.osulib.config import osu_config
from plugins.osulib.constants import score_request_limit, cache_user_profiles
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
    else:
        sorted_scores = osu_scores
    return sorted_scores


async def retrieve_osu_scores(profile: str, mode: enums.GameMode, timestamp: str):
    """ Retrieves"""
    params = {
        "mode": mode.name,
        "limit": score_request_limit,
    }
    fetched_scores = await api.get_user_scores(profile, "best", params=params)
    if fetched_scores is not None:
        for i, osu_score in enumerate(fetched_scores):
            osu_score.add_position(i + 1)
            osu_score.beatmapset = None
            osu_score.user = None
        user_scores = (dict(score_list=fetched_scores, time_updated=timestamp))
    else:
        user_scores = None
    return user_scores


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
    formatted_mods = f"+{enums.Mods.format_mods(osu_score.mods)}"
    great = osu_score.statistics.great
    ok = osu_score.statistics.ok
    miss = osu_score.statistics.miss
    acc = osu_score.accuracy

    if osu_score.mode is enums.GameMode.osu:
        potential_acc = misc_utils.calculate_acc(osu_score.mode, osu_score, exclude_misses=True)
        meh = osu_score.statistics.meh
        args_list = (f"{formatted_mods} {acc:.2%} {potential_acc:.2%}pot {great}x300 {ok}x100 {meh}x50 "
                     f"{miss}m {osu_score.max_combo}x {get_score_object_count(osu_score)}objects").split()
    elif osu_score.mode is enums.GameMode.taiko:
        args_list = (f"{formatted_mods} {acc:.2%} {great}x300 {ok}x100 "
                     f"{miss}m {osu_score.max_combo}x {get_score_object_count(osu_score)}objects").split()
    elif osu_score.mode is enums.GameMode.mania:
        score = osu_score.max_combo
        args_list = f"{formatted_mods} {score}score {get_score_object_count(osu_score)}objects".split()
    else:
        large_tick_hit = osu_score.statistics.large_tick_hit
        small_tick_hit = osu_score.statistics.small_tick_hit
        small_tick_miss = osu_score.statistics.small_tick_miss
        args_list = (f"{formatted_mods} {great}x300 {large_tick_hit}x100 {small_tick_hit}x50 {small_tick_miss}dropmiss "
                     f"{miss}m {osu_score.max_combo}x").split()
    return args_list + process_mod_settings(osu_score)


def process_mod_settings(osu_score: OsuScore):
    """ Adds args for all difficulty adjusting mod settings in a score. """
    args = []
    for mod in osu_score.mods:
        if "settings" not in mod:
            continue
        if mod["acronym"] == "DT" or mod["acronym"] == "NC" or mod["acronym"] == "HT" or mod["acronym"] == "DC":
            if "speed_change" in mod["settings"]:
                args.append(f'{mod["settings"]["speed_change"]}*')
            elif mod["acronym"] == "DT" or mod["acronym"] == "NC":
                args.append("1.5*")
            else:
                args.append("0.75*")
        if mod["acronym"] == "DA":
            if "circle_size" in mod["settings"]:
                args.append(f'cs{mod["settings"]["circle_size"]}')
            if "approach_rate" in mod["settings"]:
                args.append(f'ar{mod["settings"]["approach_rate"]}')
            if "drain_rate" in mod["settings"]:
                args.append(f'hp{mod["settings"]["drain_rate"]}')
            if "overall_difficulty" in mod["settings"]:
                args.append(f'od{mod["settings"]["overall_difficulty"]}')
    return args


def calculate_potential_pp(osu_score: OsuScore, mode: enums.GameMode):
    return mode == enums.GameMode.osu and (not osu_score.legacy_perfect or not osu_score.passed)


def add_score_position(osu_scores: list[OsuScore]):
    for i, osu_score in enumerate(osu_scores):
        osu_score.add_position(i+1)
    return osu_scores


async def get_new_score(member_id: str, osu_tracking: dict, osu_profile_cache: Config):
    """ Compare old user scores with new user scores and return the discovered
    new score if there is any. When a score is returned, it's position in the
    player's top plays can be retrieved with score["pos"]. """
    # Download a list of the user's scores
    profile = osu_config.data["profiles"][member_id]
    mode = user_utils.get_mode(member_id)
    try:
        fetched_scores = await retrieve_osu_scores(profile, mode, datetime.now(tz=timezone.utc).isoformat())
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

    old_score_ids = [osu_score.best_id for osu_score in osu_tracking[member_id]["scores"]["score_list"]]
    new_scores = []
    # Compare the scores from top to bottom and try to find a new one
    for i, osu_score in enumerate(fetched_scores["score_list"]):
        if osu_score.best_id not in old_score_ids:
            if (datetime.now(tz=timezone.utc) - osu_score.ended_at).total_seconds() > 3600*24:
                continue
            if i == 0:
                logging.info("a #1 score was set: check plugins.osu.osu_tracking['%s']['debug']", member_id)
                osu_tracking[member_id]["debug"] = dict(scores=fetched_scores,
                                                        old_scores=osu_tracking[member_id]["scores"],
                                                        old=dict(osu_tracking[member_id]["old"]),
                                                        new=dict(osu_tracking[member_id]["new"]))

            # Calculate the difference in pp from the score below
            if i < len(fetched_scores["score_list"]) - 2:
                score_pp = float(osu_score.pp)
                diff = score_pp - float(fetched_scores["score_list"][i + 1].pp)
            else:
                diff = 0
            osu_score.pp_difference = diff
            new_scores.append(osu_score)

    # Save the updated score list, and if there are new scores, update time_updated
    if new_scores:
        osu_tracking[member_id]["scores"]["time_updated"] = fetched_scores["time_updated"]
        if cache_user_profiles:
            osu_profile_cache.data[member_id]["scores"]["time_updated"] = copy.deepcopy(fetched_scores["time_updated"])
    osu_tracking[member_id]["scores"]["score_list"] = fetched_scores["score_list"]
    if cache_user_profiles:
        osu_profile_cache.data[member_id]["scores"]["score_list"] = copy.deepcopy(fetched_scores["score_list"])
        await misc_utils.save_profile_data(osu_profile_cache)
    return new_scores


def count_score_pages(osu_scores: list[OsuScore], scores_per_page: int):
    return len([osu_scores[i:i+scores_per_page] for i in range(0, len(osu_scores), scores_per_page)])
