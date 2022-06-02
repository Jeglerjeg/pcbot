""" API integration for osu!

    Adds Mods enums with raw value calculations and some
    request functions.
"""
import asyncio
import json
import logging
import os
import re
from collections import namedtuple
from datetime import datetime, timezone, timedelta

from pcbot import utils
from plugins.osulib import enums

api_url = "https://osu.ppy.sh/api/v2/"
access_token = ""
expires = datetime.now(tz=timezone.utc)
requests_sent = 0

mapcache_path = "plugins/osulib/mapdatacache"
setcache_path = "plugins/osulib/setdatacache"

replay_path = os.path.join("plugins/osulib/", "replay.osr")


async def refresh_access_token(client_id, client_secret):
    await asyncio.sleep((expires - datetime.now(tz=timezone.utc)).total_seconds())
    await get_access_token(client_id, client_secret)
    await refresh_access_token(client_id, client_secret)


async def get_access_token(client_id: str, client_secret: str):
    """ Retrieves access token from API and refreshes token after it expires. """
    params = {
        "grant_type": "client_credentials",
        "client_id": int(client_id),
        "client_secret": client_secret,
        "scope": "public"
    }

    result = await utils.post_request("https://osu.ppy.sh/oauth/token", call=utils.convert_to_json, data=params)
    global requests_sent
    requests_sent += 1
    global access_token
    access_token = result["access_token"]
    dt = datetime.now(tz=timezone.utc)
    td = timedelta(seconds=result["expires_in"])
    global expires
    expires = dt + td


def def_section(api_name: str, first_element: bool = False):
    """ Add a section using a template to simplify adding API functions. """

    async def template(url=api_url, request_tries: int = 1, **params):
        if not access_token:
            return None
        global requests_sent

        # Add the API key
        headers = {
            "Authorization": "Bearer " + access_token
        }

        # Download using a URL of the given API function name
        for i in range(request_tries):
            try:
                response = await utils.download_json(url + api_name, headers=headers, **params)

            except ValueError as e:
                logging.warning("ValueError Calling %s: %s", url + api_name, e)
            else:
                requests_sent += 1

                if response is not None:
                    break
        else:
            return None

        # Unless we want to extract the first element, return the entire object (usually a list)
        if not first_element:
            return response

        # If the returned value should be the first element, see if we can cut it
        return response[0] if len(response) > 0 else None

    # Set the correct name of the function and add simple docstring
    template.__name__ = api_name
    template.__doc__ = "Get " + ("list" if not first_element else "dict") + " using " + api_url + api_name
    return template


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


# Define all osu! API requests using the template
async def beatmap_lookup(params, map_id, mode):
    """ Looks up a beatmap unless cache exists"""
    result = retrieve_cache(map_id, "map", mode)
    valid_result = validate_cache(result)
    if not valid_result:
        await beatmapset_lookup(params=params)
        result = retrieve_cache(map_id, "map", mode)
    return result


async def beatmapset_lookup(params):
    """ Looks up a beatmapset using a beatmap ID"""
    request = def_section("beatmapsets/lookup")
    result = await request(**params)
    cache_beatmapset(result, result["id"])
    return result


async def get_user(user, mode=None, params=None):
    """ Return a user from the API"""
    if mode:
        request = def_section(f"users/{user}/{mode}")
    else:
        request = def_section(f"users/{user}")
    if params:
        return await request(**params)

    return await request()


async def get_user_scores(user_id, score_type, params=None):
    """ Returns a user's best, recent or #1 scores. """
    request = def_section(f"users/{user_id}/scores/{score_type}")
    if params:
        return await request(**params)

    return await request("")


async def get_user_beatmap_score(beatmap_id, user_id, params=None):
    """ Returns a user's score on a beatmap. """
    request = def_section(f"beatmaps/{beatmap_id}/scores/users/{user_id}")
    if params:
        result = await request(**params)
    else:
        result = await request()
    if "{'error': None}" in str(result):
        result = None
    return result


async def get_user_beatmap_scores(beatmap_id, user_id, params=None):
    """ Returns all of a user's scores on a beatmap. """
    request = def_section(f"beatmaps/{beatmap_id}/scores/users/{user_id}/all")
    if params:
        result = await request(**params)
    else:
        result = await request()
    if "{'error': None}" in str(result):
        result = None
    return result


async def get_beatmapset(beatmapset_id, force_redownload: bool = False):
    """ Returns a beatmapset using beatmapset ID"""
    result = retrieve_cache(beatmapset_id, "set")
    valid_result = validate_cache(result)
    if not valid_result or force_redownload:
        request = def_section(f"beatmapsets/{beatmapset_id}")
        result = await request()
        cache_beatmapset(result, result["id"])
    else:
        beatmapset_path = os.path.join(setcache_path, str(beatmapset_id) + ".json")
        with open(beatmapset_path, encoding="utf-8") as fp:
            result = json.load(fp)
    return result


async def get_user_recent_activity(user, params=None):
    """ Return a user's recent activity. """
    request = def_section(f"users/{user}/recent_activity")
    if params:
        return await request(**params)
    return await request()


beatmap_url_pattern_v1 = re.compile(r"https?://(osu|old)\.ppy\.sh/(?P<type>[bs])/(?P<id>\d+)(?:\?m=(?P<mode>\d))?")
beatmapset_url_pattern_v2 = \
    re.compile(r"https?://osu\.ppy\.sh/beatmapsets/(?P<beatmapset_id>\d+)/?(?:#(?P<mode>\w+)/(?P<beatmap_id>\d+))?")
beatmap_url_pattern_v2 = re.compile(r"https?://osu\.ppy\.sh/beatmaps/(?P<beatmap_id>\d+)(?:\?mode=(?P<mode>\w+))?")

BeatmapURLInfo = namedtuple("BeatmapURLInfo", "beatmapset_id beatmap_id gamemode")


def parse_beatmap_url(url: str):
    """ Parse the beatmap url and return either a BeatmapURLInfo.
    For V1, only one parameter of either beatmap_id or beatmapset_id will be set.
    For V2, only beatmapset_id will be set, or all arguments are set.

    :raise SyntaxError: The URL is neither a v1 or v2 osu! url.
    """
    match_v1 = beatmap_url_pattern_v1.match(url)
    if match_v1:
        # There might be some gamemode info in the url
        mode = None
        if match_v1.group("mode") is not None:
            mode = enums.GameMode(int(match_v1.group("mode")))

        if match_v1.group("type") == "b":
            return BeatmapURLInfo(beatmapset_id=None, beatmap_id=match_v1.group("id"), gamemode=mode)

        return BeatmapURLInfo(beatmapset_id=match_v1.group("id"), beatmap_id=None, gamemode=mode)

    match_v2_beatmapset = beatmapset_url_pattern_v2.match(url)
    if match_v2_beatmapset:
        if match_v2_beatmapset.group("mode") is None:
            return BeatmapURLInfo(beatmapset_id=match_v2_beatmapset.group("beatmapset_id"), beatmap_id=None,
                                  gamemode=None)
        return BeatmapURLInfo(beatmapset_id=match_v2_beatmapset.group("beatmapset_id"),
                              beatmap_id=match_v2_beatmapset.group("beatmap_id"),
                              gamemode=enums.GameMode.get_mode(match_v2_beatmapset.group("mode")))

    match_v2_beatmap = beatmap_url_pattern_v2.match(url)
    if match_v2_beatmap:
        if match_v2_beatmap.group("mode") is None:
            return BeatmapURLInfo(beatmapset_id=None, beatmap_id=match_v2_beatmap.group("beatmap_id"), gamemode=None)

        return BeatmapURLInfo(beatmapset_id=None, beatmap_id=match_v2_beatmap.group("beatmap_id"),
                              gamemode=enums.GameMode.get_mode((match_v2_beatmap.group("mode"))))

    raise SyntaxError("The given URL is invalid.")


async def beatmap_from_url(url: str, *, return_type: str = "beatmap"):
    """ Takes a url and returns the beatmap in the specified gamemode.
    If a url for a submission is given, it will find the most difficult map.

    :param url: The osu! beatmap url to lookup.
    :param return_type: Defaults to "beatmap". Use "id" to only return the id (spares a request for /b/ urls).
    :raise SyntaxError: The URL is neither a v1 or v2 osu! url.
    :raise LookupError: The beatmap linked in the URL was not found.
    """
    beatmap_info = parse_beatmap_url(url)

    # Get the beatmap specified
    if beatmap_info.beatmap_id is not None:
        if return_type == "id":
            return beatmap_info.beatmap_id
            # Only download the beatmap of the id, so that only this beatmap will be returned
        if return_type == "info":
            return beatmap_info
        params = {
            "beatmap_id": beatmap_info.beatmap_id,
        }
        difficulties = await beatmap_lookup(params=params, map_id=beatmap_info.beatmap_id, mode="osu")
        beatmapset = False
    else:
        beatmapset = await get_beatmapset(beatmap_info.beatmapset_id)
        difficulties = beatmapset["beatmaps"]
        beatmapset = True
    # If the beatmap doesn't exist, the operation was unsuccessful
    if not difficulties or "{'error': None}" in str(difficulties):
        raise LookupError("The beatmap with the given URL was not found.")

    # Find the most difficult beatmap
    beatmap = None
    highest = -1
    if beatmapset:
        for diff in difficulties:
            stars = diff["difficulty_rating"]
            if stars > highest:
                beatmap, highest = diff, stars
    else:
        beatmap = difficulties

    if return_type == "id":
        return beatmap["id"]
    if return_type == "info":
        beatmap_url = f"https://osu.ppy.sh/beatmaps/{beatmap['id']}"
        return parse_beatmap_url(beatmap_url)
    return beatmap


async def beatmapset_from_url(url: str, force_redownload: bool = False):
    """ Takes a url and returns the beatmapset of the specified beatmap.

    :param url: The osu! beatmap url to lookup.
    :param force_redownload: Whether or not to force a redownload of the map
    :raise SyntaxError: The URL is neither a v1 or v2 osu! url.
    :raise LookupError: The beatmap linked in the URL was not found.
    """
    beatmap_info = parse_beatmap_url(url)

    # Use the beatmapset_id from the url if it has one, else find the beatmapset
    if beatmap_info.beatmapset_id is not None:

        beatmapset_id = beatmap_info.beatmapset_id

        beatmapset = await get_beatmapset(beatmapset_id, force_redownload=force_redownload)
    else:
        params = {
            "beatmap_id": beatmap_info.beatmap_id,
        }
        beatmapset = await beatmapset_lookup(params=params)

    # Also make sure we get the beatmap
    if not beatmapset:
        raise LookupError("The beatmapset with the given URL was not found.")

    return beatmapset


def lookup_beatmap(beatmaps: list, **lookup):
    """ Finds and returns the first beatmap with the lookup specified.

    Beatmaps is a list of beatmap dicts and could be used with beatmap_lookup().
    Lookup is any key stored in a beatmap from beatmap_lookup().
    """
    if not beatmaps:
        return None

    for beatmap in beatmaps:
        match = True
        for key, value in lookup.items():
            if key.lower() not in beatmap:
                raise KeyError(f"The list of beatmaps does not have key: {key}")

            if not beatmap[key].lower() == value.lower():
                match = False

        if match:
            return beatmap

    return None


def rank_from_events(events: dict, beatmap_id: str, score):
    """ Return the rank of the first score of given beatmap_id from a
    list of events gathered via get_user().
    """
    for event in events:
        if event["type"] == "rank":
            beatmap_url = "https://osu.ppy.sh" + event["beatmap"]["url"]
            beatmap_info = parse_beatmap_url(beatmap_url)
            time_diff = datetime.fromisoformat(score["created_at"]) - datetime.fromisoformat(event["created_at"])
            if (beatmap_info.beatmap_id == beatmap_id and event["scoreRank"] == score["rank"]) and \
                    (time_diff.total_seconds() < 60):
                return event["rank"]

    return None
