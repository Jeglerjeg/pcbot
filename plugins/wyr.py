""" Would you rather? This plugin includes would you rather functionality
"""
import random
import re

import discord
from sqlalchemy import text

import bot
import plugins
from pcbot import Config
from pcbot.db import engine

client = plugins.client  # type: bot.Client

db = Config("would-you-rather", data=dict(timeout=10, responses=["**{name}** would **{choice}**!"]))
command_pattern = re.compile(r"(.+)(?:\s+or|\s*,)\s+([^?]+)\?*")

recently_asked = {}


def migrate():
    query_data = []
    if db.data["questions"]:
        for question in db.data["questions"]:
            query_data.append({"choice_1": question["choices"][0], "choice_2": question["choices"][1],
                               "choice_1_answers": question["answers"][0], "choice_2_answers": question["answers"][1]})
        with engine.connect() as connection:
            transaction = connection.begin()
            connection.execute(
                text("INSERT INTO questions (choice_1, choice_2, choice_1_answers, choice_2_answers) "
                     "VALUES (:choice_1, :choice_2, :choice_1_answers, :choice_2_answers)"),
                query_data
            )
            transaction.commit()
    del db.data["questions"]
    db.save()


if "questions" in db.data:
    migrate()


def add_question(choice_1: str, choice_2: str):
    with engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(
            text("INSERT INTO questions (choice_1, choice_2, choice_1_answers, choice_2_answers) "
                 "VALUES (:choice_1, :choice_2, :choice_1_answers, :choice_2_answers)"),
            {"choice_1": choice_1, "choice_2": choice_2, "choice_1_answers": 0, "choice_2_answers": 0}
        )
        transaction.commit()


def retrieve_question(choice_1: str, choice_2: str):
    with engine.connect() as connection:
        result = connection.execute(
            text("SELECT 1 FROM questions WHERE choice_1 = :choice_1 COLLATE NOCASE AND choice_2 = :choice_2 "
                 "COLLATE NOCASE"),
            {"choice_1": choice_1, "choice_2": choice_2}
        )
        return result.all()


def count_questions():
    with engine.connect() as connection:
        result = connection.execute(
            text("SELECT * FROM questions")
        )
        return len(result.all())


def retrieve_random_question():
    with engine.connect() as connection:
        result = connection.execute(
            text("SELECT * FROM questions ORDER BY RANDOM() LIMIT 1")
        )
        return result.first()


def add_recent_question(question: dict, channel: discord.TextChannel):
    if channel.id not in recently_asked:
        recently_asked[channel.id] = []
    recently_asked[channel.id].append(question)
    if len(recently_asked[channel.id]) > count_questions()/2:
        recently_asked[channel.id].pop(0)


def check_recent_questions(question: dict, channel: discord.TextChannel):
    if channel.id not in recently_asked:
        return True
    if question in recently_asked[channel.id]:
        return False
    return True


def check_duplicate_question(choices: list):
    if retrieve_question(choices[0], choices[1]):
        return False
    elif retrieve_question(choices[1], choices[0]):
        return False
    return True


def delete_question(choice_1: str, choice_2: str):
    with engine.connect() as conn:
        transaction = conn.begin()
        conn.execute(text("DELETE FROM questions WHERE choice_1 = :choice_1 AND choice_2 = :choice_2"),
                     {"choice_1": choice_1, "choice_2": choice_2})
        transaction.commit()


def update_answer_count(choice_1: str, choice_2: str, choice: int):
    with engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(
            text(f"UPDATE questions SET choice_{choice}_answers = choice_{choice}_answers + 1 "
                 f"WHERE choice_1 = :choice_1 AND choice_2 = :choice_2"),
            {"choice_1": choice_1, "choice_2": choice_2}
        )
        transaction.commit()


def format_choice_result(responses: list, choices: list):
    return f'A total of {responses[0]} would **{choices[0]}**, ' \
           f'while {responses[1]} would **{choices[1]}**!'


def format_choice_message(responses: list, choices: list, responders: list, result: bool = False):
    formatted_responses = "\n".join(responders)
    return f"Would you rather \U0001f7e2 **{choices[0]}** or \U0001f534 **{choices[1]}**?\n\n" \
           f"{formatted_responses}" + \
           (f"\n\n{format_choice_result(responses, choices)}" if result else "")


class ChoiceButton(discord.ui.View):
    def __init__(self, question):
        super().__init__(timeout=db.data["timeout"])
        self.choices = [question.choice_1, question.choice_2]
        self.responses = [question.choice_1_answers, question.choice_2_answers]
        self.replied = []
        self.responders = []

    async def mark_answer(self, choice: int, user: discord.User, message: discord.Message):
        # Register that this author has replied
        self.replied.append(user)

        # Update the answers in the DB
        # We don't care about multiples, just the amount (yes it will probably be biased)
        update_answer_count(self.choices[0], self.choices[1], choice+1)
        self.responses[choice] += 1

        self.responders.append(random.choice(db.data["responses"]).format(name=user.mention,
                                                                          NAME=user.display_name.upper(),
                                                                          choice=self.choices[choice]))
        embed = message.embeds[0]
        embed.description = format_choice_message(self.responses, self.choices, self.responders)
        await message.edit(embed=embed)

    @discord.ui.button(label="1", style=discord.ButtonStyle.green)
    async def first_choice(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user not in self.replied:
            await self.mark_answer(0, interaction.user, interaction.message)
            await interaction.response.defer()
        else:
            await interaction.response.send_message('You have already made a choice.', ephemeral=True)

    @discord.ui.button(label="2", style=discord.ButtonStyle.red)
    async def second_choice(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user not in self.replied:
            await self.mark_answer(1, interaction.user, interaction.message)
            await interaction.response.defer()
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
        assert count_questions() > 0, "**There are ZERO questions saved. Ask me one!**"
        question = retrieve_random_question()
        while not check_recent_questions(question, message.channel):
            question = retrieve_random_question()
        add_recent_question(question, message.channel)
        choices = [question.choice_1, question.choice_2]

        view = ChoiceButton(question)
        embed = discord.Embed(description=format_choice_message(question, choices, []))
        original_message = await message.channel.send(embed=embed, view=view)

        await view.wait()
        # Say the total tallies
        embed = discord.Embed(description=format_choice_message(view.responses, choices, view.responders, result=True))
        await original_message.edit(embed=embed, view=None)

        await db.asyncsave()

    # Otherwise, the member asked a question to the bot
    else:
        assert check_duplicate_question(sorted(opt)), "This question already exists!"

        add_question(opt[0], opt[1])

        answer = random.choice(opt)
        await client.say(message, f"**I would {answer}**!")


@wouldyourather.command(aliases="delete", owner=True)
async def remove(message: discord.Message, opt: options):
    """ Remove a wouldyourather question with the given options. """
    if retrieve_question(opt[0], opt[1]):
        delete_question(opt[0], opt[1])
        await client.say(message, "**Entry removed.**")
    else:
        await client.say(message, "**Could not find the question.**")
