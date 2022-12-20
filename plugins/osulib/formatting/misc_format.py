import logging
import traceback

import discord

from pcbot import utils
from plugins.osulib import enums
from plugins.osulib.constants import host
from plugins.osulib.models.beatmap import Beatmap
from plugins.osulib.models.score import OsuScore
from plugins.osulib.utils import misc_utils
from plugins.twitchlib import twitch


def format_mode_name(mode: enums.GameMode, short_name: bool = False, abbreviation: bool = False):
    """ Return formatted mode name for user facing modes. """
    name = ""
    if mode is enums.GameMode.osu:
        if not short_name:
            name = "osu!"
        elif short_name:
            name = "S"
    elif mode is enums.GameMode.mania:
        if not short_name and not abbreviation:
            name = "osu!mania"
        elif short_name:
            name = "M"
        elif abbreviation:
            name = "o!m"
    elif mode is enums.GameMode.taiko:
        if not short_name and not abbreviation:
            name = "osu!taiko"
        elif short_name:
            name = "T"
        elif abbreviation:
            name = "o!t"
    elif mode is enums.GameMode.fruits:
        if not short_name and not abbreviation:
            name = "osu!catch"
        elif short_name:
            name = "C"
        elif abbreviation:
            name = "o!c"
    return name


def format_user_diff(mode: enums.GameMode, data_old: dict, data_new: dict):
    """ Get a bunch of differences and return a formatted string to send.
    iso is the country code. """
    pp_rank = int(data_new["statistics"]["global_rank"]) if data_new["statistics"]["global_rank"] else 0
    pp_country_rank = int(data_new["statistics"]["country_rank"]) if data_new["statistics"]["country_rank"] else 0
    iso = data_new["country"]["code"]
    rank = -int(misc_utils.get_diff(data_old, data_new, "global_rank"))
    country_rank = -int(misc_utils.get_diff(data_old, data_new, "country_rank"))
    accuracy = misc_utils.get_diff(data_old, data_new, "hit_accuracy")
    pp_diff = misc_utils.get_diff(data_old, data_new, "pp")
    ranked_score = misc_utils.get_diff(data_old, data_new, "ranked_score")
    rankings_url = f"{host}/rankings/osu/performance"

    # Find the performance page number of the respective ranks

    formatted = [f"\u2139`{format_mode_name(mode, abbreviation=True)} "
                 f"{utils.format_number(data_new['statistics']['pp'], 2)}pp "
                 f"{utils.format_number(pp_diff, 2):+}pp`",
                 f" [\U0001f30d]({rankings_url}?page="
                 f"{pp_rank // 50 + 1})`#{pp_rank:,}{'' if int(rank) == 0 else f' {int(rank):+}'}`",
                 f" [{utils.text_to_emoji(iso)}]({rankings_url}?country={iso}&page="
                 f"{pp_country_rank // 50 + 1})`"
                 f"#{pp_country_rank:,}{'' if int(country_rank) == 0 else f' {int(country_rank):+}'}`"]
    rounded_acc = utils.format_number(accuracy, 3)
    if rounded_acc > 0:
        formatted.append("\n\U0001f4c8")  # Graph with upwards trend
    elif rounded_acc < 0:
        formatted.append("\n\U0001f4c9")  # Graph with downwards trend
    else:
        formatted.append("\n\U0001f3af")  # Dart

    formatted.append(f"`{utils.format_number(data_new['statistics']['hit_accuracy'], 3)}%"
                     f"{'' if rounded_acc == 0 else f' {rounded_acc:+}%'}`")

    formatted.append(f' \U0001f522`{data_new["statistics"]["ranked_score"]:,}'
                     f'{"" if ranked_score == 0 else f" {int(ranked_score):+,}"}`')

    return "".join(formatted)


async def format_stream(member: discord.Member, osu_score: OsuScore, beatmap: Beatmap):
    """ Format the stream url and a VOD button when possible. """
    stream_url = None
    for activity in member.activities:
        if activity and activity.type == discord.ActivityType.streaming and hasattr(activity, "platform") \
                and activity.platform.lower() == "twitch":
            stream_url = activity.url
    if not stream_url:
        return ""

    # Add the stream url and return immediately if twitch is not setup
    text = [f"**[Watch live]({stream_url})**"]
    if not twitch.twitch_client:
        text.append("\n")
        return "".join(text)

    # Try getting the vod information of the current stream
    try:
        twitch_id = await twitch.get_id(member)
        vod_request = await twitch.get_videos(twitch_id)
        assert len(vod_request) >= 1
    except Exception:
        logging.error(traceback.format_exc())
        text.append("\n")
        return "".join(text)

    vod = vod_request[0]

    # Find the timestamp of where the play would have started without pausing the game
    vod_created = vod.created_at

    # Return if the stream was started after the score was set
    if vod_created > osu_score.ended_at:
        text.append("\n")
        return "".join(text)

    # Convert beatmap length when speed mods are enabled
    mods = enums.Mods.format_mods(osu_score.mods)
    if "DT" in mods or "NC" in mods:
        beatmap.hit_length /= 1.5
    elif "HT" in mods:
        beatmap.hit_length /= 0.75

    # Get the timestamp in the VOD when the score was created
    timestamp_score_created = (osu_score.ended_at - vod_created).total_seconds()
    timestamp_play_started = timestamp_score_created - beatmap.hit_length

    # Add the vod url with timestamp to the formatted text
    text.append(f" | **[`Video of this play`]({vod.url}?t={int(timestamp_play_started)}s)**\n")
    return "".join(text)
