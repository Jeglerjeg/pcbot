""" API integration for osu!

    Adds Mods enums with raw value calculations and some
    request functions.
"""
import asyncio
import logging
import re
import traceback
from collections import namedtuple
from datetime import datetime, timezone, timedelta

from aiohttp import ClientConnectorError
from dateutil import parser

from plugins.osulib.models.beatmap import Beatmapset
from plugins.osulib.models.score import OsuScore
from plugins.osulib.models.user import OsuUser, RespektiveScoreRank

try:
    import pyrate_limiter
except ImportError:
    pyrate_limiter = None
    logging.info("pyrate_limiter is not installed, osu api functionality is unavailable.")

import bot
import plugins
from plugins.osulib import enums, caching, db
from plugins.osulib.constants import ratelimit, host
from pcbot import utils

client = plugins.client  # type: bot.Client

main_api_url = f"{host}/api/v2/"
lazer_api_url = "https://lazer.ppy.sh/api/v2/"
access_token = ""
expires = datetime.now(tz=timezone.utc)
requests_sent = 0

if pyrate_limiter:
    hourly_rate = pyrate_limiter.RequestRate(ratelimit, pyrate_limiter.Duration.MINUTE)  # Amount of requests per minute
    limiter = pyrate_limiter.Limiter(hourly_rate)
else:
    limiter = None


async def refresh_access_token(client_id, client_secret):
    while not client.is_closed():
        try:
            await asyncio.sleep((expires - datetime.now(tz=timezone.utc)).total_seconds())
        except asyncio.CancelledError:
            return
        await get_access_token(client_id, client_secret)


async def get_access_token(client_id: str, client_secret: str):
    """ Retrieves access token from API and refreshes token after it expires. """
    params = {
        "grant_type": "client_credentials",
        "client_id": int(client_id),
        "client_secret": client_secret,
        "scope": "public"
    }
    try:
        result = await utils.post_request("https://osu.ppy.sh/oauth/token", call=utils.convert_to_json, data=params)
    except ClientConnectorError:
        logging.warning("Couldn't connect to osu.ppy.sh to retrieve access token. Trying again in 10 seconds.")
        await asyncio.sleep(10)
        await get_access_token(client_id, client_secret)
        return
    global requests_sent
    requests_sent += 1
    global access_token
    access_token = result["access_token"]
    dt = datetime.now(tz=timezone.utc)
    td = timedelta(seconds=result["expires_in"])
    global expires
    expires = dt + td


def def_section(api_name: str, first_element: bool = False, api_url: str = main_api_url):
    """ Add a section using a template to simplify adding API functions. """

    async def template(url=api_url, request_tries: int = 1, **params):
        if not limiter:
            return None
        if not access_token:
            return None
        async with limiter.ratelimit("osu", delay=True):
            # Add the API key
            headers = {
                "Authorization": "Bearer " + access_token,
                "x-api-version": "20220706"
            }

            # Download using a URL of the given API function name
            for _ in range(request_tries):
                try:
                    response = await utils.download_json(url + api_name, headers=headers, **params)

                except ValueError as e:
                    logging.warning("ValueError Calling %s: %s", url + api_name, e)
                else:
                    global requests_sent
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


def respektive_def_section(api_name: str, first_element: bool = False, api_url: str = main_api_url):
    """ Add a section using a template to simplify adding API functions. """

    async def template(url=api_url, request_tries: int = 1, **params):
        # Download using a URL of the given API function name
        for _ in range(request_tries):
            try:
                response = await utils.download_json(url + api_name, **params)

            except ValueError as e:
                logging.warning("ValueError Calling %s: %s", url + api_name, e)
            else:
                global requests_sent
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


# Define all osu! API requests using the template
async def beatmap_lookup(map_id):
    """ Looks up a beatmap unless cache exists"""
    result = caching.retrieve_cache(map_id, "map")
    valid_result = caching.validate_cache(result)
    if not valid_result:
        if result:
            caching.delete_cache(Beatmapset(db.get_beatmapset(result.beatmapset_id), from_db=True))
        params = {
            "beatmap_id": map_id,
        }
        await beatmapset_lookup(params=params)
        result = caching.retrieve_cache(map_id, "map")
    return result


async def beatmapset_lookup(params):
    """ Looks up a beatmapset using a beatmap ID"""
    request = def_section("beatmapsets/lookup")
    beatmap = caching.retrieve_cache(params["beatmap_id"], "map")
    if beatmap:
        result = caching.retrieve_cache(beatmap.beatmapset_id, "set")
    else:
        result = None
    valid_result = caching.validate_cache(result)
    if not valid_result:
        if result:
            caching.delete_cache(result)
        result = await request(**params)
        if "{'error': None}" in str(result) or result is None:
            return None
        caching.cache_beatmapset(result)
        result = Beatmapset(result)
    return result


async def get_user(user, mode=None, params=None):
    """ Return a user from the API"""
    if mode:
        request = def_section(f"users/{user}/{mode}")
    else:
        request = def_section(f"users/{user}")

    if params:
        result = await request(**params)
    else:
        result = await request()

    if "{'error': None}" in str(result) or result is None:
        return None
    try:
        user = OsuUser(result, from_db=False)
    except KeyError as e:
        logging.error(traceback.format_exception(e))
        return None
    return user


async def get_user_scores(user_id, score_type, params=None, lazer: bool = False):
    """ Returns a user's best, recent or #1 scores. """
    request = def_section(f"users/{user_id}/scores/{score_type}", api_url=lazer_api_url if lazer else main_api_url)
    if params:
        result = await request(**params)
    else:
        result = await request()
    if "{'error': None}" in str(result) or result is None:
        result = None
    else:
        result = [OsuScore(osu_score) for osu_score in result]
    return result


async def get_user_beatmap_score(beatmap_id, user_id, params=None, lazer: bool = False):
    """ Returns a user's score on a beatmap. """
    request = def_section(f"beatmaps/{beatmap_id}/scores/users/{user_id}",
                          api_url=lazer_api_url if lazer else main_api_url)
    if params:
        result = await request(**params)
    else:
        result = await request()
    if "{'error': None}" in str(result):
        result = None
    else:
        result["score"] = OsuScore(result["score"])
    return result


async def get_user_beatmap_scores(beatmap_id: int, user_id: int, params=None, lazer: bool = False):
    """ Returns all of a user's scores on a beatmap. """
    request = def_section(f"beatmaps/{beatmap_id}/scores/users/{user_id}/all",
                          api_url=lazer_api_url if lazer else main_api_url)
    if params:
        result = await request(**params)
    else:
        result = await request()
    if "{'error': None}" in str(result) or result is None:
        result = None
    else:
        result["scores"] = [OsuScore(osu_score) for osu_score in result["scores"]]
    return result


async def get_beatmapset(beatmapset_id, force_redownload: bool = False):
    """ Returns a beatmapset using beatmapset ID"""
    result = caching.retrieve_cache(beatmapset_id, "set")
    valid_result = caching.validate_cache(result)
    if not valid_result or force_redownload:
        if result:
            caching.delete_cache(result)
        request = def_section(f"beatmapsets/{beatmapset_id}")
        result = await request()
        caching.cache_beatmapset(result)
        result = Beatmapset(result)
    return result


async def get_user_recent_activity(user, params=None):
    """ Return a user's recent activity. """
    request = def_section(f"users/{user}/recent_activity")
    if params:
        return await request(**params)
    return await request()


async def respektive_score_rank(user_id: int, mode: int):
    request = respektive_def_section(f"u/{user_id}?m={mode}", api_url="https://score.respektive.pw/")

    result = await request()

    if not result:
        return None

    return RespektiveScoreRank(result[0])


beatmap_url_pattern_v1 = \
    re.compile(r"https?://(osu|old|lazer)\.ppy\.sh/(?P<type>[bs])/(?P<id>\d+)(?:\?m=(?P<mode>\d))?")
beatmapset_url_pattern_v2 = \
    re.compile(r"https?://(osu|lazer)\.ppy\.sh/beatmapsets/(?P<beatmapset_id>\d+)/?(?:#(?P<mode>\w+)/("
               r"?P<beatmap_id>\d+))?")
beatmap_url_pattern_v2 = re.compile(r"https?://(osu|lazer)\.ppy\.sh/beatmaps/(?P<beatmap_id>\d+)(?:\?mode=("
                                    r"?P<mode>\w+))?")

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
        difficulties = await beatmap_lookup(map_id=beatmap_info.beatmap_id)
        beatmapset = False
    else:
        beatmapset = await get_beatmapset(beatmap_info.beatmapset_id)
        difficulties = beatmapset.beatmaps
        beatmapset = True
    # If the beatmap doesn't exist, the operation was unsuccessful
    if not difficulties:
        raise LookupError("The beatmap with the given URL was not found.")

    # Find the most difficult beatmap
    beatmap = None
    highest = -1
    if beatmapset:
        for diff in difficulties:
            stars = diff.difficulty_rating
            if stars > highest:
                beatmap, highest = diff, stars
    else:
        beatmap = difficulties

    if return_type == "id":
        return beatmap.id
    if return_type == "info":
        beatmap_url = f"{host}/beatmaps/{beatmap.id}"
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


def rank_from_events(events: dict, beatmap_id: str, osu_score: OsuScore):
    """ Return the rank of the first score of given beatmap_id from a
    list of events gathered via get_user().
    """
    for event in events:
        if event["type"] == "rank":
            beatmap_url = host + event["beatmap"]["url"]
            beatmap_info = parse_beatmap_url(beatmap_url)
            time_diff = osu_score.ended_at - parser.isoparse(event["created_at"])
            if (beatmap_info.beatmap_id == beatmap_id and event["scoreRank"] == osu_score.rank) and \
                    (time_diff.total_seconds() < 60):
                return event["rank"]

    return None