""" API integration for osu!

    Adds Mods enums with raw value calculations and some
    request functions.
"""
import asyncio
import logging
import re
from collections import namedtuple
from enum import Enum

from pcbot import utils


api_url = "https://osu.ppy.sh/api/v2/"
access_token = ""
requests_sent = 0

mode_names = {
    "Standard": ["standard", "osu"],
    "Taiko": ["taiko"],
    "Catch": ["catch", "ctb", "fruits"],
    "Mania": ["mania", "keys"]
}


async def set_oauth_client(b: str, s: str):
    """ Set the osu! API key. This simplifies every API function as they
    can exclude the "k" parameter.
    """

    client_id = b
    client_secret = s
    await get_access_token(client_id, client_secret)


async def get_access_token(client_id, client_secret):
    params = {
        "grant_type": "client_credentials",
        "client_id": int(client_id),
        "client_secret": client_secret,
        "scope": "public"
    }

    result = await utils.post_request("https://osu.ppy.sh/oauth/token", call=utils._convert_json, data=params)
    global requests_sent
    requests_sent += 1
    global access_token
    access_token = result["access_token"]
    await asyncio.sleep(result["expires_in"])
    await get_access_token(client_id, client_secret)


class GameMode(Enum):
    """ Enum for gamemodes. """
    Standard = 0
    Taiko = 1
    Catch = 2
    Mania = 3

    @classmethod
    def get_mode(cls, mode: str):
        """ Return the mode with the specified string. """
        for mode_name, names in mode_names.items():
            for name in names:
                if name.startswith(mode.lower()):
                    return GameMode.__members__[mode_name]

        return None


class Mods(Enum):
    """ Enum for displaying mods. """
    NF = 0
    EZ = 1
    TD = 2
    HD = 3
    HR = 4
    SD = 5
    DT = 6
    RX = 7
    HT = 8
    NC = 9
    FL = 10
    AU = 11
    SO = 12
    AP = 13
    PF = 14
    Key4 = 15
    Key5 = 16
    Key6 = 17
    Key7 = 18
    Key8 = 19
    FI = 20
    RD = 21
    Cinema = 22
    Key9 = 24
    KeyCoop = 25
    Key1 = 26
    Key3 = 27
    Key2 = 28
    ScoreV2 = 29
    LastMod = 30
    KeyMod = Key4 | Key5 | Key6 | Key7 | Key8
    FreeModAllowed = NF | EZ | HD | HR | SD | FL | FI | RX | AP | SO | KeyMod  # ¯\_(ツ)_/¯
    ScoreIncreaseMods = HD | HR | DT | FL | FI

    def __new__(cls, num):
        """ Convert the given value to 2^num. """
        obj = object.__new__(cls)
        obj._value_ = 2 ** num
        return obj

    @classmethod
    def list_mods(cls, bitwise: int):
        """ Return a list of mod enums from the given bitwise (enabled_mods in the osu! API) """
        bin_str = str(bin(bitwise))[2:]
        bin_list = [int(d) for d in bin_str[::-1]]
        mods_bin = (pow(2, i) for i, d in enumerate(bin_list) if d == 1)
        mods = [cls(mod) for mod in mods_bin]

        # Manual checks for multiples
        if Mods.DT in mods and Mods.NC in mods:
            mods.remove(Mods.DT)

        return mods

    @classmethod
    def format_mods(cls, mods):
        """ Return a string with the mods in a sorted format, such as DTHD.

        mods is either a bitwise or a list of mod enums.
        """
        if type(mods) is int:
            mods = cls.list_mods(mods)
        assert type(mods) is list

        return "".join((mod for mod in mods) if mods else ["Nomod"])


def def_section(api_name: str, first_element: bool=False):
    """ Add a section using a template to simplify adding API functions. """
    async def template(url=api_url, request_tries: int=1, **params):
        global requests_sent

        # Add the API key
        headers = {
            "Authorization": "Bearer " + access_token
        }

        # Download using a URL of the given API function name
        for i in range(request_tries):
            try:
                json = await utils.download_json(url + api_name, headers=headers, **params)
            except ValueError as e:
                logging.warning("ValueError Calling {}: {}".format(url + api_name, e))
            else:
                requests_sent += 1

                if json is not None:
                    break
        else:
            return None

        # Unless we want to extract the first element, return the entire object (usually a list)
        if not first_element:
            return json

        # If the returned value should be the first element, see if we can cut it
        return json[0] if len(json) > 0 else None

    # Set the correct name of the function and add simple docstring
    template.__name__ = api_name
    template.__doc__ = "Get " + ("list" if not first_element else "dict") + " using " + api_url + api_name
    return template


# Define all osu! API requests using the template
beatmap_lookup = def_section("beatmaps/lookup")
beatmapset_lookup = def_section("beatmapsets/lookup")


async def get_user(user, mode=None, params=None):
    if mode:
        request = def_section("users/" + user + "/" + mode)
    else:
        request = def_section("users/" + user)
    if params:
        return await request(**params)
    else:
        return await request()


async def get_user_scores(user_id, type, params=None):
    request = def_section("users/" + user_id + "/scores/" + type)
    if params:
        return await request(**params)
    else:
        return await request("")


async def get_user_beatmap_score(beatmap_id, user_id, params=None):
    request = def_section("beatmaps/" + beatmap_id + "/scores/users/" + user_id)
    if params:
        result = await request(**params)
    else:
        result = await request()
    if "{'error': None}" in str(result):
        result = None
    return result


async def get_beatmapset(beatmapset_id):
    request = def_section("beatmapsets/" + beatmapset_id)
    return await request()


async def get_user_recent_activity(user):
    request = def_section("users/" + user + "/recent_activity")
    return await request()

beatmap_url_pattern_v1 = re.compile(r"https?://(osu|old)\.ppy\.sh/(?P<type>[bs])/(?P<id>\d+)(?:\?m=(?P<mode>\d))?")
beatmap_url_pattern_v2 = re.compile(r"https?://osu\.ppy\.sh/beatmapsets/(?P<beatmapset_id>\d+)(?:#(?P<mode>\w+)/(?P<beatmap_id>\d+))?")

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
            mode = GameMode(int(match_v1.group("mode")))

        if match_v1.group("type") == "b":
            return BeatmapURLInfo(beatmapset_id=None, beatmap_id=match_v1.group("id"), gamemode=mode)
        else:
            return BeatmapURLInfo(beatmapset_id=match_v1.group("id"), beatmap_id=None, gamemode=mode)

    match_v2 = beatmap_url_pattern_v2.match(url)
    if match_v2:
        if match_v2.group("mode") is None:
            return BeatmapURLInfo(beatmapset_id=match_v2.group("beatmapset_id"), beatmap_id=None, gamemode=None)
        else:
            return BeatmapURLInfo(beatmapset_id=match_v2.group("beatmapset_id"),
                                  beatmap_id=match_v2.group("beatmap_id"),
                                  gamemode=GameMode.get_mode(match_v2.group("mode")))

    raise SyntaxError("The given URL is invalid.")


async def beatmap_from_url(url: str, *, return_type: str="beatmap"):
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
        params = {
            "id": beatmap_info.beatmap_id,
        }
        difficulties = await beatmap_lookup(**params)
    else:
        difficulties = await get_beatmapset(beatmap_info.beatmapset_id)
    # If the beatmap doesn't exist, the operation was unsuccessful
    if not difficulties or "{'error': None}" in str(difficulties):
        raise LookupError("The beatmap with the given URL was not found.")

    # Find the most difficult beatmap
    beatmap = None
    highest = -1
    for diff in difficulties:
        stars = diff["difficulty_rating"]
        if stars > highest:
            beatmap, highest = diff, stars

    if return_type == "id":
        return beatmap["beatmap_id"]
    return beatmap


async def beatmapset_from_url(url: str):
    """ Takes a url and returns the beatmapset of the specified beatmap.

    :param url: The osu! beatmap url to lookup.
    :raise SyntaxError: The URL is neither a v1 or v2 osu! url.
    :raise LookupError: The beatmap linked in the URL was not found.
    """
    beatmap_info = parse_beatmap_url(url)

    # Use the beatmapset_id from the url if it has one, else find the beatmapset
    if beatmap_info.beatmapset_id is not None:

        beatmapset_id = beatmap_info.beatmapset_id

        beatmapset = await get_beatmapset(beatmapset_id)
    else:
        params = {
            "beatmap_id": beatmap_info.beatmap_id,
        }
        beatmapset = await beatmapset_lookup(**params)

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
                raise KeyError("The list of beatmaps does not have key: {}".format(key))

            if not beatmap[key].lower() == value.lower():
                match = False

        if match:
            return beatmap
    else:
        return None


def rank_from_events(events: dict, beatmap_id: str):
    """ Return the rank of the first score of given beatmap_id from a
    list of events gathered via get_user().
    """
    for event in events:
        if event["type"] == "rank":
            beatmap_url = "https://osu.ppy.sh" + event["beatmap"]["url"]
            beatmap_info = parse_beatmap_url(beatmap_url)
            if beatmap_info.beatmap_id == beatmap_id:
                return event["rank"]
    else:
        return None
