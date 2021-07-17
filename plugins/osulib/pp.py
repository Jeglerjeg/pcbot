""" Implement pp calculation features using oppai-ng.
    https://github.com/Francesco149/oppai-ng
"""

import os
from collections import namedtuple
import logging

from pcbot import utils
from . import api
from .args import parse as parse_options

try:
    from oppai import *

    can_calc_pp = True
except:
    can_calc_pp = False

host = "https://osu.ppy.sh/"

CachedBeatmap = namedtuple("CachedBeatmap", "url_or_id beatmap")
PPStats = namedtuple("PPStats", "pp stars artist title version ar od hp cs max_pp max_combo")
MapPPStats = namedtuple("PPStats", "pp stars artist title version ar od hp cs aim_pp speed_pp acc_pp aim_stars "
                        "speed_stars")
ClosestPPStats = namedtuple("ClosestPPStats", "acc pp stars artist title version")

cache_path = "plugins/osulib/mapcache"
cached_beatmap = CachedBeatmap(url_or_id=None, beatmap=None)


async def is_osu_file(url: str):
    """ Returns True if the url links to a .osu file. """
    headers = await utils.retrieve_headers(url)
    return "text/plain" in headers.get("Content-Type", "") and ".osu" in headers.get("Content-Disposition", "")


async def download_beatmap(beatmap_url_or_id):
    """ Download the .osu file of the beatmap with the given url, and save it to beatmap_path.
    :param beatmap_url_or_id: beatmap_url as str or the id as int
    """
    # Parse the url and find the link to the .osu file
    try:
        if type(beatmap_url_or_id) is str:
            beatmap_id = await api.beatmap_from_url(beatmap_url_or_id, return_type="id")
        else:
            beatmap_id = beatmap_url_or_id
    except SyntaxError as e:
        # Since the beatmap isn't an osu.ppy.sh url, we'll see if it's a .osu file
        if not await is_osu_file(beatmap_url_or_id):
            raise ValueError(e)

        file_url = beatmap_url_or_id
    else:
        file_url = host + "osu/" + str(beatmap_id)

    # Download the beatmap using the url
    beatmap_file = await utils.download_file(file_url)
    if not beatmap_file:
        raise ValueError("The given URL is invalid.")

    beatmap_path = os.path.join(cache_path, str(beatmap_id) + ".osu")
    with open(beatmap_path, "wb") as f:
        f.write(beatmap_file)

    # one map apparently had a /ufeff at the very beginning of the file???
    # https://osu.ppy.sh/b/1820921
    if not beatmap_file.decode().strip("\ufeff \t").startswith("osu file format"):
        logging.error("Invalid file received from {}\nCheck {}".format(file_url, beatmap_path))
        raise ValueError("Could not download the .osu file.")


async def parse_map(beatmap_url_or_id, ignore_cache: bool = False):
    """ Download and parse the map with the given url or id, or return a newly parsed cached version.

    :param beatmap_url_or_id: beatmap_url as str or the id as int
    :param ignore_cache: When true, the .osu will always be downloaded
    """
    global cached_beatmap

    if type(beatmap_url_or_id) is str:
        beatmap_id = await api.beatmap_from_url(beatmap_url_or_id, return_type="id")
    else:
        beatmap_id = beatmap_url_or_id

    beatmap_path = os.path.join(cache_path, str(beatmap_id) + ".osu")

    # Parse from cache or load the .osu and parse new
    if not ignore_cache and beatmap_url_or_id == cached_beatmap.url_or_id:
        beatmap = cached_beatmap.beatmap
    elif not ignore_cache and os.path.isfile(beatmap_path):
        with open(beatmap_path, encoding="utf-8") as fp:
            beatmap = fp.read()
            cached_beatmap = CachedBeatmap(url_or_id=beatmap_url_or_id, beatmap=beatmap)
    else:
        await download_beatmap(beatmap_url_or_id)
        with open(beatmap_path, encoding="utf-8") as fp:
            beatmap = fp.read()

        cached_beatmap = CachedBeatmap(url_or_id=beatmap_url_or_id, beatmap=beatmap)

    return beatmap


async def calculate_pp(beatmap_url_or_id, *options, ignore_cache: bool = False, map_calc: bool = False,
                       potential: bool = False):
    """ Return a PPStats namedtuple from this beatmap, or a ClosestPPStats namedtuple
    when [pp_value]pp is given in the options.

    :param beatmap_url_or_id: beatmap_url as str or the id as int
    :param ignore_cache: When true, the .osu will always be downloaded
    :param map_calc: When true, calculates and returns more fields in the PPStats tuple
    :param potential: When true, calculates and returns the potenial PP if FC
    """
    noautoacc = False
    ez = ezpp_new()
    beatmap = await parse_map(beatmap_url_or_id, ignore_cache=ignore_cache)
    args = parse_options(*options)

    # Set number of misses
    ezpp_set_nmiss(ez, args.misses)

    # Set args if needed
    if args.ar:
        ezpp_set_base_ar(ez, args.ar)
    if args.hp:
        ezpp_set_base_hp(ez, args.hp)
    if args.od:
        ezpp_set_base_od(ez, args.od)
    if args.cs:
        ezpp_set_base_cs(ez, args.cs)

    # Calculate the mod bitmask and apply settings if needed
    mods_bitmask = sum(mod.value for mod in args.mods) if args.mods else 0
    ezpp_set_mods(ez, mods_bitmask)

    ezpp_data_dup(ez, beatmap, len(beatmap.encode(errors="replace")))
    ezpp_set_autocalc(ez, 1)

    # Store total map objects in case map length is changed
    total_objects = ezpp_nobjects(ez)

    # Store max combo for use in create_score_embed_with_pp()
    max_combo = ezpp_max_combo(ez)

    # Calculate the star difficulty
    totalstars = ezpp_stars(ez)

    # Set end of map if failed
    if args.rank == "Frank":
        objects = args.c300 + args.c100 + args.c50 + args.misses
        ezpp_set_end(ez, objects)
        noautoacc = True

    # Set accuracy based on arguments
    if args.acc is not None and noautoacc is not True:
        ezpp_set_accuracy_percent(ez, args.acc)
    else:
        ezpp_set_accuracy(ez, args.c100, args.c50)

    # Set combo
    if args.combo is not None:
        ezpp_set_combo(ez, args.combo)

    # Set score version
    ezpp_set_score_version(ez, args.score_version)

    # Parse artist name
    artist = ezpp_artist(ez)

    # Parse beatmap title
    title = ezpp_title(ez)

    # Parse difficulty name
    version = ezpp_version(ez)

    # If the pp arg is given, return using the closest pp function
    if args.pp is not None:
        return await find_closest_pp(ez, args)

    ar = ezpp_ar(ez)
    od = ezpp_od(ez)
    hp = ezpp_hp(ez)
    cs = ezpp_cs(ez)

    if map_calc:
        # Calculate map_calc specific values
        aim_pp = ezpp_aim_pp(ez)
        speed_pp = ezpp_speed_pp(ez)
        acc_pp = ezpp_acc_pp(ez)
        aim_stars = ezpp_aim_stars(ez)
        speed_stars = ezpp_speed_stars(ez)

        # Calculate the pp
        pp = ezpp_pp(ez)
        ezpp_free(ez)
        return MapPPStats(pp, totalstars, artist, title, version, ar, od, hp, cs, aim_pp, speed_pp, acc_pp, aim_stars,
                          speed_stars)

    # Calculate the pp
    pp = ezpp_pp(ez)
    max_pp = None
    if potential:
        ezpp_set_end(ez, total_objects)
        ezpp_set_nmiss(ez, 0)
        ezpp_set_accuracy_percent(ez, args.potential_acc)
        ezpp_set_combo(ez, ezpp_max_combo(ez))
        max_pp = ezpp_pp(ez)

    ezpp_free(ez)
    return PPStats(pp, totalstars, artist, title, version, ar, od, hp, cs, max_pp, max_combo)


async def find_closest_pp(ez, args):
    """ Find the accuracy required to get the given amount of pp from this map. """
    if not can_calc_pp:
        return None

    # Define a partial command for easily setting the pp value by 100s count
    def calc(accuracy: float):
        # Set accuracy
        ezpp_set_accuracy_percent(ez, accuracy)

        return ezpp_pp(ez)

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
        else:
            previous_pp = current_pp
            acc -= dec

    # Calculate the star difficulty
    totalstars = ezpp_stars(ez)

    # Parse artist name
    artist = ezpp_artist(ez)

    # Parse beatmap title
    title = ezpp_title(ez)

    # Parse difficulty name
    version = ezpp_version(ez)

    # Find the closest pp of our two values, and return the amount of 100s
    closest_pp = min([previous_pp, current_pp], key=lambda v: abs(args.pp - v))
    acc = acc if closest_pp == current_pp else acc + dec
    ezpp_free(ez)
    return ClosestPPStats(round(acc, 2), closest_pp, totalstars, artist, title,
                          version)
