""" Implement pp calculation features using oppai-ng.
    https://github.com/Francesco149/oppai-ng
"""

import logging
import os
from collections import namedtuple

from pcbot import utils
from . import api
from . import pp_bindings
from .args import parse as parse_options

host = "https://osu.ppy.sh/"

CachedBeatmap = namedtuple("CachedBeatmap", "url_or_id beatmap")
PPStats = namedtuple("PPStats", "pp stars partial_stars max_pp")
ClosestPPStats = namedtuple("ClosestPPStats", "acc pp stars artist title version")

cache_path = "plugins/osulib/mapcache"


async def is_osu_file(url: str):
    """ Returns True if the url links to a .osu file. """
    headers = await utils.retrieve_headers(url)
    return "text/plain" in headers.get("Content-Type", "") and ".osu" in headers.get("Content-Disposition", "")


async def download_beatmap(beatmap_url_or_id, beatmap_path: str, ignore_cache: bool = False):
    """ Download the .osu file of the beatmap with the given url, and save it to beatmap_path.

    :param beatmap_url_or_id: beatmap_url as str or the id as int
    :param beatmap_path: the path to save the beatmap in
    :param ignore_cache: whether or not to ignore the in-memory cache
    """

    beatmap_id = None
    # Parse the url and find the link to the .osu file
    try:
        if isinstance(beatmap_url_or_id, str):
            beatmap_id = await api.beatmap_from_url(beatmap_url_or_id, return_type="id")
        else:
            beatmap_id = beatmap_url_or_id
    except SyntaxError as e:
        # Since the beatmap isn't an osu.ppy.sh url, we'll see if it's a .osu file
        if not await is_osu_file(beatmap_url_or_id):
            raise ValueError from e

        file_url = beatmap_url_or_id
    else:
        file_url = host + "osu/" + str(beatmap_id)

    # Download the beatmap using the url
    beatmap_file = await utils.download_file(file_url)
    if not beatmap_file:
        raise ValueError("The given URL is invalid.")

    if ignore_cache:
        return beatmap_file

    with open(beatmap_path, "wb") as f:
        f.write(beatmap_file)

    # one map apparently had a /ufeff at the very beginning of the file???
    # https://osu.ppy.sh/b/1820921
    if not beatmap_file.decode().strip("\ufeff \t").startswith("osu file format"):
        logging.error("Invalid file received from %s\nCheck %s", file_url, beatmap_path)
        raise ValueError("Could not download the .osu file.")


async def parse_map(beatmap_url_or_id, ignore_osu_cache: bool = False):
    """ Download and parse the map with the given url or id, or return a newly parsed cached version.

    :param beatmap_url_or_id: beatmap_url as str or the id as int
    :param ignore_osu_cache: When true, does not download or use .osu file cache
    """

    if isinstance(beatmap_url_or_id, str):
        beatmap_id = await api.beatmap_from_url(beatmap_url_or_id, return_type="id")
    else:
        beatmap_id = beatmap_url_or_id

    if not ignore_osu_cache:
        beatmap_path = os.path.join(cache_path, str(beatmap_id) + ".osu")
    else:
        beatmap_path = os.path.join(cache_path, "temp.osu")

    if not os.path.exists(cache_path):
        os.makedirs(cache_path)

    # Parse from cache or load the .osu and parse new
    if ignore_osu_cache or not os.path.isfile(beatmap_path):
        await download_beatmap(beatmap_url_or_id, beatmap_path)
    return beatmap_path


async def calculate_pp(beatmap_url_or_id, *options, ignore_osu_cache: bool = False):
    """ Return a PPStats namedtuple from this beatmap, or a ClosestPPStats namedtuple
    when [pp_value]pp is given in the options.

    :param beatmap_url_or_id: beatmap_url as str or the id as int
    :param ignore_osu_cache: When true, does not download or use .osu file cache
    """

    beatmap_path = await parse_map(beatmap_url_or_id, ignore_osu_cache=ignore_osu_cache)
    args = parse_options(*options)

    # Calculate the mod bitmask and apply settings if needed
    mods_bitmask = sum(mod.value for mod in args.mods) if args.mods else 0

    # If the pp arg is given, return using the closest pp function
    # if args.pp is not None:
    #    return await find_closest_pp(args)

    # Calculate the pp
    pp_info = pp_bindings.std_pp(beatmap_path, mods_bitmask, args.combo, args.acc, args.potential_acc, args.c300,
                                 args.c100, args.c50, args.misses, args.objects)
    pp = pp_info["pp"]
    total_stars = pp_info["total_stars"]
    partial_stars = pp_info["partial_stars"]
    max_pp = pp_info["max_pp"]
    return PPStats(pp, total_stars, partial_stars, max_pp)


async def find_closest_pp(ez, args):
    """ Find the accuracy required to get the given amount of pp from this map. """
    # Define a partial command for easily setting the pp value by 100s count
    def calc(accuracy: float):
        # Set accuracy
        oppai.ezpp_set_accuracy_percent(ez, accuracy)

        return oppai.ezpp_pp(ez)

    # Find the smallest possible value oppai is willing to give
    min_pp = calc(accuracy=0.0)
    if args.pp <= min_pp:
        raise ValueError("The given pp value is too low (oppai gives **{:.02f}pp** at **0% acc**).".format(min_pp))

    # Calculate the max pp value by using 100% acc
    previous_pp = calc(accuracy=100.0)

    if args.pp >= previous_pp:
        raise ValueError("PP value should be below **{:.02f}pp** for this map.".format(previous_pp))

    dec = .05
    acc = 100.0 - dec
    while True:
        current_pp = calc(accuracy=acc)

        # Stop when we find a pp value between the current 100 count and the previous one
        if current_pp <= args.pp <= previous_pp:
            break

        previous_pp = current_pp
        acc -= dec

    # Calculate the star difficulty
    totalstars = oppai.ezpp_stars(ez)

    # Parse artist name
    artist = oppai.ezpp_artist(ez)

    # Parse beatmap title
    title = oppai.ezpp_title(ez)

    # Parse difficulty name
    version = oppai.ezpp_version(ez)

    # Find the closest pp of our two values, and return the amount of 100s
    closest_pp = min([previous_pp, current_pp], key=lambda v: abs(args.pp - v))
    acc = acc if closest_pp == current_pp else acc + dec
    oppai.ezpp_free(ez)
    return ClosestPPStats(round(acc, 2), closest_pp, totalstars, artist, title,
                          version)
