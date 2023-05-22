import asyncio
import logging
import traceback
from datetime import datetime, timezone
from math import ceil

import aiohttp

from plugins.scoresaberlib import db, api
from plugins.scoresaberlib.models.player import ScoreSaberPlayer
from plugins.scoresaberlib.models.score import ScoreSaberScore


def count_score_pages(scoresaber_scores: list[ScoreSaberScore], scores_per_page: int):
    return ceil(len(scoresaber_scores) / scores_per_page)


async def get_new_score(member_id: int, profile: ScoreSaberPlayer):
    """ Compare old user scores with new user scores and return the discovered
    new score if there is any. When a score is returned, it's position in the
    player's top plays can be retrieved with score["pos"]. """
    # Download a list of the user's scores
    try:
        fetched_scores = await api.get_user_scores(profile.id, "top", 100)
    except aiohttp.ServerDisconnectedError:
        return None
    except asyncio.TimeoutError:
        logging.warning("Timed out when retrieving scoresaber! scores from %s (%s)", member_id, profile.id)
        return None
    except ValueError:
        logging.info("Could not retrieve scoresaber! scores from %s (%s)", member_id, profile.id)
        return None
    except Exception:
        logging.error(traceback.format_exc())
        return None
    if fetched_scores is None:
        return None

    new_scores = []
    # Compare the scores from top to bottom and try to find a new one
    for scoresaber_score in fetched_scores:
        if scoresaber_score[0].time_set.timestamp() > profile.last_pp_notification.timestamp():
            new_scores.append(scoresaber_score)

    # Save the updated score list, and if there are new scores, update time_updated
    if new_scores:
        profile.set_time_cached(datetime.now(tz=timezone.utc))
        db.update_scoresaber_user(profile, member_id, profile.ticks)
    return new_scores