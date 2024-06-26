""" Plugin for generating markov text, or a summary if you will. """

import asyncio
import json
import logging
import os
import random
import re
import string
from collections import defaultdict, deque
from functools import partial

import discord
from sqlalchemy.sql import select, insert, delete

import bot
import plugins
from pcbot import utils, Annotate, config, Config
from pcbot.db import engine, db_metadata

client = plugins.client  # type: bot.Client

try:
    import markovify
except ImportError:
    logging.warning("Markovify could not be imported and as such !summary +strict will not work.")
try:
    import nltk

    nltk.download("punkt", download_dir="plugins/nltk_data", quiet=True)
    nltk.data.path.append("plugins/nltk_data")
except ImportError:
    nltk = None
    logging.warning("NLTK could not be imported and as such !summary +bigram will not work.")
try:
    import numpy
except ImportError:
    logging.warning("Numpy could not be imported and as such !summary +bigram will not work.")
    numpy = None

NEW_LINE_IDENTIFIER = " {{newline}} "

# The messages stored per session, where every key is a channel id
stored_messages = defaultdict(partial(deque, maxlen=10000))
logs_from_limit = 5000
max_summaries = 15
max_admin_summaries = 15
update_task = asyncio.Event()
update_task.set()

# Define some regexes for option checking in "summary" command
valid_num = re.compile(r"\*(?P<num>\d+)")
valid_member = utils.member_mention_pattern
valid_member_silent = re.compile(r"@\((?P<name>.+)\)")
valid_role = re.compile(r"<@&(?P<id>\d+)>")
valid_channel = utils.channel_mention_pattern
valid_options = ("+re", "+regex", "+case", "+tts", "+nobot", "+bot", "+coherent", "+loose", "+bigram")

on_no_messages = "**There were no messages to generate a summary from, {0.author.name}.**"
on_fail = "**I was unable to construct a summary, {0.author.name}.**"

summary_options = Config("summary_options", data={"no_bot": False, "no_self": False, "persistent_channels": []},
                         pretty=True)


def generate_query_data(messages: list[discord.Message]):
    messages_to_commit = []
    for message in messages:
        messages_to_commit.append({"content": message.clean_content, "channel_id": message.channel.id,
                                   "author_id": message.author.id, "bot": message.author.bot})
    return messages_to_commit


def commit_message(query_data: list):
    with engine.connect() as connection:
        table = db_metadata.tables["summary_messages"]
        statement = insert(table).values(query_data)
        transaction = connection.begin()
        connection.execute(statement)
        transaction.commit()


def migrate_summary_data():
    with open("config/summary_data.json", encoding="utf-8") as f:
        data = json.load(f)
        query_data = []
        if data["channels"]:
            for channel_id, messages in data["channels"].items():
                for message in messages:
                    if not message["content"]:
                        continue
                    query_data.append({"content": message["content"], "channel_id": channel_id,
                                       "author_id": message["author"], "bot": message["bot"]})
            commit_message(query_data)
    os.remove("config/summary_data.json")


def delete_channel_messages(channel_id: int):
    with engine.connect() as conn:
        table = db_metadata.tables["summary_messages"]
        statement = delete(table).where(table.c.channel_id == channel_id)
        transaction = conn.begin()
        conn.execute(statement)
        transaction.commit()


if os.path.exists("config/summary_data.json"):
    migrate_summary_data()


def get_persistent_messages(channel_id: int, member_list: list[discord.Member] = None, bots: bool = False,
                            phrase: str = None):
    if member_list is None:
        member_list = []
    table = db_metadata.tables["summary_messages"]
    statement = select(table.c.content).where((table.c.channel_id == channel_id)).whereclause
    if len(member_list) == 1:
        statement = select(table.c.content).where(statement & (table.c.author_id == member_list[0].id)).whereclause
    elif len(member_list) > 1:
        statement = select(table.c.content).where(
            statement & (table.c.author_id.in_(member.id for member in member_list))).whereclause
    if phrase:
        statement = select(table.c.content).where(statement & (table.c.content.contains(phrase))).whereclause
    if not bots:
        statement = select(table.c.content).where(statement & (table.c.bot == bots)).whereclause
    with engine.connect() as connection:
        result = connection.execute(select(table.c.content).where(statement))
        return result.all()


def to_persistent(message: discord.Message):
    return {"content": message.clean_content, "author": str(message.author.id), "bot": message.author.bot}


async def update_messages(channel: discord.TextChannel):
    """ Download messages. """
    messages = stored_messages[str(channel.id)]  # type: deque

    # We only want to log messages when there are none
    # Any messages after this logging will be logged in the on_message event
    if messages:
        return

    # Make sure not to download messages twice by setting this handy task
    update_task.clear()

    # Download logged messages
    try:
        async for m in channel.history(limit=logs_from_limit):
            if not m.content:
                continue

            # We have no messages, so insert each from the left, leaving us with the oldest at index -1
            messages.appendleft(to_persistent(m))
    except:  # When something goes wrong, clear the messages
        messages.clear()
    finally:  # Really have to make sure we clear this task in all cases
        update_task.set()


async def on_reload(name: str):
    """ Preserve the summary message cache when reloading. """
    global stored_messages
    local_messages = stored_messages

    await plugins.reload(name)

    stored_messages = local_messages


def indexes_of_word(words: list, word: str):
    """ Return a list of indexes with the given word. """
    return [i for i, s in enumerate(words) if s.lower() == word]


def random_with_bias(messages: list, word: str):
    """ Go through all the messages and try to choose the ones where the given word is
    not at the end of the string. """
    last_word_messages = []
    non_last_word_messages = []
    for m in messages:
        words = m.split()
        if words[-1].lower() == word:
            last_word_messages.append(m)
        else:
            non_last_word_messages.append(m)

    if not last_word_messages:
        return random.choice(non_last_word_messages)
    if not non_last_word_messages:
        return random.choice(last_word_messages)

    return random.choice(last_word_messages if random.randint(0, 5) == 0 else non_last_word_messages)


def markov_messages(messages: list, coherent: bool = False):
    """ Generate some kind of markov chain that somehow works with discord.
    I found this makes better results than markovify would. """
    imitated = []
    word = ""

    if all(bool(s.startswith("@") or s.startswith("http")) for s in messages):
        return "**The given phrase would crash the bot.**"

    # First word
    while True:
        m_split = random.choice(messages).split()
        if not m_split:
            continue

        # Choose the first word in the sentence to simulate a markov chain
        word = m_split[0]

        if not word.startswith("@") and not word.startswith("http"):
            break

    # Add the first word
    imitated.append(word)
    valid = []
    im = ""

    # Next words
    while True:
        # Set the last word and find all messages with the last word in it
        if not im == imitated[-1].lower():
            im = imitated[-1].lower()
            valid = [m for m in messages if im in m.lower().split()]

        # Add a word from the message found
        if valid:
            # # Choose one of the matched messages and split it into a list or words
            m = random_with_bias(valid, im).split()
            m_indexes = indexes_of_word(m, im)
            m_index = random.choice(m_indexes)  # Choose a random index
            m_from = m[m_index:]

            # Are there more than the matched word in the message (is it not the last word?)
            if len(m_from) > 1:
                imitated.append(m_from[1])  # Then we'll add the next word
                continue

            # Have the chance of breaking be 1/4 at start and 1/1 when imitated approaches 150 words
            # unless the entire summary should be coherent
            chance = 0 if coherent else int(-0.02 * len(imitated) + 4)
            chance = chance if chance >= 0 else 0

            if random.randint(0, chance) == 0:
                break

        # Add a random word if all valid messages are one word or there are less than 2 messages
        if len(valid) <= 1 or all(len(m.split()) <= 1 for m in valid):
            seq = random.choice(messages).split()
            word = random.choice(seq)
            imitated.append(word)

    # Remove links after, because you know
    imitated = [s for s in imitated if "http://" not in s and "https://" not in s]

    return " ".join(imitated)


def filter_messages(message_content: list, phrase: str, regex: bool = False, case: bool = False):
    """ Filter messages by searching and yielding each message. """
    for content in message_content:
        if regex:
            try:
                if re.search(phrase, content, 0 if case else re.IGNORECASE):
                    yield content
            except Exception as e:  # Return error message when regex does not work
                raise AssertionError("**Invalid regex.**") from e
        elif not regex and (phrase in content if case else phrase.lower() in content.lower()):
            yield content


def generate_message(message: discord.Message, message_content: list, phrase: str, strict: bool, coherent: bool,
                     bigram: bool, num: int):
    """ Generate a message from stored message content and user arguments. """
    sentences = []
    markovify_model = None
    if strict:
        try:
            markovify_model = markovify.Text(message_content)
        except NameError:
            logging.warning("+strict was used but markovify is not imported")
            strict = False
        except KeyError:
            markovify_model = None
    if bigram and (not nltk or not numpy):
        logging.warning("+bigram was used but nltk is not imported")
        bigram = False

    # Generate the summary, or num summaries
    for _ in range(num):
        if strict and markovify_model:
            if phrase and is_endswith(phrase):
                try:
                    sentence = markovify_model.make_sentence_with_start(phrase[:-3])
                except KeyError:
                    sentence = markovify_model.make_sentence(tries=1000)

            else:
                sentence = markovify_model.make_sentence(tries=1000)
        elif bigram:
            bigram_model = create_bigram_model(message_content)
            sentence = generate_bigram_message(bigram_model, phrase)
        else:
            sentence = markov_messages(message_content, coherent)

        if not sentence:
            sentence = markov_messages(message_content, coherent)

        assert sentence, on_fail.format(message)

        # Convert new line identifiers back to characters
        sentence = sentence.replace(NEW_LINE_IDENTIFIER.strip(" "), "\n")
        sentences.append(sentence)
    return sentences


def create_bigram_model(message_content: list):
    bigram_count = defaultdict(lambda: defaultdict(lambda: 0))
    bigram_model = defaultdict(lambda: defaultdict(lambda: 0.0))
    # Count the frequency of a bigram
    for sentence in message_content:
        split_sentence = nltk.tokenize.word_tokenize(sentence)
        # Remove punctuation
        for word in split_sentence:
            if word is not None and word in string.punctuation:
                split_sentence.remove(word)
        # Count occurences of a word after another word
        for first_word, second_word in nltk.bigrams(split_sentence, pad_right=True, pad_left=True):
            bigram_count[first_word][second_word] += 1
    # Calculate the probability of a bigram occuring
    for first_word in bigram_count:
        total_bigram_count = sum(bigram_count[first_word].values())
        for second_word in bigram_count[first_word]:
            bigram_model[first_word][second_word] = bigram_count[first_word][second_word] / total_bigram_count
    return bigram_model


def generate_bigram_message(bigram_model: defaultdict[lambda: defaultdict[lambda: 0.0]], phrase: str):
    # Generate a sentence using the bigram model
    bigram_text = [phrase if phrase else None]
    sentence_complete = False
    while not sentence_complete:
        key = bigram_text[-1]
        bigram_word = list(bigram_model[key].keys())
        probabilities = list(bigram_model[key].values())
        random_word = numpy.random.choice(bigram_word, p=probabilities)
        bigram_text.append(random_word)

        if bigram_text[-1] is None:
            sentence_complete = True
    sentence = " ".join([t for t in bigram_text if t])
    return sentence


def is_valid_option(arg: str):
    if valid_num.match(arg) or valid_member.match(arg) or valid_member_silent.match(arg) \
            or valid_channel.match(arg) or valid_role.match(arg):
        return True

    if arg.lower() in valid_options:
        return True

    return False


def filter_messages_by_arguments(messages: list, member: list, bots: bool):
    # Split the messages into content and filter member and phrase
    messages = (m for m in messages if not member or m["author"] in [str(mm.id) for mm in member])

    # Filter bot messages or own messages if the option is enabled in the config
    if not bots:
        messages = (m for m in messages if not m["bot"])
    elif summary_options.data["no_self"]:
        messages = (m for m in messages if not m["author"] == str(client.user.id))

    # Convert all messages to content
    return (m["content"] for m in messages)


def is_endswith(phrase: str):
    return phrase.endswith("...") and len(phrase.split()) in (1, 2)


@plugins.command(
    usage="([*<num>] [@<user/role> ...] [#<channel>] [+re(gex)] [+case] [+tts] [+(no)bot] [+coherent] [+loose] "
          "[+bigram]) [phrase ...]",
    pos_check=is_valid_option, aliases="markov")
async def summary(message: discord.Message, *options, phrase: Annotate.Content = None):
    """ Run a markov chain through the past 5000 messages + up to another 5000
    messages after first use. This command needs some time after the plugin reloads
    as it downloads the past 5000 messages in the given channel. """
    # This dict stores all parsed options as keywords
    member, channel, num = [], None, None
    regex, case, tts, coherent, strict, bigram = False, False, False, False, True, False
    bots = not summary_options.data["no_bot"]

    async with message.channel.typing():
        for value in options:
            num_match = valid_num.match(value)
            if num_match:
                assert not num
                num = int(num_match.group("num"))
                continue

            member_match = valid_member.match(value)
            if member_match:
                member.append(message.guild.get_member(int(member_match.group("id"))))
                continue

            member_match = valid_member_silent.match(value)
            if member_match:
                member.append(utils.find_member(message.guild, member_match.group("name")))
                continue

            role_match = valid_role.match(value)
            if role_match:
                role = discord.utils.get(message.guild.roles, id=int(role_match.group("id")))
                member.extend(m for m in message.guild.members if role in m.roles)

            channel_match = valid_channel.match(value)
            if channel_match:
                assert not channel
                channel = utils.find_channel(message.guild, channel_match.group())
                continue

            if value in valid_options:
                if value in ("+re", "+regex"):
                    regex = True
                if value == "+case":
                    case = True
                if value == "+tts":
                    tts = True
                if value == "+coherent":
                    coherent = True
                if value == "+loose":
                    strict = False
                if value == "+bigram":
                    bigram = True

                bots = False if value == "+nobot" else True if value == "+bot" else bots
        if phrase and len(phrase.split()) > 1 and bigram:
            await client.say(message, "Only 1 word phrases can be used with bigrams")
            return

        # Assign defaults and number of summaries limit
        is_privileged = message.channel.permissions_for(message.author).manage_messages

        if num is None or num < 1:
            num = 1
        elif num > max_admin_summaries and is_privileged:
            num = max_admin_summaries
        elif num > max_summaries:
            num = max_summaries if not is_privileged else num

        if not channel:
            channel = message.channel

        # Check channel permissions after the given channel has been decided
        assert channel.permissions_for(message.guild.me).read_message_history, "**I can't see this channel.**"
        assert not tts or message.channel.permissions_for(message.author).send_tts_messages, \
            "**You don't have permissions to send tts messages in this channel.**"

        if str(channel.id) in summary_options.data["persistent_channels"]:
            messages = get_persistent_messages(channel.id, member, bots, phrase)
            message_content = [str(message.content) for message in messages]
        else:
            await update_task.wait()
            await update_messages(channel)
            messages = stored_messages[str(channel.id)]
            message_content = filter_messages_by_arguments(messages, member, bots)
            # Filter looking for phrases if specified
            if phrase and not is_endswith(phrase):
                message_content = list(filter_messages(message_content, phrase, regex, case))

        # Replace new lines with text to make them persist through splitting
        message_content = (s.replace("\n", NEW_LINE_IDENTIFIER) for s in message_content)

        command_prefix = config.guild_command_prefix(message.guild)
        # Clean up by removing all commands from the summaries
        if phrase is None or not phrase.startswith(command_prefix):
            message_content = [s for s in message_content if not s.startswith(command_prefix)]

        # Check if we even have any messages
        assert message_content, on_no_messages.format(message)
        sentences = generate_message(message, message_content, phrase, strict, coherent, bigram, num)

    await client.send_message(message.channel, "\n".join(sentences), tts=tts)


@plugins.event(bot=True, self=True)
async def on_message(message: discord.Message):
    """ Whenever a message is sent, see if we can update in one of the channels. """
    # Store to persistent if enabled for this channel
    if str(message.channel.id) in summary_options.data["persistent_channels"] and message.content:
        query_data = generate_query_data([message])
        commit_message(query_data)
    elif str(message.channel.id) in stored_messages and message.content:
        stored_messages[str(message.channel.id)].append(to_persistent(message))


@summary.command(owner=True)
async def enable_persistent_messages(message: discord.Message, disable: bool = False):
    """ Stores every message in this channel in persistent storage. """
    if disable:
        if str(message.channel.id) not in summary_options.data["persistent_channels"]:
            await client.say(message, "Persistent messages are not enabled in this channel.")
            return
        summary_options.data["persistent_channels"].remove(str(message.channel.id))
        await summary_options.asyncsave()
        delete_channel_messages(message.channel.id)
        await client.say(message, "Persistent messages are no longer enabled in this channel.")
        return

    if str(message.channel.id) in summary_options.data["persistent_channels"]:
        await client.say(message, "Persistent messages are already enabled and tracked in this channel")
        return

    summary_options.data["persistent_channels"].append(str(message.channel.id))
    await summary_options.asyncsave()

    await client.say(message, "Downloading messages. This may take a while.")

    message_list = []
    # Download EVERY message in the channel
    i = 0
    async for m in message.channel.history(before=message, limit=None):
        i += 1
        if i % 100 == 0:
            query_data = generate_query_data(message_list)
            commit_message(query_data)
            message_list = []
        if not m.content:
            continue

        # We have no messages, so insert each from the left, leaving us with the oldest at index -1
        message_list.append(m)
    if message_list:
        query_data = generate_query_data(message_list)
        commit_message(query_data)
    await client.say(message,
                     f"Downloaded {len(get_persistent_messages(message.channel.id))} messages!")
