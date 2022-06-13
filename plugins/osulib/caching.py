import json
import os
from datetime import datetime

mapcache_path = "plugins/osulib/mapdatacache"
setcache_path = "plugins/osulib/setdatacache"


def cache_beatmapset(beatmap: dict, map_id: int):
    """ Saves beatmapsets to cache. """
    beatmapset_path = os.path.join(setcache_path, str(map_id) + ".json")

    if not os.path.exists(setcache_path):
        os.makedirs(setcache_path)

    if not os.path.exists(mapcache_path):
        os.makedirs(mapcache_path)

    beatmapset = beatmap.copy()
    beatmap["time_cached"] = datetime.utcnow().isoformat()
    with open(beatmapset_path, "w", encoding="utf-8") as file:
        json.dump(beatmap, file)
    del beatmapset["beatmaps"]
    del beatmapset["converts"]
    for diff in beatmap["beatmaps"]:
        beatmap_path = os.path.join(mapcache_path, str(diff["id"]) + "-" + str(diff["mode"]) + ".json")
        diff["time_cached"] = datetime.utcnow().isoformat()
        diff["beatmapset"] = beatmapset
        with open(beatmap_path, "w", encoding="utf-8") as f:
            json.dump(diff, f)
    if beatmap["converts"]:
        for convert in beatmap["converts"]:
            convert_path = os.path.join(mapcache_path, str(convert["id"]) + "-" + str(convert["mode"]) + ".json")
            convert["time_cached"] = datetime.utcnow().isoformat()
            convert["beatmapset"] = beatmapset
            with open(convert_path, "w", encoding="utf-8") as fp:
                json.dump(convert, fp)


def retrieve_cache(map_id: int, map_type: str, mode: str = None):
    """ Retrieves beatmap or beatmapset cache from memory or file if it exists """
    # Check if cache should be validated for beatmap or beatmapset
    result = None
    if map_type == "set":
        if not os.path.exists(setcache_path):
            os.makedirs(setcache_path)
        beatmap_path = os.path.join(setcache_path, str(map_id) + ".json")
    else:
        if not os.path.exists(mapcache_path):
            os.makedirs(mapcache_path)
        beatmap_path = os.path.join(mapcache_path, str(map_id) + "-" + mode + ".json")
    if os.path.isfile(beatmap_path):
        with open(beatmap_path, encoding="utf-8") as fp:
            result = json.load(fp)
    return result


def validate_cache(beatmap: dict):
    """ Check if the map cache is still valid. """
    if beatmap is None:
        return False
    valid_result = True
    cached_time = datetime.fromisoformat(beatmap["time_cached"])
    time_now = datetime.utcnow()
    previous_sr_update = datetime(2021, 8, 5)
    diff = time_now - cached_time
    if cached_time < previous_sr_update:
        valid_result = False
    elif beatmap["status"] == "loved":
        if diff.days > 30:
            valid_result = False
    elif beatmap["status"] == "pending" or beatmap["status"] == "graveyard" or beatmap["status"] == "wip" \
            or beatmap["status"] == "qualified":
        if diff.days > 7:
            valid_result = False

    return valid_result
