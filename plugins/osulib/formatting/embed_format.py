import discord

from plugins.osulib import enums, pp, api
from plugins.osulib.formatting import score_format
from plugins.osulib.utils import user_utils


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


async def create_score_embed_with_pp(member: discord.Member, osu_score: dict, beatmap: dict,
                                     mode: enums.GameMode, osu_tracking: dict, scoreboard_rank: bool = False,
                                     twitch_link: bool = False, time: bool = False):
    """ Returns a score embed for use outside of automatic score notifications. """
    score_pp = await pp.get_score_pp(osu_score, mode, beatmap)
    mods = enums.Mods.format_mods(osu_score["mods"])

    if score_pp is not None and osu_score["pp"] is None:
        osu_score["pp"] = score_pp.pp
    elif osu_score["pp"] is None:
        osu_score["pp"] = 0
    if score_pp is not None:
        beatmap["difficulty_rating"] = pp.get_beatmap_sr(score_pp, beatmap, mods)
    if ("max_combo" not in beatmap or not beatmap["max_combo"]) and score_pp and score_pp.max_combo:
        beatmap["max_combo"] = score_pp.max_combo

    # There might not be any events
    if scoreboard_rank is False and str(member.id) in osu_tracking and "new" in osu_tracking[str(member.id)] \
            and osu_tracking[str(member.id)]["new"]["events"]:
        scoreboard_rank = api.rank_from_events(osu_tracking[str(member.id)]["new"]["events"],
                                               str(osu_score["beatmap"]["id"]), osu_score)

    time_string = ""
    if time:
        time_string = score_format.get_formatted_score_time(osu_score)

    embed = get_embed_from_template(await score_format.format_new_score(mode, osu_score, beatmap,
                                                                        scoreboard_rank,
                                                                        member if twitch_link else None),
                                    member.color, osu_score["user"]["username"],
                                    user_utils.get_user_url(str(member.id)),
                                    osu_score["user"]["avatar_url"],
                                    osu_score["beatmapset"]["covers"]["list@2x"]
                                    if bool("beatmapset" in osu_score)
                                    else beatmap["beatmapset"]["covers"]["list@2x"],
                                    time=time_string,
                                    potential_string=score_format.format_potential_pp(
                                        score_pp if score_pp is not None and not bool(osu_score["perfect"]
                                                                                      and osu_score["passed"])
                                        else None,
                                        osu_score),
                                    completion_rate=score_format.format_completion_rate(osu_score,
                                                                                        score_pp if
                                                                                        score_pp is not None
                                                                                        and not
                                                                                        bool(
                                                                                            osu_score["perfect"]
                                                                                            and
                                                                                            osu_score["passed"]
                                                                                        )
                                                                                        else None))
    return embed
