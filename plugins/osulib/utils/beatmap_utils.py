import discord

from pcbot import utils
from plugins.osulib import api, enums
from plugins.osulib.constants import host


async def find_beatmap_info(channel: discord.TextChannel):
    beatmap_info = None
    async for m in channel.history():
        to_search = [m.content]
        if m.embeds:
            for embed in m.embeds:
                to_search.append(embed.description if embed.description else "")
                to_search.append(embed.title if embed.title else "")
                to_search.append(embed.footer.text if embed.footer else "")
        found_url = utils.http_url_pattern.search("".join(to_search))
        if found_url:
            try:
                beatmap_info = await api.beatmap_from_url(found_url.group(), return_type="info")
                break
            except SyntaxError:
                continue
    return beatmap_info


def get_beatmap_url(beatmap_id: int, mode: enums.GameMode):
    """ Return the beatmap's url. """
    return f"{host}beatmaps/{beatmap_id}?mode={mode.name}"
