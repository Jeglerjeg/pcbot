import logging
import os
import random
import shlex
import importlib
from datetime import datetime
from getpass import getpass
from sys import exit

import discord
import asyncio

from pcbot.config import Config

logging.basicConfig(level=logging.INFO)
plugins = {}


def load_plugin(plugin_name):
    if not plugin_name.startswith("__") or not plugin_name.endswith("__"):
        try:
            plugin = importlib.import_module("plugins.{}".format(plugin_name))
        except ImportError:
            return False

        plugins[plugin_name] = plugin
        return True

    return False


def reload_plugin(plugin_name):
    if plugins.get(plugin_name):
        plugins[plugin_name] = importlib.reload(plugins[plugin_name])


def unload_plugin(plugin_name):
    if plugins.get(plugin_name):
        plugins.pop(plugin_name)


def load_plugins():
    for plugin in os.listdir("plugins/"):
        plugin_name = os.path.splitext(plugin)[0]
        load_plugin(plugin_name)


class Bot(discord.Client):
    def __init__(self):
        super().__init__()
        self.message_count = Config("count", data={})
        self.owner = Config("owner")

        load_plugins()
        asyncio.async(self.autosave())

    # Return true if user/member is the assigned bot owner
    def is_owner(self, user):
        if type(user) is not str:
            user = user.id

        if user == self.owner.data:
            return True

        return False

    # Save a plugins files if it has a save function
    def save_plugin(self, plugin):
        if plugins.get(plugin):
            try:
                yield from plugins[plugin].save(self)
            except AttributeError:
                pass

    # Looks for any save function in a plugin and saves. Set up for saving on !stop and periodic saving every 30 mins
    def save_plugins(self):
        for name, _ in plugins.items():
            yield from self.save_plugin(name)

    @asyncio.coroutine
    def autosave(self):
        while True:
            # Sleep for 30 minutes before saving (no reason to save on startup)
            yield from asyncio.sleep(60 * 30)
            yield from self.save_plugins()
            logging.log(logging.INFO, "Plugins saved")

    @asyncio.coroutine
    def on_ready(self):
        print('Logged in as')
        print(self.user.name)
        print(self.user.id)
        print('------')

    @asyncio.coroutine
    def on_message(self, message: discord.Message):
        if message.author == self.user:
            return

        if not message.content:
            return

        # Log every command to console (logs anything starting with !)
        if message.content.startswith("!"):
            logging.log(logging.INFO, "{0}@{1.author.name}: {1.content}".format(
                datetime.now().strftime("%d.%m.%y %H:%M:%S"),
                message
            ))

        # Split content into arguments by space (surround with quotes for spaces)
        try:
            args = shlex.split(message.content)
        except ValueError:
            args = message.content.split()

        # Bot help command. Loads info from plugins
        if args[0] == "!help":
            # Command specific help
            if len(args) > 1:
                plugin_name = args[1].lower()
                for name, plugin in plugins.items():
                    if plugin.commands:
                        cmd = plugin.commands.get(plugin_name)
                        if cmd:
                            m = "**Usage**: ```{}```\n" \
                                "**Description**: {}".format(cmd.get("usage"), cmd.get("desc"))
                            yield from self.send_message(message.channel, m)
                            break

            # List all commands
            else:
                m = "**Commands:**```"
                for name, plugin in plugins.items():
                    if plugin.commands:
                        m += "\n" + "\n".join(plugin.commands.keys())

                m += "```\nUse `!help <comand>` for command specific help."
                yield from self.send_message(message.channel, m)

        # Below are all owner specific commands
        if message.channel.is_private and message.content == "!setowner":
            if self.owner.data:
                yield from self.send_message(message.channel, "An owner is already set.")
                return

            owner_code = str(random.randint(100, 999))
            print("Owner code for assignment: {}".format(owner_code))
            yield from self.send_message(message.channel,
                                         "A code has been printed in the console for you to repeat within 15 seconds.")
            user_code = yield from self.wait_for_message(timeout=15, channel=message.channel, content=owner_code)
            if user_code:
                yield from self.send_message(message.channel, "You have been assigned bot owner.")
                self.owner.data = message.author.id
                self.owner.save()
            else:
                yield from self.send_message(message.channel, "You failed to send the desired code.")

        if self.is_owner(message.author):
            # Stops the bot
            if message.content == "!stop":
                yield from self.save_plugins()
                bot.logout()
                exit("Stopped by owner.")

            # Sets the bots game
            elif args[0] == "!game":
                if len(args) > 1:
                    game = discord.Game(name=args[1])
                    logging.log(logging.DEBUG, "Setting bot game to {}".format(args[1]))
                    yield from self.change_status(game)
                else:
                    yield from self.send_message(message.channel, "Usage: `!game <game>`")

            # Runs a piece of code
            elif args[0] == "!do":
                if len(args) > 1:
                    def say(msg):
                        asyncio.async(self.send_message(message.channel, msg))

                    script = message.clean_content[len("!do "):].replace("`", "")
                    try:
                        exec(script)
                    except Exception as e:
                        say("```" + str(e) + "```")

            # Evaluates a piece of code and prints the result
            elif args[0] == "!eval":
                if len(args) > 1:
                    script = message.clean_content[len("!eval "):].replace("`", "")
                    result = eval(script)
                    yield from self.send_message(message.channel, "**Result:** \n```{}\n```".format(result))

            # Plugin specific commands
            elif args[0] == "!plugin":
                if len(args) > 1:
                    if args[1] == "reload":
                        if len(args) > 2:
                            if plugins.get(args[2]):
                                yield from self.save_plugin(args[2])
                                reload_plugin(args[2])
                                yield from self.send_message(message.channel, "Reloaded plugin `{}`.".format(args[2]))
                            else:
                                yield from self.send_message(message.channel,
                                                             "`{}` is not a plugin. Use `!plugins`.".format(args[2]))
                        else:
                            yield from self.save_plugins()
                            for plugin in list(plugins.keys()):
                                reload_plugin(plugin)
                            yield from self.send_message(message.channel, "All plugins reloaded.")
                    elif args[1] == "load":
                        if len(args) > 2:
                            if not plugins.get(args[2].lower()):
                                loaded = load_plugin(args[2].lower())
                                if loaded:
                                    yield from self.send_message(message.channel, "Plugin `{}` loaded.".format(args[2]))
                                else:
                                    yield from self.send_message(message.channel,
                                                                 "Plugin `{}` could not be loaded.".format(args[2]))
                            else:
                                yield from self.send_message(message.channel,
                                                             "Plugin `{}` is already loaded.".format(args[2]))
                    elif args[1] == "unload":
                        if len(args) > 2:
                            if plugins[args[2].lower()]:
                                yield from self.save_plugin(args[2])
                                unload_plugin(args[2].lower())
                                yield from self.send_message(message.channel, "Plugin `{}` unloaded.".format(args[2]))
                            else:
                                yield from self.send_message(message.channel,
                                                             "`{}` is not a plugin. Use `!plugins`.".format(args[2]))
                    else:
                        yield from self.send_message(message.channel, "`{}` is not a valid argument.".format(args[1]))
                else:
                    yield from self.send_message(message.channel,
                                                 "**Plugins:** ```\n"
                                                 "{}```".format(",\n".join(plugins.keys())))

            # Originally just a test command
            elif message.content == "!count":
                if not self.message_count.data.get(message.channel.id):
                    self.message_count.data[message.channel.id] = 0

                self.message_count.data[message.channel.id] += 1
                yield from self.send_message(message.channel, "I have counted `{}` times in this channel.".format(
                    self.message_count.data[message.channel.id]
                ))
                self.message_count.save()

        # Run plugins on_message
        for name, plugin in plugins.items():
            yield from plugin.on_message(self, message, args)


bot = Bot()

if __name__ == "__main__":
    email = input("Email: ")
    password = getpass()
    bot.run(email, password)
