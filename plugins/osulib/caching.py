from datetime import datetime, timezone

from plugins.osulib.db import insert_beatmap, get_beatmap, get_beatmapset, insert_beatmapset, delete_beatmap, \
    delete_beatmapset
from plugins.osulib.models.beatmap import Beatmap, Beatmapset


def cache_beatmapset(beatmap: dict):
    """ Saves beatmapsets to cache. """

    insert_beatmapset(Beatmapset(beatmap).to_db_query())
    query_data = []
    for diff in beatmap["beatmaps"]:
        query_data.append(Beatmap(diff).to_db_query())
    insert_beatmap(query_data)


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


def delete_cache(beatmapset: Beatmapset):
    for beatmap in beatmapset.beatmaps:
        delete_beatmap(beatmap.id)
    delete_beatmapset(beatmapset.id)


def validate_cache(beatmap: Beatmap | Beatmapset):
    """ Check if the map cache is still valid. """
    if not beatmap:
        return False
    valid_result = True
    time_now = datetime.now(tz=timezone.utc)
    diff = time_now - beatmap.time_cached
    if beatmap.status == "loved":
        if diff.days > 30:
            valid_result = False
    elif beatmap.status == "pending" or beatmap.status == "graveyard" or beatmap.status == "wip" \
            or beatmap.status == "qualified":
        if diff.days > 7:
            valid_result = False

    return valid_result
