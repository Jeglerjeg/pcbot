""" Implement pp calculation features using rosu-pp python bindings.
    https://github.com/MaxOhn/rosu-pp-py
"""

import logging
import os
import traceback
from collections import namedtuple
from operator import itemgetter

from pcbot import utils, Config
from plugins.osulib import enums, api
from plugins.osulib.args import parse as parse_options
from plugins.osulib.models.beatmap import Beatmap, Beatmapset
from plugins.osulib.models.score import OsuScore
from plugins.osulib.utils import misc_utils, score_utils

try:
    import rosu_pp_py
except ImportError:
    rosu_pp_py = None

host = "https://osu.ppy.sh/"

CachedBeatmap = namedtuple("CachedBeatmap", "url_or_id beatmap")
PPStats = namedtuple("PPStats", "pp stars partial_stars max_pp max_combo ar cs od hp bpm")
ClosestPPStats = namedtuple("ClosestPPStats", "acc pp stars")

cache_path = "plugins/osulib/mapcache"
no_choke_cache = {}


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


async def calculate_pp(beatmap_url_or_id, *options, mode: enums.GameMode, ignore_osu_cache: bool = False,
                       failed: bool = False, potential: bool = False):
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

    mods_bitmask = sum(mod.value for mod in args.mods) if args.mods else 0

    calculator = rosu_pp_py.Calculator(beatmap_path)
    if args.ar:
        calculator.set_ar(args.ar)
    if args.od:
        calculator.set_od(args.od)
    if args.hp:
        calculator.set_hp(args.hp)
    if args.cs:
        calculator.set_cs(args.cs)
    score_params = rosu_pp_py.ScoreParams(mods=mods_bitmask, mode=mode.value)
    if args.clock_rate:
        score_params.clockRate = args.clock_rate

    # If the pp arg is given, return using the closest pp function
    if args.pp is not None and mode is enums.GameMode.osu:
        return await find_closest_pp(calculator, score_params, args)

    # Calculate the pp
    max_pp = None
    total_stars = None
    max_combo = None
    # Calculate maximum stars and pp
    if failed or potential:
        if args.potential_acc:
            score_params.acc = args.potential_acc
        [potential_pp_info] = calculator.calculate(score_params)
        max_combo = potential_pp_info.maxCombo
        total_stars = potential_pp_info.stars
        if mode is enums.GameMode.osu:
            max_pp = potential_pp_info.pp

    # Calculate actual stars and pp
    score_params = get_score_params(score_params, args)
    [pp_info] = calculator.calculate(score_params)
    if not max_combo:
        max_combo = pp_info.maxCombo

    pp = pp_info.pp
    total_stars = total_stars if failed else pp_info.stars
    partial_stars = pp_info.stars
    ar = pp_info.ar
    cs = pp_info.cs
    od = pp_info.od
    hp = pp_info.hp
    bpm = pp_info.bpm
    return PPStats(pp, total_stars, partial_stars, max_pp, max_combo, ar, cs, od, hp, bpm)


def get_score_params(score_params: rosu_pp_py.ScoreParams, args):
    if args.objects and args.objects > 0:
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


def get_beatmap_sr(score_pp: PPStats, beatmap: Beatmap, mods: str):
    """ Change beatmap SR if using SR adjusting mods. """
    difficulty_rating = score_pp.stars if \
        (mods not in ("Nomod", "HD", "FL", "TD", "ScoreV2", "NF", "SD", "PF", "RX") or not beatmap.convert) \
        and score_pp else beatmap.difficulty_rating
    return difficulty_rating


def calculate_total_user_pp(osu_scores: list[OsuScore], member_id: str, osu_tracking: dict):
    """ Calculates the user's total PP. """
    total_pp = 0
    for i, osu_score in enumerate(osu_scores):
        total_pp += osu_score.pp * (0.95 ** i)
    total_pp_without_bonus_pp = 0
    for osu_score in osu_scores:
        total_pp_without_bonus_pp += osu_score.weight["pp"]
    bonus_pp = osu_tracking[member_id]["new"]["statistics"]["pp"] - total_pp_without_bonus_pp
    return total_pp + bonus_pp


async def get_score_pp(osu_score: OsuScore, mode: enums.GameMode, beatmap: Beatmap = None):
    """ Return PP for a given score. """
    score_pp = None
    try:
        score_pp = await calculate_pp(beatmap.id if beatmap else osu_score.beatmap_id, mode=mode,
                                      ignore_osu_cache=not bool(beatmap.status == "ranked"
                                                                or beatmap.status == "approved") if beatmap
                                      else False,
                                      potential=score_utils.calculate_potential_pp(osu_score, mode),
                                      failed=not osu_score.passed, *score_utils.process_score_args(osu_score))
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
        ignore_osu_cache = not bool(beatmapset.status == "ranked" or beatmapset.status == "approved")

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
            pp_stats = await calculate_pp(int(map_id), mods, mode=diff.mode,
                                          ignore_osu_cache=ignore_osu_cache)
        except ValueError:
            logging.error(traceback.format_exc())
            continue

        diff.add_max_pp(pp_stats.pp)
        diff.difficulty_rating = pp_stats.stars
        diff.ar = pp_stats.ar
        diff.cs = pp_stats.cs
        diff.accuracy = pp_stats.od
        diff.accuracy = pp_stats.hp
        diff.add_new_bpm(pp_stats.bpm)

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
            osu_config.data["map_cache"][set_id][map_id][mods]["new_bpm"] = pp_stats.bpm
    if ignore_osu_cache:
        await osu_config.asyncsave()


async def calculate_no_choke_top_plays(osu_scores: list, member_id: str):
    """ Calculates and returns a new list of unchoked plays. """
    mode = enums.GameMode.osu
    no_choke_list = []
    if member_id not in no_choke_cache:
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
                osu_score.statistics.great = osu_score.statistics.great +\
                    osu_score.statistics.great
                osu_score.statistics.miss = 0
                osu_score.rank = score_utils.get_no_choke_scorerank(osu_score.mods, full_combo_acc)
                osu_score.total_score = None
            no_choke_list.append(osu_score)
        no_choke_list.sort(key=itemgetter("pp"), reverse=True)
        for i, osu_score in enumerate(no_choke_list):
            osu_score.position = i + 1
        no_choke_cache[member_id] = no_choke_list
        no_chokes = no_choke_cache[member_id]
    else:
        no_chokes = no_choke_cache[member_id]
    return no_chokes
