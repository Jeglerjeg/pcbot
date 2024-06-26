""" Plugin for copypastas

Commands:
    pasta
"""

import asyncio
from difflib import get_close_matches
from random import choice

import discord

import bot
import plugins
from pcbot import Config, Annotate, convert_to_embed

client = plugins.client  # type: bot.Client


pastas = Config("pastas", data={})
pasta_cache = {}  # list of generate_pasta tuples to cache
embed_color = discord.Color.dark_grey()


async def generate_pasta(name: str):
    """ Generate a pasta embed. """
    # Return the optionally cached result
    if name in pasta_cache:
        return pasta_cache[name]

    # Choose a random pasta when the name is .
    if name == ".":
        name = choice(list(pastas.data.keys()))

    # Remove spaces as pastas are space independent
    parsed_name = name.replace(" ", "")

    # Pasta might not be in the set
    assert parsed_name in pastas.data, f"Pasta `{name}` is undefined.\n Perhaps you meant: " \
                                       f"`{', '.join(get_close_matches(parsed_name, pastas.data.keys(), cutoff=0.5))}`?"

    text = pastas.data[parsed_name]
    embed = await convert_to_embed(text, color=embed_color)
    embed.set_footer(text="pasta: " + name)

    # Add the url to the message content itself when it's not an image
    content = None
    if embed.url and embed.image.url is None:
        content = embed.url + (" \N{EN DASH} " + embed.description if embed.description else "")
        embed = None  # Remove the embed as the image wouldn't embed otherwise

    # Cache the result and return
    generated = (embed, content)
    pasta_cache[name] = generated
    return generated


@plugins.command(aliases="paste")
async def pasta(message: discord.Message, name: Annotate.LowerContent):
    """ Use copypastas. Don't forget to enclose the copypasta in quotes: `"pasta goes here"` for multiline
        pasta action. You also need quotes around `<name>` if it has any spaces. """
    embed, content = await generate_pasta(name)
    await client.send_message(message.channel, content, embed=embed)


@pasta.command(aliases="a create set")
async def add(message: discord.Message, name: str.lower, copypasta: Annotate.Content):
    """ Add a pasta with the specified content. """
    # When creating pastas we don't use spaces either!
    parsed_name = name.replace(" ", "")

    assert parsed_name not in pastas.data, f"Pasta `{name}` already exists. "

    # If the pasta doesn't exist, set it
    pastas.data[parsed_name] = copypasta
    await pastas.asyncsave()
    await client.say(message, f"Pasta `{name}` set.")


@pasta.command(aliases="r delete")
async def remove(message: discord.Message, name: Annotate.LowerContent):
    """ Remove a pasta with the specified name. """
    # We don't even use spaces when removing pastas!
    parsed_name = name.replace(" ", "")

    assert parsed_name in pastas.data, f"No pasta with name `{name}`."

    copypasta = pastas.data.pop(parsed_name)
    await pastas.asyncsave()
    await client.say(message, f"Pasta `{name}` removed. In case this was a mistake, "
                              f"here's the pasta: ```{copypasta}```")


@plugins.event()
async def on_message(message: discord.Message):
    """ Use shorthand |<pasta ...> for displaying pastas and remove the user's message. """
    if message.content.startswith("|") and not message.content.startswith("||"):
        if message.channel.permissions_for(message.guild.me).manage_messages:
            asyncio.ensure_future(client.delete_message(message))
        embed, content = await generate_pasta(message.content[1:].lower())
        await client.send_message(message.channel, content, embed=embed)
        return True
