""" osu! commands

This plugin currently only assigns osu! profiles and notifies the server whenever they set a new top score (pp best).
The notifying is a near identical copy of plugins/twitch.py

Commands:
!osu
"""

import logging
from io import BytesIO
from os import path

import discord
import asyncio
import requests

from pcbot import Config

commands = {
    "osu": {
        "usage": "!osu <option>\n"
                 "Options:\n"
                 "    set <username>\n"
                 "    get\n"
                 "    notify-channel [channel]",
        "desc": "Handle osu! commands.\n"
                "`set` assigns your osu! user for notifying.\n"
                "`get` returns an osu! userpage link..\n"
                "~~`notify-channel` sets a channel as the notify channel. This channel should not be used by any "
                "member. Specify no channel to disable. **Requires `Manage Server` permission.**~~"
    }
}

osu = Config("osu", data={"key": "change to your api key", "profiles": {}})
osu_tracking = {}  # Saves the requested data or deletes whenever the user stops playing (for comparisons)
update_interval = 30  # Seconds

osu_api = "https://osu.ppy.sh/api/"

logging.getLogger("requests").setLevel(logging.WARNING)


@asyncio.coroutine
def on_ready(client: discord.Client):
    global osu_tracking

    if osu.data["key"] == "change to your api key":
        logging.log(logging.WARNING, "osu! functionality is unavailable until an API key is provided")

    while True:
        try:
            yield from asyncio.sleep(update_interval)
            sent_requests = 0

            # Go through all set channels playing osu! and update their status
            for member_id, profile in osu.data["profiles"].items():
                def find_playing(m):
                    if m.id == member_id:
                        if m.game:
                            if m.game.name.startswith("osu!"):
                                return True

                    return False

                member = discord.utils.find(find_playing, client.get_all_members())

                if member:
                    sent_requests += 1

                    request_params = {
                        "k": osu.data["key"],
                        "u": profile,
                        "type": "id",
                        "limit": 50
                    }
                    request = requests.get(osu_api + "get_user_best", request_params)

                    if request.ok:
                        scores = request.json()

                        # Go through all scores and see if they've already been tracked
                        if member_id in osu_tracking:
                            new_score = None

                            for score in scores:
                                if score not in osu_tracking[member_id]:
                                    new_score = score

                            # Tell all mutual servers if this user set a nice play
                            if new_score:
                                for server in client.servers:
                                    if member in server.members:

                                        m = "{0.mention} set a new best on " \
                                            "https://osu.ppy.sh/b/{1[beatmap_id]}\n" \
                                            "**{1[pp]}pp, {1[rank]}**\n" \
                                            "**Profile**: https://osu.ppy.sh/u/{1[user_id]}".format(member, new_score)
                                        yield from client.send_message(server, m)

                        osu_tracking[member_id] = list(scores)

            logging.log(logging.INFO, "Requested scores from {} users playing osu!.".format(sent_requests))

        except Exception as e:
            logging.log(logging.INFO, "Error: " + str(e))


@asyncio.coroutine
def on_message(client: discord.Client, message: discord.Message, args: list):
    if args[0] == "!osu":
        m = "Please see `!help osu`."
        if len(args) > 1:
            # Assign an osu! profile to your name or remove it
            if args[1] == "set":
                if len(args) > 2:
                    profile = " ".join(args[2:])

                    request_params = {
                        "k": osu.data["key"],
                        "u": profile
                    }
                    request = requests.get(osu_api + "get_user", request_params)
                    user = request.json()

                    if user:
                        # Clear the scores when changing user
                        if message.author.id in osu_tracking:
                            osu_tracking.pop(message.author.id)

                        osu.data["profiles"][message.author.id] = user[0]["user_id"]
                        osu.save()
                        m = "Set your osu! profile to `{}`.".format(user[0]["username"])
                    else:
                        m = "User {} does not exist.".format(profile)
                else:
                    if message.author.id in osu.data["profiles"]:
                        osu.data["profiles"].pop(message.author.id)
                        osu.save()
                        m = "osu! profile unlinked."

            # Return the member's or another member's osu! profile as a link and upload a signature
            elif args[1] == "get":
                if len(args) > 2:
                    member = client.find_member(message.server, " ".join(args[2:]))
                else:
                    member = message.author

                if member:
                    if member.id in osu.data["profiles"]:
                        user_id = osu.data["profiles"][member.id]

                        # Set the signature color to that of the role color
                        color = "pink"

                        if len(member.roles) > 1:
                            color = "hex{0:02x}{1:02x}{2:02x}".format(*member.roles[1].colour.to_tuple())

                        # Download and upload the signature
                        request_params = {
                            "colour": color,
                            "uname": user_id,
                            "pp": 1,
                            "countryrank": True,
                            "xpbar": True
                        }

                        request = requests.get("http://lemmmy.pw/osusig/sig.php", request_params)

                        if request.ok:
                            signature = BytesIO(request.content)

                            yield from client.send_file(message.channel, signature, filename="sig.png")

                        m = "https://osu.ppy.sh/u/{}".format(user_id)
                    else:
                        m = "No osu! profile assigned to {}!".format(member.name)
                else:
                    m = "Found no such member."

            # # Set or get the osu! notify channel
            # elif args[1] == "notify-channel":
            #     if message.author.permissions_in(message.channel).manage_server:
            #         if len(args) > 2:
            #             channel = client.find_channel(message.server, args[2])
            #
            #             if channel:
            #                 osu.data["notify-channel"][message.server.id] = channel.id
            #                 osu.save()
            #                 m = "Notify channel set to {}.".format(channel.mention)
            #         else:
            #             if "notify-channel" in osu.data:
            #                 twitch_channel = client.get_channel(osu.data["notify-channel"])
            #                 if twitch_channel:
            #                     m = "Twitch notify channel is {}.".format(twitch_channel)
            #                 else:
            #                     m = "The twitch notify channel no longer exists!"
            #             else:
            #                 m = "A twitch notify channel has not been set."
            #     else:
            #         m = "You need `Manage Server` to use this command."

        yield from client.send_message(message.channel, m)
