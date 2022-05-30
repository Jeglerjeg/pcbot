import asyncio
import logging
import traceback
from datetime import timezone, datetime
from operator import itemgetter

import aiohttp

from pcbot import Config
from plugins.osulib import enums, api
from plugins.osulib.constants import score_request_limit, cache_user_profiles, osu_config
from plugins.osulib.utils import user_utils


def get_sorted_scores(osu_scores: list, list_type: str):
    """ Sort scores by newest or oldest scores. """
    if list_type == "oldest":
        sorted_scores = sorted(osu_scores, key=itemgetter("created_at"))
    elif list_type == "newest":
        sorted_scores = sorted(osu_scores, key=itemgetter("created_at"), reverse=True)
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
            osu_score["pos"] = i + 1
            del osu_score["beatmapset"]
            del osu_score["user"]
        user_scores = (dict(score_list=fetched_scores, time_updated=timestamp))
    else:
        user_scores = None
    return user_scores


def get_no_choke_scorerank(mods: list, acc: float):
    """ Get the scorerank of an unchoked play. """
    if ("HD" in mods or "FL" in mods) and acc == 1:
        scorerank = "XH"
    elif "HD" in mods or "FL" in mods:
        scorerank = "SH"
    elif acc == 1:
        scorerank = "X"
    else:
        scorerank = "S"
    return scorerank


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
    new_scores = []
    # Compare the scores from top to bottom and try to find a new one
    for i, osu_score in enumerate(fetched_scores["score_list"]):
        if datetime.fromisoformat(osu_tracking[member_id]["scores"]["time_updated"]) <\
                datetime.fromisoformat(osu_score["created_at"]):
            if i == 0:
                logging.info("a #1 score was set: check plugins.osu.osu_tracking['%s']['debug']", member_id)
                osu_tracking[member_id]["debug"] = dict(scores=fetched_scores,
                                                        old_scores=osu_tracking[member_id]["scores"],
                                                        old=dict(osu_tracking[member_id]["old"]),
                                                        new=dict(osu_tracking[member_id]["new"]))

            # Calculate the difference in pp from the score below
            if i < len(fetched_scores["score_list"]) - 2:
                score_pp = float(osu_score["pp"])
                diff = score_pp - float(fetched_scores["score_list"][i + 1]["pp"])
            else:
                diff = 0
            new_scores.append(dict(osu_score, diff=diff))

    # Save the updated score list, and if there are new scores, update time_updated
    osu_tracking[member_id]["scores"]["score_list"] = fetched_scores["score_list"]
    if cache_user_profiles:
        osu_profile_cache.data[member_id]["scores"]["score_list"] = fetched_scores["score_list"]
        await osu_profile_cache.asyncsave()
    if new_scores:
        osu_tracking[member_id]["scores"]["time_updated"] = fetched_scores["time_updated"]
        if cache_user_profiles:
            osu_profile_cache.data[member_id]["scores"]["time_updated"] = fetched_scores["time_updated"]
            await osu_profile_cache.asyncsave()
    return new_scores
