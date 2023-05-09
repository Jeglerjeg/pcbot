import discord


def get_embed_from_template(description: str, color: discord.Colour, author_text: str, author_url: str,
                            author_icon: str, thumbnail_url: str = "", time: str = ""):
    embed = discord.Embed(color=color)
    embed.description = description
    embed.set_author(name=author_text, url=author_url, icon_url=author_icon)
    if thumbnail_url:
        embed.set_thumbnail(url=thumbnail_url)
    footer = []
    if time:
        footer.append(time)
    embed.set_footer(text="\n".join(footer))
    return embed