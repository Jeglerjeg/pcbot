from datetime import datetime, timezone

from plugins.osulib.db import insert_beatmap, get_beatmap, get_beatmapset, insert_beatmapset
from plugins.osulib.models.beatmap import Beatmap, Beatmapset


def cache_beatmapset(beatmap: dict):
    """ Saves beatmapsets to cache. """

    insert_beatmapset(Beatmapset(beatmap).to_db_query())
    for diff in beatmap["beatmaps"]:
        insert_beatmap(Beatmap(diff).to_db_query())


def retrieve_cache(map_id: int, map_type: str):
    """ Retrieves beatmap or beatmapset cache from memory or file if it exists """
    # Check if cache should be validated for beatmap or beatmapset
    result = None
    if map_type == "set":
        beatmapset = get_beatmapset(map_id)
        if beatmapset:
            result = Beatmapset(beatmapset, from_db=True)
    else:
        beatmap = get_beatmap(map_id)
        if beatmap:
            result = Beatmap(beatmap, from_db=True)
    return result


def validate_cache(beatmap: Beatmap | Beatmapset):
    """ Check if the map cache is still valid. """
    if not beatmap:
        return False
    valid_result = True
    time_now = datetime.now(tz=timezone.utc)
    previous_sr_update = datetime(2021, 8, 5, tzinfo=timezone.utc)
    diff = time_now - beatmap.time_cached
    if beatmap.time_cached < previous_sr_update:
        valid_result = False
    elif beatmap.status == "loved":
        if diff.days > 30:
            valid_result = False
    elif beatmap.status == "pending" or beatmap.status == "graveyard" or beatmap.status == "wip" \
            or beatmap.status == "qualified":
        if diff.days > 7:
            valid_result = False

    return valid_result
