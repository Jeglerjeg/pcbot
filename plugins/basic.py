""" Plugin for basic commands

Commands:
    roll
    feature
"""

import random
from re import match

import discord

import bot
import plugins
from pcbot import utils, Config, Annotate

client = plugins.client  # type: bot.Client

feature_reqs = Config(filename="feature_requests", data={})


@plugins.command()
async def roll(message: discord.Message, num: utils.int_range(f=1) = 100):
    """ Roll a number from 1-100 if no second argument or second argument is not a number.
        Alternatively rolls `num` times (minimum 1). """
    rolled = random.randint(1, num)
    await client.say(message, f"**{message.author.display_name}** rolls `{rolled}`.")


@plugins.argument("{open}<num>[x<sides>]{suffix}{close}")
def dice_roll(arg: str):
    """ Dice roll as number of rolls (eg 6) or as num and sides (2x6)"""
    num, sides = 1, 6

    if arg.count("x") > 1:
        return None

    if "x" in arg:
        num, sides = arg.split("x")
    else:
        num = arg

    try:
        num = int(num)
        sides = int(sides)
    except ValueError:
        return None

    if num < 1 or sides < 1:
        return None

    return num, sides


@plugins.command()
async def dice(message: discord.Message, num_and_sides: dice_roll = (1, 6)):
    """ Roll an n-dimensional dice 1 or more times. """
    rolls = []
    num, sides = num_and_sides

    for _ in range(num):
        rolls.append(random.randint(1, sides))

    await client.say(message, f"**{message.author.display_name}** rolls `[{', '.join(str(r)for r in rolls)}]`")


@plugins.command()
async def rate(message: discord.Message, to_rate: str = None):
    """ Rate the member or word from 1 to 10 """
    if not to_rate:
        member = message.author
    else:
        member = utils.find_member(guild=message.guild, name=to_rate)
    if member:
        random.seed(str(member.id))
        num = random.randint(0, 10)
        random.seed()
        await client.say(message, f"I rate **{member.display_name}** a **{num}/10**")
    else:
        random.seed(to_rate.lower())
        num = random.randint(0, 10)
        random.seed()
        await client.say(message, f"I rate **{to_rate}** a **{num}/10**")


@plugins.command()
async def avatar(message: discord.Message, member: discord.Member = Annotate.Self):
    """ Display your or another member's avatar. """
    e = discord.Embed(color=member.color)
    e = e.set_image(url=member.display_avatar.url)
    e.set_author(name=member.display_name, icon_url=member.display_avatar.url)
    await client.send_message(message.channel, embed=e)


@plugins.argument("#{open}feature_id{suffix}{close}")
def get_req_id(feature_id: str):
    """ Return the id matched in an id string.
    Format should be similar to #24 """
    req_id = match("^#?([0-9])+$", feature_id)
    assert req_id, "**Feature request id's must either be a number or follow `#<id>`**"

    return int(req_id.group(1)) - 1


def format_req(plugin, req_id: int):
    """ Format a request as checked or not checked, also displaying its ID. """
    req_list = feature_reqs.data[plugin]

    if 0 <= req_id < len(req_list):
        req = req_list[req_id]
        checked = "-"

        # Check if the request is marked
        if req.endswith("+++"):
            checked = "+"
            req = req[:-3]

        return f"{checked} #{req_id + 1:<4}| {req}"

    return None


def feature_exists(plugin: str, req_id: int):
    """ Returns True if a feature with the given id exists. """
    return 0 <= req_id < len(feature_reqs.data[plugin])


def plugin_in_req(plugin: str):
    """ Function for checking that the plugin exists and initializes the req.
    Returns the plugin name. """
    plugin = plugin.lower()

    if not plugins.get_plugin(plugin):
        return None

    if plugin not in feature_reqs.data:
        feature_reqs.data[plugin] = []

    return plugin


@plugins.command()
async def feature(message: discord.Message, plugin: plugin_in_req, req_id: get_req_id = None):
    """ Handle plugin feature requests where plugin is a plugin name.
    See `{pre}plugin` for a list of plugins. """
    if req_id is not None:
        assert feature_exists(plugin, req_id), "There is no such feature."

        # The feature request the specified id exists, and we format and send the feature request
        await client.say(message, "```diff\n" + format_req(plugin, req_id) + "```")
    else:
        format_list = "\n".join(format_req(plugin, req_id)
                                for req_id in range(len(feature_reqs.data[plugin])))
        assert format_list, "This plugin has no feature requests!"

        # Format a list of all requests for the specified plugin when there are any
        await client.say(message, f"```diff\n{format_list}```")


@feature.command()
async def new(message: discord.Message, plugin: plugin_in_req, content: Annotate.CleanContent):
    """ Add a new feature request to a plugin.
    See `{pre}plugin` for a list of plugins. """
    req_list = feature_reqs.data[plugin]
    content = content.replace("\n", " ")

    assert content not in req_list, "This feature has already been requested!"

    # Add the feature request if an identical request does not exist
    feature_reqs.data[plugin].append(content)
    await feature_reqs.asyncsave()
    await client.say(message, f"Feature saved as `{plugin}` id **#{len(req_list)}**.")


@feature.command(owner=True)
async def mark(message: discord.Message, plugin: plugin_in_req, req_id: get_req_id):
    """ Toggles marking a feature request as complete.
    See `{pre}plugin` for a list of plugins. """
    # Test and reply if feature by requested id doesn't exist
    assert feature_exists(plugin, req_id), "There is no such feature."

    req = feature_reqs.data[plugin][req_id]

    # Mark or unmark the feature request by adding or removing +++ from the end (slightly hacked)
    if not req.endswith("+++"):
        feature_reqs.data[plugin][req_id] += "+++"
        await feature_reqs.asyncsave()
        await client.say(message, f"Marked feature with `{plugin}` id **#{req_id + 1}**.")
    else:
        feature_reqs.data[plugin][req_id] = req[:-3]
        await feature_reqs.asyncsave()
        await client.say(message, f"Unmarked feature with `{plugin}` id **#{req_id + 1}**.")


@feature.command(owner=True)
async def remove(message: discord.Message, plugin: plugin_in_req, req_id: get_req_id):
    """ Removes a feature request.
    See `{pre}plugin` for a list of plugins. """
    # Test and reply if feature by requested id doesn't exist
    assert feature_exists(plugin, req_id), "There is no such feature."

    # Remove the feature
    del feature_reqs.data[plugin][req_id]
    await feature_reqs.asyncsave()
    await client.say(message, f"Removed feature with `{plugin}` id **#{req_id + 1}**.")
