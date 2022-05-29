""" Would you rather? This plugin includes would you rather functionality
"""
import asyncio
import random
import re

import discord

import bot
import plugins
from pcbot import Config

client = plugins.client  # type: bot.Client

db = Config("would-you-rather", data=dict(timeout=10, responses=["**{name}** would **{choice}**!"], questions=[]),
            pretty=True)
command_pattern = re.compile(r"(.+)(?:\s+or|\s*,)\s+([^?]+)\?*")
sessions = set()  # All running would you rather's are in this set


def format_choice_message(choices: list, responses: list):
    formatted_responses = "\n".join(responses)
    return f"Would you rather \U0001f7e2 **{choices[0]}** or \U0001f534 **{choices[1]}**?\n\n" \
           f"{formatted_responses}"


class ChoiceButton(discord.ui.View):
    def __init__(self, question: dict, choices: list):
        super().__init__()
        self.question = question
        self.choices = choices
        self.replied = []
        self.responses = []
        self.timeout = db.data["timeout"]

    async def mark_answer(self, choice: int, user: discord.User, message: discord.Message):
        # Register that this author has replied
        self.replied.append(user)

        # Update the answers in the DB
        # We don't care about multiples, just the amount (yes it will probably be biased)
        self.question["answers"][choice] += 1

        self.responses.append(random.choice(db.data["responses"]).format(name=user.display_name,
                                                                         NAME=user.display_name.upper(),
                                                                         choice=self.choices[choice]))
        embed = message.embeds[0]
        embed.description = format_choice_message(self.choices, self.responses)
        await message.edit(embed=embed)

    @discord.ui.button(label="1", style=discord.ButtonStyle.green)
    async def first_choice(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user not in self.replied:
            await self.mark_answer(0, interaction.user, interaction.message)
            await interaction.response.send_message('Your choice has been saved.', ephemeral=True)
        else:
            await interaction.response.send_message('You have already made a choice', ephemeral=True)

    @discord.ui.button(label="2", style=discord.ButtonStyle.red)
    async def second_choice(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user not in self.replied:
            await self.mark_answer(1, interaction.user, interaction.message)
            await interaction.response.send_message('Your choice has been saved.', ephemeral=True)
        else:
            await interaction.response.send_message('You have already made a choice.', ephemeral=True)


@plugins.argument("{open}option ...{close} or/, {open}other option ...{close}[?]", allow_spaces=True)
async def options(arg):
    """ Command argument for receiving two options. """
    match = command_pattern.match(arg)
    assert match
    assert not match.group(1).lower() == match.group(2).lower(), "**The choices cannot be the same.**"

    return match.group(1), match.group(2)


@plugins.command(aliases="wyr rather either")
async def wouldyourather(message: discord.Message, opt: options = None):
    """ Ask the bot if he would rather, or have the bot ask you.

    **Examples:**

    Registering a choice: `!wouldyourather lie or be lied to`

    Asking the bot: `!wouldyourather`"""
    # If there are no options, the bot will ask the questions (if there are any to choose from)
    if opt is None:
        assert message.channel.id not in sessions, "**A would you rather session is already in progress.**"
        sessions.add(message.channel.id)

        assert db.data["questions"], "**There are ZERO questions saved. Ask me one!**"

        question = random.choice(db.data["questions"])
        choices = question["choices"]

        view = ChoiceButton(question, choices)
        embed = discord.Embed(description=format_choice_message(choices, []))
        original_message = await message.channel.send(embed=embed, view=view)

        await view.wait()
        await original_message.edit(view=None)

        # Say the total tallies
        await client.say(message, f'A total of {question["answers"][0]} would **{choices[0]}**, '
                                  f'while {question["answers"][1]} would **{choices[1]}**!')
        await db.asyncsave()
        sessions.remove(message.channel.id)

    # Otherwise, the member asked a question to the bot
    else:
        db.data["questions"].append(dict(
            choices=list(opt),
            answers=[0, 0]
        ))
        await db.asyncsave()

        answer = random.choice(opt)
        await client.say(message, f"**I would {answer}**!")


@wouldyourather.command(aliases="delete", owner=True)
async def remove(message: discord.Message, opt: options):
    """ Remove a wouldyourather question with the given options. """
    for q in db.data["questions"]:
        if q["choices"][0] == opt[0] and q["choices"][1] == opt[1]:
            db.data["questions"].remove(q)
            await db.asyncsave()
            await client.say(message, "**Entry removed.**")
            break
    else:
        await client.say(message, "**Could not find the question.**")
