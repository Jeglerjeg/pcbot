""" Implement pp calculation features using rosu-pp python bindings.
    https://github.com/MaxOhn/rosu-pp-py
"""

import logging
import os
import traceback
from collections import namedtuple
from operator import itemgetter
from typing import Union

from pcbot import utils, Config
from plugins.osulib import enums, api
from plugins.osulib.args import parse as parse_options
from plugins.osulib.args import mods as parse_mods
from plugins.osulib.models.beatmap import Beatmap, Beatmapset
from plugins.osulib.models.score import OsuScore
from plugins.osulib.utils import misc_utils, score_utils

import rosu_pp_py


CachedBeatmap = namedtuple("CachedBeatmap", "url_or_id beatmap")
PPStats = namedtuple("PPStats", "pp stars partial_stars max_pp max_combo ar cs od hp clock_rate")
ClosestPPStats = namedtuple("ClosestPPStats", "count_100 pp stars")

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
        file_url = "https://osu.ppy.sh/osu/" + str(beatmap_id)

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


async def calculate_pp(beatmap_url_or_id, *options, mods: Union[list, str], mode: enums.GameMode, ignore_osu_cache: bool = False,
                       failed: bool = False, potential: bool = False, lazer: bool = False):
    """ Return a PPStats namedtuple from this beatmap, or a ClosestPPStats namedtuple
    when [pp_value]pp is given in the options.

    :param beatmap_url_or_id: beatmap_url as str or the id as int
    :param mods: the mods to calculate pp for
    :param mode: which mode to calculate PP for
    :param ignore_osu_cache: When true, does not download or use .osu file cache
    :param failed: whether the play was failed
    :param potential: whether potential PP should be calculated
    :param lazer: whether the score was set on lazer
    """

    if not rosu_pp_py:
        return

    beatmap_path = await parse_map(beatmap_url_or_id, ignore_osu_cache=ignore_osu_cache)
    args = parse_options(*options)

    # Calculate the mod bitmask and apply settings if needed
    if isinstance(mods, str):
        mod_args = parse_mods(mods)
        if mod_args and enums.Mods.NC in mod_args:
            mod_args.remove(enums.Mods.NC)
            mod_args.append(enums.Mods.DT)
        mods = sum(mod.value for mod in mod_args) if mod_args else 0
    elif args.mods:
        if args.mods and enums.Mods.NC in args.mods:
            args.mods.remove(enums.Mods.NC)
            args.mods.append(enums.Mods.DT)
        mods = sum(mod.value for mod in args.mods) if args.mods else 0

    osu_map = rosu_pp_py.Beatmap(path=beatmap_path)

    osu_map.convert(mode.to_rosu(), mods=mods)
    calculator = rosu_pp_py.Performance(mods=mods)
    calculator.set_lazer(lazer)
    if args.clock_rate:
        calculator.set_clock_rate(args.clock_rate)

    # If the pp arg is given, return using the closest pp function
    if args.pp is not None and mode is enums.GameMode.osu:
        return await find_closest_pp(osu_map, calculator, args)

    # Calculate the pp
    max_pp = None
    total_stars = None
    max_combo = None
    # Calculate maximum stars and pp
    if failed or potential:
        if args.potential_acc:
            calculator.set_accuracy(args.potential_acc)
        potential_pp_info = calculator.calculate(osu_map)
        max_combo = potential_pp_info.difficulty.max_combo
        total_stars = potential_pp_info.difficulty.stars
        if mode is enums.GameMode.osu:
            max_pp = potential_pp_info.pp

    # Calculate actual stars and pp
    calculator = set_score_params(calculator, args)
    pp_info = calculator.calculate(osu_map)
    if not max_combo:
        max_combo = pp_info.difficulty.max_combo

    map_attributes = rosu_pp_py.BeatmapAttributesBuilder(map=osu_map, mods=mods)
    map_attributes = set_map_params(map_attributes, args).build()

    pp = pp_info.pp
    total_stars = total_stars if failed else pp_info.difficulty.stars
    partial_stars = pp_info.difficulty.stars
    ar = map_attributes.ar
    cs = map_attributes.cs
    od = map_attributes.od
    hp = map_attributes.hp
    clock_rate = map_attributes.clock_rate
    return PPStats(pp, total_stars, partial_stars, max_pp, max_combo, ar, cs, od, hp, clock_rate)


def set_map_params(osu_map_attributes: rosu_pp_py.BeatmapAttributesBuilder, args):
    if args.clock_rate:
        osu_map_attributes.set_clock_rate(args.clock_rate)
    if args.ar:
        osu_map_attributes.set_ar(args.ar, False)
    if args.od:
        osu_map_attributes.set_od(args.od, False)
    if args.hp:
        osu_map_attributes.set_hp(args.hp, False)
    if args.cs:
        osu_map_attributes.set_cs(args.cs, False)
    return osu_map_attributes


def set_score_params(calculator: rosu_pp_py.Performance, args):
    if args.ar:
        calculator.set_ar(args.ar, False)
    if args.od:
        calculator.set_od(args.od, False)
    if args.hp:
        calculator.set_hp(args.hp, False)
    if args.cs:
        calculator.set_cs(args.cs, False)
    if args.objects and args.objects > 0:
        calculator.set_passed_objects(args.objects)
    if args.combo:
        calculator.set_combo(args.combo)
    if args.acc:
        calculator.set_accuracy(args.acc)
    if args.c300:
        calculator.set_n300(args.c300)
    if args.c100:
        calculator.set_n100(args.c100)
    if args.c50:
        calculator.set_n50(args.c50)
    if args.katu:
        calculator.set_n_katu(args.katu)
    if args.geki:
        calculator.set_n_geki(args.geki)
    if args.misses:
        calculator.set_misses(args.misses)
    if args.large_ticks:
        calculator.set_large_tick_hits(args.large_ticks)
    if args.small_ticks:
        calculator.set_small_tick_hits(args.small_ticks)
    if args.slider_ends:
        calculator.set_slider_end_hits(args.slider_ends)
    return calculator


async def find_closest_pp(osu_map: rosu_pp_py.Beatmap, calculator: rosu_pp_py.Performance, args):
    """ Find the accuracy required to get the given amount of pp from this map. """

    # Define a partial command for easily setting the pp value by 100s count
    def calc(n100: int, pp_info=None):
        if pp_info:
            calculator.set_n100(n100)
            pp_info = calculator.calculate(pp_info)
        else:
            new_calculator = set_score_params(calculator, args)
            new_calculator.set_n100(n100)
            pp_info = new_calculator.calculate(osu_map)

        return pp_info

    # Find the smallest possible value rosu-pp is willing to give, below 16.67% acc returns infpp since
    # it's an impossible value.
    min_pp = calc(n100=osu_map.n_objects)

    if args.pp <= min_pp.pp:
        raise ValueError(f"The given pp value is too low (calculator gives **{min_pp.pp:.02f}pp** as the "
                         "lowest possible).")

    # Calculate the max pp value by using 100% acc
    previous_pp = calc(0, min_pp)

    if args.pp >= previous_pp.pp:
        raise ValueError(f"PP value should be below **{previous_pp.pp:.02f}pp** for this map.")

    count_100 = 0
    while True:
        current_pp = calc(count_100, min_pp)

        # Stop when we find a pp value between the current 100 count and the previous one
        if current_pp.pp <= args.pp <= previous_pp.pp:
            break

        previous_pp = current_pp
        count_100 += 1

    # Calculate the star difficulty
    totalstars = current_pp.difficulty.stars

    # Find the closest pp of our two values, and return the amount of 100s
    closest_pp = min([previous_pp.pp, current_pp.pp], key=lambda v: abs(args.pp - v))
    count_100 = count_100 if closest_pp == current_pp.pp else count_100 - 1
    return ClosestPPStats(count_100, closest_pp, totalstars)


def get_beatmap_sr(score_pp: PPStats, beatmap: Beatmap, mods: str):
    """ Change beatmap SR if using SR adjusting mods. """
    difficulty_rating = score_pp.stars if \
        (mods not in ("Nomod", "HD", "FL", "TD", "ScoreV2", "NF", "SD", "PF", "RX") or not beatmap.convert) \
        and score_pp else beatmap.difficulty_rating
    return difficulty_rating


def calculate_total_user_pp(osu_scores: list[OsuScore], old_pp: float):
    """ Calculates the user's total PP. """
    total_pp = 0
    for i, osu_score in enumerate(osu_scores):
        total_pp += osu_score.pp * (0.95 ** i)
    total_pp_without_bonus_pp = 0
    for osu_score in osu_scores:
        total_pp_without_bonus_pp += osu_score.weight["pp"]
    bonus_pp = old_pp - total_pp_without_bonus_pp
    return total_pp + bonus_pp


async def get_score_pp(osu_score: OsuScore, mode: enums.GameMode, beatmap: Beatmap = None):
    """ Return PP for a given score. """
    score_pp = None
    try:
        score_pp = await calculate_pp(beatmap.id if beatmap else osu_score.beatmap_id, mods=osu_score.mods, mode=mode,
                                      ignore_osu_cache=not bool(beatmap.status in ("ranked", "approved")) if beatmap
                                      else False,
                                      potential=score_utils.calculate_potential_pp(osu_score, mode),
                                      failed=not osu_score.passed, *score_utils.process_score_args(osu_score),
                                      lazer=osu_score.build_id is not None)
    except Exception:
        logging.error(traceback.format_exc())
    return score_pp


async def calculate_pp_for_beatmapset(beatmapset: Beatmapset, osu_config: Config, ignore_osu_cache: bool = False,
                                      mods: str = "+Nomod"):
    """ Calculates the pp for every difficulty in the given mapset, added
    to a "pp" key in the difficulty's dict. """
    # Init the cache of this mapset if it has not been created
    set_id = str(beatmapset.id)
    if set_id not in osu_config.data["map_cache"]:
        osu_config.data["map_cache"][set_id] = {}

    if not ignore_osu_cache:
        ignore_osu_cache = not bool(beatmapset.status in ("ranked", "approved"))

    cached_mapset = osu_config.data["map_cache"][set_id]

    for diff in beatmapset.beatmaps:
        map_id = str(diff.id)

        if ignore_osu_cache:
            # If the diff is cached and unchanged, use the cached pp
            if map_id in cached_mapset and mods in cached_mapset[map_id]:
                if diff.checksum == cached_mapset[map_id]["md5"]:
                    diff.add_max_pp(cached_mapset[map_id][mods]["pp"])
                    diff.difficulty_rating = cached_mapset[map_id][mods]["stars"]
                    diff.ar = cached_mapset[map_id][mods]["ar"]
                    diff.cs = cached_mapset[map_id][mods]["cs"]
                    diff.accuracy = cached_mapset[map_id][mods]["od"]
                    diff.drain = cached_mapset[map_id][mods]["hp"]
                    diff.add_new_bpm(cached_mapset[map_id][mods]["new_bpm"])
                    continue

                # If it was changed, add an asterisk to the beatmap name (this is a really stupid place to do this)
                diff.version = "".join(["*", diff.version])

        # If the diff is not cached, or was changed, calculate the pp and update the cache
        try:
            pp_stats = await calculate_pp(int(map_id), mods=mods, mode=diff.mode,
                                          ignore_osu_cache=ignore_osu_cache)
        except ValueError:
            logging.error(traceback.format_exc())
            continue

        diff.add_max_pp(pp_stats.pp)
        diff.difficulty_rating = pp_stats.stars
        diff.ar = pp_stats.ar
        diff.cs = pp_stats.cs
        diff.accuracy = pp_stats.od
        diff.drain = pp_stats.hp
        diff.add_new_bpm(diff.bpm * pp_stats.clock_rate)

        if ignore_osu_cache:
            # Cache the difficulty
            if map_id in cached_mapset:
                if diff.checksum != cached_mapset[map_id]["md5"]:
                    osu_config.data["map_cache"][set_id][map_id] = {
                        "md5": diff.checksum
                    }
            else:
                osu_config.data["map_cache"][set_id][map_id] = {
                    "md5": diff.checksum
                }
            if mods not in osu_config.data["map_cache"][set_id][map_id]:
                osu_config.data["map_cache"][set_id][map_id][mods] = {}
            osu_config.data["map_cache"][set_id][map_id][mods]["pp"] = pp_stats.pp
            osu_config.data["map_cache"][set_id][map_id][mods]["stars"] = pp_stats.stars
            osu_config.data["map_cache"][set_id][map_id][mods]["ar"] = pp_stats.ar
            osu_config.data["map_cache"][set_id][map_id][mods]["cs"] = pp_stats.cs
            osu_config.data["map_cache"][set_id][map_id][mods]["od"] = pp_stats.od
            osu_config.data["map_cache"][set_id][map_id][mods]["hp"] = pp_stats.hp
            osu_config.data["map_cache"][set_id][map_id][mods]["new_bpm"] = diff.bpm * pp_stats.clock_rate
    if ignore_osu_cache:
        await osu_config.asyncsave()


async def calculate_no_choke_top_plays(osu_scores: list):
    """ Calculates and returns a new list of unchoked plays. """
    mode = enums.GameMode.osu
    no_choke_list = []
    for osu_score in osu_scores:
        if osu_score.legacy_perfect:
            no_choke_list.append(osu_score)
            continue
        full_combo_acc = misc_utils.calculate_acc(mode, osu_score, exclude_misses=True)
        score_pp = await get_score_pp(osu_score, mode)
        if (score_pp.max_pp - osu_score.pp) > 10:
            osu_score.new_pp = f"""{utils.format_number(osu_score.pp, 2)} => {utils.format_number(
                score_pp.max_pp, 2)}"""
            osu_score.pp = score_pp.max_pp
            osu_score.legacy_perfect = True
            osu_score.accuracy = full_combo_acc
            osu_score.max_combo = score_pp.max_combo
            osu_score.statistics.great += osu_score.statistics.miss
            osu_score.statistics.miss = 0
            osu_score.rank = score_utils.get_no_choke_scorerank(osu_score.mods, full_combo_acc)
            osu_score.total_score = None
        no_choke_list.append(osu_score)
    no_choke_list.sort(key=itemgetter("pp"), reverse=True)

    return no_choke_list
