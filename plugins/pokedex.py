""" Plugin that would act as a pokédex, specifically designed for Pokémon GO.

Commands:
    pokedex
"""

import json
import logging
import os
from collections import defaultdict
from difflib import get_close_matches
from io import BytesIO
from operator import itemgetter

import discord

import bot
import plugins
from pcbot import Config, Annotate, guild_command_prefix, utils

try:
    from PIL import Image
except:
    resize = False
    logging.warning("PIL could not be loaded. The pokedex works like usual, however sprites will remain 1x scaled.")
else:
    resize = True

client = plugins.client  # type: bot.Client

api_path = "plugins/pokedexlib/pokedex.json"
sprites_path = "plugins/pokedexlib/sprites/"
pokedex_config = Config("pokedex", data=defaultdict(dict))
default_scale_factor = 1.0
min_scale_factor, max_scale_factor = 0.25, 4

pokemon_go_gen = [1, 2, 3, 4, 5, 6]

# Load the Pokedex API
with open(api_path, encoding="utf-8") as api_file:
    api = json.load(api_file)
    pokedex = api["pokemon"]

# Load all our sprites into RAM (they don't take much space)
# Unlike the pokedex.json API, these use pokemon ID as keys.
# The values are the sprites in bytes.
sprites = {}
for file in os.listdir(sprites_path):
    with open(os.path.join(sprites_path, file), "rb") as sprite_bytes:
        sprites[int(file.split(".")[0])] = sprite_bytes.read()


def id_to_name(pokemon_id: int):
    """ Convert the pokemon ID to a name. """
    for name, pokemon in pokedex.items():
        if pokemon["id"] == pokemon_id:
            return name

    return None


def egg_name(pokemon_evolution: list):
    """ Return the egg name of the pokemon_evolution chain. """
    # The pokemon are in their respective order, so we'll find the first one with
    # a Pokemon GO generation pokemon
    for names in pokemon_evolution:
        for name in names:
            pokemon = pokedex[name]

            if pokemon["generation"] in pokemon_go_gen:
                return pokemon["locale_name"]

    return "Unknown"


def resize_sprite(sprite, factor: float):
    """ Resize a sprite (string of bytes / rb). """
    image = Image.open(BytesIO(sprite))

    # Resize with the scaled proportions
    width, height = image.size
    width, height = int(width * factor), int(height * factor)
    image = image.resize((width, height), Image.NEAREST)

    # Return the byte-like object
    return utils.convert_image_object(image)


def format_type(*types):
    """ Format a string from a list of a pokemon's types. """
    return " | ".join(t.capitalize() for t in types if t is not None)


def get_pokemon(name_or_id: str, assert_on_error: bool = True):
    """ Returns a pokemon with the given name or id string. """
    # Get the requested pokemon name
    name = name_or_id
    try:
        pokemon_id = int(name_or_id)
    except ValueError:
        # See if there's a pokemon with the locale name formatted like the given name
        for pokemon in pokedex.values():
            if pokemon["locale_name"].lower() == name:
                name = pokemon["name"]
                break

        # Correct the name if it is very close to an existing pokemon and there's only one close match
        matches = get_close_matches(name, pokedex.keys(), n=2, cutoff=0.8)
        if matches and len(matches) == 1:
            name = matches[0]

        if name not in pokedex:
            assert not assert_on_error, \
                f"There is no pokémon called **{name}** in my pokédex!\nPerhaps you meant: " \
                f"`{', '.join(get_close_matches(name, pokedex.keys(), cutoff=0.5))}`?"
            return None
    else:
        name = id_to_name(pokemon_id)

        if name is None:
            assert not assert_on_error, f"There is no pokémon with ID **#{pokemon_id:03}** in my pokédex!"
            return None

    return name


@plugins.command(name="pokedex", aliases="pd pokemon dex")
async def pokedex_(message: discord.Message, name_or_id: Annotate.LowerCleanContent):
    """ Display some information of the given pokémon.

    **Examples**: <http://imgur.com/a/lqG9c> """
    # Do some quick replacements for flexible parsing
    name_or_id = name_or_id.strip()

    if name_or_id.startswith("#"):
        name_or_id = name_or_id.replace("#", "")
    if " " in name_or_id:
        if "♀" in name_or_id or "♀" in name_or_id or name_or_id.endswith("f") or name_or_id.endswith("m"):
            name_or_id = name_or_id.replace(" ", "-").replace("♂", "m").replace("♀", "f")
        else:
            name_or_id = name_or_id.replace(" ", "")

    # Get the name of the specified pokemon
    name = get_pokemon(name_or_id)

    # Assign our pokemon
    pokemon = pokedex[name]

    # Send an image if the bots has Attach Files permission or the message is a dm
    if message.guild is None or message.channel.permissions_for(message.guild.me).attach_files:
        # Get the guild's scale factor
        if not isinstance(message.channel, discord.abc.PrivateChannel) \
                and message.guild.id in pokedex_config.data and "scale-factor" in pokedex_config.data[message.guild.id]:
            scale_factor = pokedex_config.data[message.guild.id]["scale-factor"]
        else:
            scale_factor = default_scale_factor

        # Assign our pokemon
        pokemon = pokedex[name]

        # Assign the sprite to use
        if pokemon["id"] in sprites:
            sprite = sprites[pokemon["id"]]
        else:
            sprite = sprites[0]

        # Resize (if PIL is enabled) and upload the sprite
        if resize and not round(scale_factor, 2) == 1:
            sprite = resize_sprite(sprite, scale_factor)
        elif resize:
            sprite = BytesIO(sprite)

    # Format Pokemon GO specific info
    pokemon_go_info = ""
    if "evolution_cost" in pokemon:
        pokemon_go_info += f'Evolution cost: `{ pokemon["evolution_cost"]} {egg_name(pokemon["evolution"])} Candy` '

    if "hatches_from" in pokemon:
        if pokemon_go_info:
            pokemon_go_info += "\n"
        pokemon_go_info += f"Hatches from: `{pokemon['hatches_from']}km Egg` "

    # Format the message
    formatted_message = (
        "**#{id:03} {upper_name} - GEN {generation}**\n"
        "**{genus}**\n"
        "Weight: `{weight}kg` Height: `{height}m`\n"
        "Type: `{type}`\n"
        "{pokemon_go}"
        "```\n{description}```"
        "**EVOLUTIONS**: {formatted_evolution}"
    ).format(
        upper_name=pokemon["locale_name"].upper(),
        type=format_type(*pokemon["types"]),
        formatted_evolution=" **->** ".join(" **/** ".join(pokedex[name]["locale_name"].upper() for name in names)
                                            for names in pokemon["evolution"]),
        pokemon_go=pokemon_go_info,
        **pokemon
    )
    embed = discord.Embed(color=message.author.color)
    embed.set_image(url=f"attachment://{name}.png")
    embed.description = formatted_message

    await client.send_message(message.channel, file=(discord.File(sprite, filename=f"{name}.png")), embed=embed)


@pokedex_.command()
async def egg(message: discord.Message, egg_type: Annotate.LowerCleanContent):
    """ Get the pokemon hatched from the specified egg_type
    (in distance, e.g. 2 or 5km) """
    # Strip any km suffix (or prefix, whatever)
    egg_type = egg_type.replace("km", "")

    try:
        distance = int(float(egg_type))  # Using float for anyone willing to type 2.0km
    except ValueError:
        await client.say(message, f"The egg type **{egg_type}** is invalid.")
        return

    pokemon_criteria = []
    egg_types = []

    # Find all pokemon with the specified distance
    for pokemon in sorted(pokedex.values(), key=itemgetter("id")):
        # We've exceeded the generation and no longer need to search
        if pokemon["generation"] not in pokemon_go_gen:
            break

        if "hatches_from" not in pokemon:
            continue

        if pokemon["hatches_from"] not in egg_types:
            egg_types.append(pokemon["hatches_from"])

        if pokemon["hatches_from"] == distance:
            pokemon_criteria.append(pokemon["locale_name"])

    # The list might be empty
    assert pokemon_criteria, f"No pokemon hatch from a **{distance}km** egg. **Valid distances are** " \
                             f'```\n{", ".join(f"{s}km" for s in sorted(egg_types))}```'

    # Respond with the list of matching criteria
    await client.say(message, f"**The following Pokémon may hatch from a {distance}km egg**:"
                              f"```\n{', '.join(sorted(pokemon_criteria))}```")


def assert_type(slot: str, guild: discord.Guild):
    """ Assert if a type does not exist, and show the valid types. """
    match = get_close_matches(slot, api["types"], n=1, cutoff=0.4)

    if match:
        matches_string = f" Perhaps you meant `{match[0]}`?"
    else:
        matches_string = f" See `{guild_command_prefix(guild)}help pokedex type`."
    assert slot in api["types"], f"**{slot.capitalize()}** is not a valid pokemon type.{matches_string}"


types_str = f'**Valid types are** ```\n{", ".join(s.capitalize() for s in api["types"])}```'


def attack_method(pokemon_type):
    """ Iterate through the pokemon type's attack damage factor. """
    for damage_type, damage in api["types"][pokemon_type]["damage_factor"].items():
        yield damage_type, damage


def defense_method(pokemon_type):
    """ Iterate through the pokemon type's defense damage factor. """
    for value in api["types"].values():
        yield value["name"], value["damage_factor"][pokemon_type]


def resolve_damage_factor(method, type_1: str, type_2: str = None):
    """ Combine the damage factors when there are two types. """
    damage_factor = {k: 0 for k in api["types"].keys()}

    if not type_2:
        for damage_type, damage in method(type_1):
            damage_factor[damage_type] = damage
    else:
        for damage_type_1, damage_1 in method(type_1):
            for damage_type_2, damage_2 in method(type_2):
                if damage_type_1 == damage_type_2:
                    damage_factor[damage_type_1] = damage_1 * damage_2

    return damage_factor


def format_damage(method, type_1: str, type_2: str = None):
    """ Formats the effective, ineffective and no effect lists with type names
    based on the damage factor.
    """
    damage_factor = resolve_damage_factor(method, type_1, type_2)
    effective, ineffective, useless = [], [], []

    for damage_type, damage in damage_factor.items():
        name = damage_type.capitalize()

        if damage == 4:
            effective.append(name + " x2")
        elif damage == 2:
            effective.append(name)
        elif damage == 0.5:
            ineffective.append(name)
        elif damage == 0.25:
            ineffective.append(name + " x2")
        elif damage == 0:
            useless.append(name)

    return effective, ineffective, useless


def format_specific_efficacy(method, type_1: str, type_2: str = None):
    """ Format the efficacy string specifically for defense or attack. """
    effective, ineffective, useless = format_damage(method, type_1, type_2)
    type_name = format_type(type_1, type_2)
    s = f'**{type_name}** \N{EN DASH} **{"DEFENSE" if method is defense_method else "ATTACK"}**\n'
    if effective:
        s += f"Super effective: `{', '.join(effective)}`\n"
    if ineffective:
        s += f"Not very effective: `{', '.join(ineffective)}`\n"
    if useless:
        s += f"No effect: `{', '.join(useless)}`\n"

    return s


def format_efficacy(type_1: str, type_2: str = None):
    """ Format an efficacy string so that we can use this function for
    multiple commands. """
    efficacy = format_specific_efficacy(attack_method, type_1, type_2)
    efficacy += format_specific_efficacy(defense_method, type_1, type_2)
    return efficacy.strip("\n")


@pokedex_.command(name="type", description=f"Show pokemon with the specified types. {types_str}")
async def filter_type(message: discord.Message, slot_1: str.lower, slot_2: str.lower = None):
    matched_pokemon = []
    assert_type(slot_1, message.guild)

    # Find all pokemon with the matched criteria
    if slot_2:
        assert_type(slot_2, message.guild)

        # If two slots are provided, search for pokemon with both types matching
        for pokemon in pokedex.values():
            if pokemon["types"] == [slot_1, slot_2]:
                matched_pokemon.append(pokemon["locale_name"])
    else:
        # All pokemon have a type in their first slot, so check if these are equal
        for pokemon in pokedex.values():
            if pokemon["types"][0] == slot_1:
                matched_pokemon.append(pokemon["locale_name"])

    # There might not be any pokemon with the specified types
    assert matched_pokemon, f"Looks like there are no pokemon of type **{format_type(slot_1, slot_2)}**!"

    await client.say(message, f"**Pokemon with type {format_type(slot_1, slot_2)}**: "
                              f"```\n{', '.join(sorted(matched_pokemon))}```")


@pokedex_.command(aliases="e",
                  description=f"Display type efficacy (effectiveness) of the specified type or pokemon. {types_str}")
async def effect(message: discord.Message, slot_1_or_pokemon: str.lower, slot_2: str.lower = None):
    name = get_pokemon(slot_1_or_pokemon, assert_on_error=False)
    formatted = ""
    if name:
        types = pokedex[name]["types"]
        slot_1 = types[0]
        if len(types) > 1:
            slot_2 = types[1]
        formatted += f"Using types of **{name.capitalize()}**:\n\n"
    else:
        slot_1 = slot_1_or_pokemon

    assert_type(slot_1, message.guild)
    if slot_2:
        assert_type(slot_2, message.guild)

    formatted += format_efficacy(slot_1, slot_2)
    await client.say(message, formatted)


@pokedex_.command(disabled_pm=True, aliases="sf", permissions="manage_guild")
async def scalefactor(message: discord.Message, factor: float = default_scale_factor):
    """ Set the image scaling factor for your guild. If no factor is given, the default is set. /
    **This command requires the `Manage Guild` permission.**"""
    assert factor != 0, "If you wish to disable images, remove the `Attach Files` permission from this bot."

    assert factor <= max_scale_factor, f"The factor **{factor}** is too high **(max={max_scale_factor})**."
    assert min_scale_factor <= factor, f"The factor **{factor}** is too low **(min={min_scale_factor})**."

    if message.guild.id not in pokedex_config.data:
        pokedex_config.data[message.guild.id] = {}

    # Handle specific scenarios
    if factor == default_scale_factor:
        if "scale-factor" in pokedex_config.data[message.guild.id]:
            del pokedex_config.data[message.guild.id]["scale-factor"]
            reply = "Pokédex image scale factor reset to default: **{factor}**."
        else:
            reply = "Pokédex image scale factor is **{factor}** (default)."
    else:
        pokedex_config.data[message.guild.id]["scale-factor"] = factor
        reply = "Pokédex image scale factor set to **{factor}**."

    await pokedex_config.asyncsave()
    await client.say(message, reply.format(factor=factor))
