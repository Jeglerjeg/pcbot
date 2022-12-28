import discord

from plugins.osulib import enums, pp, api
from plugins.osulib.formatting import score_format
from plugins.osulib.models.beatmap import Beatmap
from plugins.osulib.models.score import OsuScore
from plugins.osulib.utils import user_utils, score_utils


def get_embed_from_template(description: str, color: discord.Colour, author_text: str, author_url: str,
                            author_icon: str, thumbnail_url: str = "", time: str = "", potential_string: str = "",
                            completion_rate: str = ""):
    embed = discord.Embed(color=color)
    embed.description = description
    embed.set_author(name=author_text, url=author_url, icon_url=author_icon)
    if thumbnail_url:
        embed.set_thumbnail(url=thumbnail_url)
    footer = []
    if potential_string:
        footer.append(potential_string)
    if completion_rate:
        footer.append(completion_rate)
    if time:
        footer.append(time)
    embed.set_footer(text="\n".join(footer))
    return embed


async def create_score_embed_with_pp(member: discord.Member, osu_score: OsuScore, beatmap: Beatmap,
                                     mode: enums.GameMode, osu_tracking: dict, twitch_link: bool = False,
                                     time: bool = False):
    """ Returns a score embed for use outside of automatic score notifications. """
    score_pp = await pp.get_score_pp(osu_score, mode, beatmap)
    mods = enums.Mods.format_mods(osu_score.mods)

    if score_pp is not None and (osu_score.pp is None or osu_score.pp == 0):
        osu_score.pp = score_pp.pp
    elif osu_score.pp is None:
        osu_score.pp = 0
    if score_pp is not None:
        beatmap.difficulty_rating = pp.get_beatmap_sr(score_pp, beatmap, mods)
        beatmap.max_combo = score_pp.max_combo
    if (not hasattr(beatmap, "max_combo") or not beatmap.max_combo) and score_pp and score_pp.max_combo:
        beatmap.add_max_combo(score_pp.max_combo)

    # There might not be any events
    if str(member.id) in osu_tracking and "new" in osu_tracking[str(member.id)] \
            and osu_tracking[str(member.id)]["new"]["events"]:
        osu_score.rank_global = api.rank_from_events(osu_tracking[str(member.id)]["new"]["events"],
                                                     str(beatmap.id), osu_score)

    time_string = ""
    if time:
        time_string = score_format.get_formatted_score_time(osu_score)
    embed = get_embed_from_template(await score_format.format_new_score(mode, osu_score, beatmap,
                                                                        member if twitch_link else None),
                                    member.color, osu_score.user["username"],
                                    user_utils.get_user_url(str(member.id)),
                                    osu_score.user["avatar_url"],
                                    osu_score.beatmapset.covers.list2x
                                    if hasattr(osu_score, "beatmapset") and osu_score["beatmapset"]
                                    else beatmap.beatmapset.covers.list2x,
                                    time=time_string,
                                    potential_string=score_format.format_potential_pp(
                                        score_pp if score_pp is not None else None,
                                        osu_score) if score_utils.calculate_potential_pp(osu_score, mode) else "",
                                    completion_rate=score_format.format_completion_rate(osu_score,
                                                                                        score_pp if
                                                                                        score_pp is not None
                                                                                        and not
                                                                                        bool(
                                                                                            osu_score.legacy_perfect
                                                                                            and
                                                                                            osu_score.passed
                                                                                        )
                                                                                        else None))
    return embed
