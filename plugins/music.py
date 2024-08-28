""" Plugin for playing music.

Some of the logic is very similar to the example at:
    https://github.com/Rapptz/discord.py/blob/master/examples/playlist.py

TUTORIAL:
    This module would require the bot to have ffmpeg installed and set in
    PATH, so that one could run `ffmpeg` in the shell.
    See: https://www.ffmpeg.org/

    The bot owner can link a music channel to any voice channel in a guild
    using the !music link <voice channel ...> command. After doing this, the
    bot should automatically join the linked channel whenever a member plays a song.
    The members in the channel can then manage music playing.

ISSUES:
    The music player seems to randomly start skipping songs, or rather
    stopping them way too early. I have no solution to this issue and do not
    know why it happens, but apparently I'm not the only bot creator who has
    experienced said issue.

Commands:
    music
"""
import asyncio
import logging
import random
import re
from collections import namedtuple, deque
from typing import Dict

import discord
import yt_dlp

import bot
import plugins
from pcbot import utils, Annotate

client = plugins.client  # type: bot.Client

voice_states = {}  # type: Dict[discord.Guild, VoiceState]
ytdl_format_options = {
    'format': 'bestaudio/best',
    'audioformat': 'opus',
    'noplaylist': True,
    'nocheckcertificate': True,
    'quiet': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0'  # bind to ipv4 since ipv6 addresses cause issues sometimes
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

max_songs_queued = 6  # How many songs each member are allowed in the queue at once
max_song_length = 10 * 60 * 60  # The maximum song length in seconds
default_volume = .6

# if not discord.opus.is_loaded():
#    discord.opus.load_opus('libopus-0.x64.dll')

Song = namedtuple("Song", "channel player requester")

disposition_pattern = re.compile(r"filename=\"(?P<name>.+)\"")


async def on_reload(name: str):
    """ Preserve voice states. """
    global voice_states
    local_states = voice_states

    await plugins.reload(name)

    voice_states = local_states


def format_song(song: Song, url=True):
    """ Format a song request. """
    # The player duration is given in seconds; convert it to h:mm
    duration = ""
    if song.player.duration:
        length = divmod(int(song.player.duration), 60)
        duration = f"Duration: **{length[0]}:{length[1]:02}**"

    return f"**{song.player.title}**\nRequested by: **{song.requester.display_name}**\n{duration}" \
        + (f"\n**URL**: <{song.player.url}>" if url else "")


class VoiceState:
    def __init__(self, voice):
        self.voice = voice  # type: discord.VoiceClient
        self._volume = default_volume
        self.current = None
        self.queue = deque()  # The queue contains items of type Song

    @property
    def volume(self):
        return self._volume

    @volume.setter
    def volume(self, value: float):
        if value > 1:
            value = 1
        elif value < .01:
            value = default_volume

        self._volume = value
        if self.voice.is_playing():
            self.voice.source.volume = self._volume

    async def play_next(self):
        """ Play the next song if there are any. """

        if not self.queue:
            if self.voice.is_connected():
                await disconnect(self.voice.guild)
            return
        self.current = self.queue.popleft()
        self.current.player.volume = self.volume
        self.voice.play(self.current.player,
                        after=lambda e: asyncio.run_coroutine_threadsafe(self.play_next(), client.loop))

    def skip(self):
        """ Skip the song currently playing. """
        if self.voice.is_playing():
            self.voice.stop()

    def resume(self):
        """ Resume the currently paused song. """
        if self.voice.is_paused():
            self.voice.resume()

    def pause(self):
        """ Pause the currently playing song"""
        if self.voice.is_playing():
            self.voice.pause()

    def format_playing(self):
        if self.voice.is_playing():
            return format_song(self.current)

        return "*Nothing.*"


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=default_volume):
        super().__init__(source, volume)

        self.data = data

        self.duration = data.get('duration')
        self.title = data.get('title')
        self.url = data.get('webpage_url')

    @classmethod
    async def from_url(cls, url, *, loop=None):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=False))

        if 'entries' in data:
            # take first item from a playlist
            data = data['entries'][0]

        filename = data['url']
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)


@plugins.command(aliases="m", disabled_pm=True)
async def music(message, _: utils.placeholder):
    """ Manage music. If a music channel is assigned, the bot will join
    whenever someone plays music. """


def client_connected(guild: discord.Guild):
    """ Returns True or False whether the bot is client_connected to the
    Music channel in this guild. """
    if guild.me.voice:
        return guild in voice_states

    return False


def assert_connected(member: discord.Member, checkbot=True):
    """ Throws an AssertionError exception when neither the bot nor
    the member is connected to the music channel."""
    if member.voice:
        assert member.voice.channel and member.voice.channel is member.guild.me.voice.channel \
            if member.guild.me.voice else True, "**You are not connected to the music channel.**"
    else:
        raise AssertionError("**You are not connected to the music channel.**")
    if checkbot:
        assert client_connected(member.guild), "**The bot is not connected to the music channel.**"


async def join(message: discord.Message):
    """  Joins a voice channel  """
    guild = message.guild
    assert_connected(member=message.author, checkbot=False)
    channel = message.author.voice.channel

    if guild.voice_client is not None:
        voiceclient = await guild.voice_client.move_to(channel)
        voice_states[guild] = VoiceState(voiceclient)
        return

    voiceclient = await channel.connect()
    voice_states[guild] = VoiceState(voiceclient)


async def disconnect(guild: discord.Guild):
    state = voice_states[guild]
    state.queue.clear()
    await state.voice.disconnect()
    del voice_states[guild]


async def play(message: discord.Message, song: Annotate.Content = None):
    """ Play a song in the guild voice channel. The given song could either be a URL or keywords
    to lookup videos in YouTube. """

    assert_connected(message.author, checkbot=False)

    # Connect to voice channel if not connected
    if message.guild.voice_client is None:
        await join(message)

    state = voice_states[message.guild]

    if song is None:
        assert len(message.attachments) > 0, \
            "**An audio file must be provided when using this command without a song name or url.**"
        song = message.attachments[0].url

    # Strip any embed characters, spaces or code symbols.
    song = song.strip("< >`")

    try:
        player = await YTDLSource.from_url(song)
    except Exception as e:
        await client.say(message, "**Could not add this song to the queue.**")
        logging.info(e)
        return

    # Make sure the song isn't too long
    if player.duration:
        assert player.duration < max_song_length, "**The requested song is too long.**"

    url_match = utils.http_url_pattern.match(song)
    if url_match and player.title == url_match.group("sub"):
        # Try retrieving the filename as this is probably a file
        headers = await utils.retrieve_headers(song)
        if "Content-Disposition" in headers:
            name_match = disposition_pattern.search(headers["Content-Disposition"])
            if name_match:
                player.title = "".join(name_match.group("name").split(".")[:-1])

    song = Song(player=player, requester=message.author, channel=message.channel)

    embed = discord.Embed(color=message.author.color)
    embed.description = "Queued:\n" + format_song(song, url=False)

    await client.send_message(song.channel, embed=embed)
    state.queue.append(song)

    # Start the song when there are none
    if not state.voice.is_playing():
        await state.play_next()


music.command(aliases="p pl")(play)
plugins.command(aliases="p")(play)


async def skip(message: discord.Message):
    """ Skip the song currently playing. """
    assert_connected(message.author)
    state = voice_states[message.guild]
    assert state.voice.is_playing(), "**There is no song currently playing.**"

    await client.say(message, "**Skipped song.**")
    state.skip()


music.command(aliases="s next")(skip)
plugins.command(aliases="s")(skip)


async def undo(message: discord.Message):
    """ Undo your previously queued song. This will not *skip* the song if it's playing. """
    assert_connected(message.author)
    state = voice_states[message.guild]

    for song in reversed(state.queue):
        if song.requester == message.author:
            await client.say(message, f"Removed previous request **{song.player.title}** from the queue.")
            state.queue.remove(song)
            return

    await client.say(message, "**You have nothing to undo.**")


music.command(aliases="u nvm fuck no")(undo)
plugins.command()(undo)


async def clear(message: discord.Message):
    """ Remove all songs you have queued. """
    assert_connected(message.author)
    state = voice_states[message.guild]

    removed = False
    for song in list(state.queue):
        if song.requester == message.author:
            state.queue.remove(song)
            removed = True

    if removed:
        await client.say(message, f"Removed all queued songs by **{message.author.display_name}**.")
    else:
        await client.say(message, "**You have no queued songs.**")


music.command()(clear)
plugins.command()(clear)


@music.command(roles="Shuffler")
async def shuffle(message: discord.Message):
    """ Shuffles the current queue. """
    assert_connected(message.author)
    state = voice_states[message.guild]

    random.shuffle(state.queue)
    await queue(message)


@music.command(aliases="v volume")
async def vol(message: discord.Message, volume: int):
    """ Set the volume of the player. Volume should be a number in percent. """
    assert_connected(message.author)
    state = voice_states[message.guild]
    state.volume = volume / 100
    await client.say(message, f"Set the volume to **{state.volume:.00%}**.")


async def playing(message: discord.Message):
    """ Return the name and URL of the song currently playing. """
    assert_connected(message.author)
    state = voice_states[message.guild]

    embed = discord.Embed(color=message.author.color)
    embed.description = "Playing:\n" + state.format_playing()

    await client.send_message(message.channel, embed=embed)


music.command(aliases="np")(playing)
plugins.command(aliases="np")(playing)


async def pause(message: discord.Message):
    """ Pause the currently playing song. """
    assert_connected(message.author)
    state = voice_states[message.guild]
    assert state.voice.is_playing(), "**There is no song currently playing.**"

    state.pause()
    await client.say(message, content="Paused the currently playing song.")


music.command()(pause)
plugins.command()(pause)


async def resume(message: discord.Message):
    """ Resume the currently paused song. """
    assert_connected(message.author)
    state = voice_states[message.guild]
    assert state.voice.is_paused(), "**There is no song currently paused.**"

    state.resume()
    await client.say(message, content="Resumed the paused song.")


music.command()(resume)
plugins.command()(resume)


async def queue(message: discord.Message):
    """ Return a list of the queued songs. """
    assert_connected(message.author)
    state = voice_states[message.guild]
    assert state.queue, "**There are no songs queued.**"

    embed = discord.Embed(color=message.author.color)
    embed.description = "```elm\n{}```".format(
        "\n".join(format_song(s, url=False).replace("**", "") + "\n" for s in state.queue))

    await client.send_message(message.channel, embed=embed)


music.command(aliases="q l list")(queue)
plugins.command(aliases="q")(queue)


@plugins.event()
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    """ Handle leaving channels. The bot will automatically
    leave the guild's voice channel when all members leave. """
    channel = voice_states[member.guild].voice.channel \
        if member.guild in voice_states and voice_states[member.guild].voice else None
    if not channel:
        return

    count_members = sum(1 for m in channel.members if not m.bot)

    # Leave the voice channel we're client_connected to when the only one here is the bot
    if member.guild.me and member.guild.me.voice:
        if member.guild in voice_states and member.guild.me.voice.channel == channel:
            if count_members == 0:
                await disconnect(member.guild)
