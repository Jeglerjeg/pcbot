import discord

from pcbot import utils
from plugins.osulib import enums
from plugins.osulib.constants import max_diff_length, host
from plugins.osulib.formatting.misc_format import format_mode_name


async def format_beatmapset_diffs(beatmapset: dict):
    """ Format some difficulty info on a beatmapset. """
    # Get the longest difficulty name
    diff_length = len(max((diff["version"] for diff in beatmapset["beatmaps"]), key=len))
    if diff_length > max_diff_length:
        diff_length = max_diff_length
    elif diff_length < len("difficulty"):
        diff_length = len("difficulty")

    m = ["```elm\n"
         f"M {'Difficulty': <{diff_length}}  Stars  Drain  PP"]

    for diff in sorted(beatmapset["beatmaps"], key=lambda d: float(d["difficulty_rating"])):
        diff_name = diff["version"]
        length = divmod(int(diff["hit_length"] / (diff["new_bpm"] / diff["bpm"])), 60)
        m.append("\n{gamemode: <2}{name: <{diff_len}}  {stars: <7}{drain: <7}{pp}".format(
            gamemode=format_mode_name(enums.GameMode(int(diff["mode_int"])), short_name=True),
            name=diff_name if len(diff_name) < max_diff_length else diff_name[:max_diff_length - 3] + "...",
            diff_len=diff_length,
            stars=f"{utils.format_number(float(diff['difficulty_rating']), 2)}\u2605",
            pp=f"{int(diff.get('pp', '0'))}pp",
            drain=f"{length[0]}:{length[1]:02}")
        )
    m.append("```")
    return "".join(m)


async def format_beatmap_info(diff: dict, mods: str):
    """ Format some difficulty info on a beatmapset. """
    # Get the longest difficulty name
    diff_length = len(diff["version"])
    if diff_length > max_diff_length:
        diff_length = max_diff_length
    elif diff_length < len("difficulty"):
        diff_length = len("difficulty")

    m = [f"```elm\n{'Difficulty': <{diff_length}}  Drain  BPM  Passrate"]

    diff_name = diff["version"]
    length = divmod(int(diff["hit_length"] / (diff["new_bpm"] / diff["bpm"])), 60)
    pass_rate = "Not passed"
    if not diff["passcount"] == 0 and not diff["playcount"] == 0:
        pass_rate = f"{(diff['passcount'] / diff['playcount']) * 100:.2f}%"

    m.append("\n{name: <{diff_len}}  {drain: <7}{bpm: <5}{passrate}\n\n"
             "OD   CS   AR   HP   Max Combo  Mode\n"
             "{od: <5}{cs: <5}{ar: <5}{hp: <5}{maxcombo: <11}{mode_name}\n\n"
             "Total PP   Total Stars   Mods\n"
             "{pp: <11}{stars: <14}{mods}".format(
              name=diff_name if len(diff_name) < max_diff_length else diff_name[:max_diff_length - 3] + "...",
              diff_len=diff_length,
              stars=f"{utils.format_number(float(diff['difficulty_rating']), 2)}\u2605",
              pp=f"{int(diff.get('pp', '0'))}pp",
              drain=f"{length[0]}:{length[1]:02}",
              passrate=pass_rate,
              od=utils.format_number(float(diff["accuracy"]), 1),
              ar=utils.format_number(float(diff["ar"]), 1),
              hp=utils.format_number(float(diff["drain"]), 1),
              cs=utils.format_number(float(diff["cs"]), 1),
              bpm=int(diff["new_bpm"]) if diff["new_bpm"] else diff["bpm"],
              maxcombo=f"{diff['max_combo']}x" if diff["max_combo"] else "None",
              mode_name=format_mode_name(enums.GameMode.get_mode(diff["mode"])),
              mods=mods.upper() if not mods == "+Nomod" else mods
             ))

    m.append("```")
    return "".join(m)


async def format_map_status(member: discord.Member, status_format: str, beatmapset: dict, minimal: bool,
                            user_id: int = None, mods: str = "+Nomod"):
    """ Format the status update of a beatmap. """
    if user_id:
        name = member.display_name
    else:
        user_id = beatmapset["user_id"]
        name = beatmapset["creator"]
    status = [status_format.format(name=name, user_id=user_id, host=host, artist=beatmapset["artist"],
                                   title=beatmapset["title"], id=beatmapset["id"])]
    if not minimal:
        beatmap = bool(len(beatmapset["beatmaps"]) == 1)
        if not beatmap:
            status.append(await format_beatmapset_diffs(beatmapset))
        else:
            status.append(await format_beatmap_info(beatmapset["beatmaps"][0], mods))

    embed = discord.Embed(color=member.color, description="".join(status))
    embed.set_image(url=beatmapset["covers"]["cover@2x"])
    return embed
