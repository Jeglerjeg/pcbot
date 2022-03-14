""" Implement pp calculation features using rosu-pp python bindings.
    https://github.com/MaxOhn/rosu-pp-py
"""

import logging
import os
from collections import namedtuple

from pcbot import utils
from . import api
from .args import parse as parse_options

try:
    import rosu_pp_py
except ImportError:
    rosu_pp_py = None

host = "https://osu.ppy.sh/"

CachedBeatmap = namedtuple("CachedBeatmap", "url_or_id beatmap")
PPStats = namedtuple("PPStats", "pp stars partial_stars max_pp max_combo ar cs od hp bpm")
ClosestPPStats = namedtuple("ClosestPPStats", "acc pp stars")

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


async def calculate_pp(beatmap_url_or_id, *options, mode: api.GameMode, ignore_osu_cache: bool = False, failed: bool = False, potential: bool = False):
    """ Return a PPStats namedtuple from this beatmap, or a ClosestPPStats namedtuple
    when [pp_value]pp is given in the options.

    :param beatmap_url_or_id: beatmap_url as str or the id as int
    :param mode: which mode to calculate PP for
    :param ignore_osu_cache: When true, does not download or use .osu file cache
    :param failed: whether or not the play was failed
    :param potential: whether or not potential PP should be calculated
    """

    if not rosu_pp_py:
        return

    beatmap_path = await parse_map(beatmap_url_or_id, ignore_osu_cache=ignore_osu_cache)
    args = parse_options(*options)

    # Calculate the mod bitmask and apply settings if needed
    if args.mods and api.Mods.NC in args.mods:
        args.mods.remove(api.Mods.NC)
        args.mods.append(api.Mods.DT)
    mods_bitmask = sum(mod.value for mod in args.mods) if args.mods else 0

    calculator = rosu_pp_py.Calculator(beatmap_path)
    score_params = rosu_pp_py.ScoreParams(mods=mods_bitmask)

    # If the pp arg is given, return using the closest pp function
    if args.pp is not None and mode is api.GameMode.osu:
        return await find_closest_pp(calculator, score_params, args)

    # Calculate the pp
    max_pp = None
    max_combo = None
    total_stars = None
    # Calculate maximum stars and pp
    if failed or potential:
        if args.potential_acc:
            score_params.acc = args.potential_acc
        [potential_pp_info] = calculator.calculate(score_params)
        total_stars = potential_pp_info.stars
        if mode is api.GameMode.osu:
            max_pp = potential_pp_info.pp

    # Calculate actual stars and pp
    score_params = get_score_params(score_params, args)
    [pp_info] = calculator.calculate(score_params)
    if mode is api.GameMode.osu:
        max_combo = pp_info.maxCombo
    elif mode is api.GameMode.taiko or mode is api.GameMode.fruits:
        max_combo = pp_info.maxCombo

    pp = pp_info.pp
    total_stars = total_stars if failed else pp_info.stars
    partial_stars = pp_info.stars
    ar = pp_info.ar
    cs = pp_info.od
    od = pp_info.od
    hp = pp_info.hp
    bpm = pp_info.bpm
    return PPStats(pp, total_stars, partial_stars, max_pp, max_combo, ar, cs, od, hp, bpm)


def get_score_params(score_params: rosu_pp_py.ScoreParams, args):
    if args.objects:
        score_params.passedObjects = args.objects
    if args.combo:
        score_params.combo = args.combo
    if args.acc:
        score_params.acc = args.acc
    if args.c300:
        score_params.n300 = args.c300
    if args.c100:
        score_params.n100 = args.c100
    if args.c50:
        score_params.n50 = args.c50
    if args.misses:
        score_params.nMisses = args.misses
    if args.score:
        score_params.score = args.score
    if args.dropmiss:
        score_params.nKatu = args.dropmiss
    return score_params


async def find_closest_pp(calculator, score_params, args):
    """ Find the accuracy required to get the given amount of pp from this map. """
    # Define a partial command for easily setting the pp value by 100s count
    def calc(accuracy: float):
        new_score_params = get_score_params(score_params, args)
        new_score_params.acc = accuracy
        [pp_info] = calculator.calculate(new_score_params)

        return pp_info

    # Find the smallest possible value rosu-pp is willing to give, below 16.67% acc returns infpp since
    # it's an impossible value.
    min_pp = calc(accuracy=16.67)

    if args.pp <= min_pp.pp:
        raise ValueError(f"The given pp value is too low (calculator gives **{min_pp.pp:.02f}pp** as the "
                         "lowest possible).")

    # Calculate the max pp value by using 100% acc
    previous_pp = calc(accuracy=100.0)

    if args.pp >= previous_pp.pp:
        raise ValueError(f"PP value should be below **{previous_pp.pp:.02f}pp** for this map.")

    dec = .05
    acc = 100.0 - dec
    while True:
        current_pp = calc(accuracy=acc)

        # Stop when we find a pp value between the current 100 count and the previous one
        if current_pp.pp <= args.pp <= previous_pp.pp:
            break

        previous_pp = current_pp
        acc -= dec

    # Calculate the star difficulty
    totalstars = current_pp.stars

    # Find the closest pp of our two values, and return the amount of 100s
    closest_pp = min([previous_pp.pp, current_pp.pp], key=lambda v: abs(args.pp - v))
    acc = acc if closest_pp == current_pp.pp else acc + dec
    return ClosestPPStats(round(acc, 2), closest_pp, totalstars)
