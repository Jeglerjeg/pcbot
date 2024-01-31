""" Plugin for built-in commands.

This script works just like any of the plugins in plugins/
"""

import asyncio
import importlib
import inspect
import logging
import random
from datetime import datetime, timedelta, timezone

import discord

import bot
import plugins
from pcbot import utils, Config, Annotate, config

client = plugins.client  # type: bot.Client

sub = asyncio.subprocess
lambdas = Config("lambdas", data={})
lambda_config = Config("lambda-config", data={"imports": [], "blacklist": []})

code_globals = {}


@plugins.command(name="help", aliases="commands")
async def help_(message: discord.Message, command: str.lower = None, *args):
    """ Display commands or their usage and description. """
    command_prefix = config.guild_command_prefix(message.guild)

    # Display the specific command
    if command:
        if command.startswith(command_prefix):
            command = command[len(command_prefix):]

        cmd = plugins.get_command(command)
        if not cmd:
            return

        # Get the specific command with arguments and send the help
        cmd = plugins.get_sub_command(cmd, *args)
        embed = discord.Embed(color=message.author.color)
        embed.description = plugins.format_help(cmd, message.guild, message)
        await client.send_message(message.channel, embed=embed)

    # Display every command
    else:
        commands = []

        for plugin in plugins.all_values():
            # Only go through plugins with actual commands
            if not getattr(plugin, "__commands", False):
                continue

            # Add all commands that the user can use
            for cmd in plugin.__commands:
                if not cmd.hidden and plugins.can_use_command(cmd, message.author, message.channel):
                    commands.append(cmd.name_prefix(message.guild).split()[0])

        commands = ", ".join(sorted(commands))

        m = f"**Commands**: ```{commands}```Use `{command_prefix}help <command>`, " \
            f"`{command_prefix}<command> {config.help_arg[0]}` or " \
            f"`{command_prefix}<command> {config.help_arg[1]}` for command specific help."
        embed = discord.Embed(color=message.author.color)
        embed.description = m
        await client.send_message(message.channel, embed=embed)


@plugins.command(hidden=True)
async def setowner(message: discord.Message):
    """ Set the bot owner. Only works in private messages. """
    if not isinstance(message.channel, discord.abc.PrivateChannel):
        return

    assert not plugins.owner_cfg.data, "An owner is already set."

    owner_code = str(random.randint(100, 999))
    logging.critical("Owner code for assignment: %s", owner_code)

    await client.say(message, "A code has been printed in the console for you to repeat within 60 seconds.")

    def check(m):
        return m.content == owner_code and m.channel == message.channel

    try:
        user_code = await client.wait_for_message(timeout=60, check=check)
    except asyncio.TimeoutError:
        await client.say(message, "You failed to send the desired code.")
        return

    if user_code:
        await client.say(message, "You have been assigned bot owner.")
        plugins.owner_cfg.data = str(message.author.id)
        await plugins.owner_cfg.asyncsave()


@plugins.command(owner=True)
async def stop(message: discord.Message):
    """ Stops the bot. """
    await client.say(message, "\N{COLLISION SYMBOL}\N{PISTOL}")
    await plugins.save_plugins()
    await client.close()


@plugins.command(owner=True)
async def update(message: discord.Message):
    """ Update the bot by running `git pull`. """
    await client.say(message, f'```diff\n{await utils.subprocess("git", "pull", no_stderr=True)}```')


@update.command(owner=True)
async def reset(message: discord.Message):
    """ **RESET THE HEAD** before updating. This removes all local changes done to the repository
    (excluding the .gitignore files).
    """
    confirmed = await utils.confirm(message, "Are you sure you want to remove all local changes?")
    assert confirmed, "Aborted."

    await utils.subprocess("git", "reset", "--hard")
    await update(message)


@plugins.command(owner=True)
async def game(message: discord.Message, name: Annotate.Content = None):
    """ Stop playing or set game to `name`. """
    await client.change_presence(activity=discord.Game(name=name))
    await client.say(message, f"**Set the game to** `{name}`." if name else "**No longer playing.**")


@game.command(owner=True)
async def stream(message: discord.Message, url: str, title: Annotate.Content):
    """ Start streaming a game. """
    await client.change_presence(activity=discord.Streaming(name=title, url=url))
    await client.say(message, f"Started streaming **{title}**.")


@plugins.command(name="as", owner=True)
async def do_as(message: discord.Message, member: discord.Member, command: Annotate.Content):
    """ Execute a command as the specified member. """
    message.author = member
    message.content = command
    await client.on_message(message)


async def send_result(channel: discord.TextChannel, result, time_elapsed: timedelta):
    """ Sends eval results. """
    if isinstance(result, discord.Embed):
        await client.send_message(channel, embed=result)
    else:
        embed = discord.Embed(color=channel.guild.me.color, description=f"```py\n{result}```")
        embed.set_footer(text=f"Time elapsed: {time_elapsed.total_seconds() * 1000:.3f}ms")
        await client.send_message(channel, embed=embed)


@plugins.command(owner=True)
async def do(message: discord.Message, python_code: Annotate.Code):
    """ Execute python code. """
    code_globals.update({"message": message, "client": client,
                         "author": message.author, "guild": message.guild, "channel": message.channel})

    # Create an async function so that we can await it using the result of eval
    python_code = "async def do_session():\n    " + "\n    ".join(line for line in python_code.split("\n"))
    try:
        exec(python_code, code_globals)
    except SyntaxError as e:
        await client.say(message, "```" + utils.format_syntax_error(e) + "```")
        return

    before = datetime.now()
    try:
        result = await eval("do_session()", code_globals)
    except Exception as e:
        await client.say(message, "```" + utils.format_exception(e) + "```")
    else:
        if result:
            await send_result(message.channel, result, datetime.now() - before)


@plugins.command(name="eval", owner=True)
async def eval_(message: discord.Message, python_code: Annotate.Code):
    """ Evaluate a python expression. Can be any python code on one
    line that returns something. Coroutine generators will by awaited.
    """
    code_globals.update({"message": message, "client": client,
                         "author": message.author, "guild": message.guild, "channel": message.channel})

    before = datetime.now()
    try:
        result = eval(python_code, code_globals)
        if inspect.isawaitable(result):
            result = await result
    except SyntaxError as e:
        result = utils.format_syntax_error(e)
    except Exception as e:
        result = utils.format_exception(e)

    await send_result(message.channel, result, datetime.now() - before)


@plugins.command(name="plugin", hidden=True, aliases="pl")
async def plugin_(message: discord.Message):
    """ Manage plugins.
        **Owner command unless no argument is specified.**
        """
    await client.say(message, f'**Plugins:** ```{", ".join(plugins.all_keys())}```')


@plugin_.command(aliases="r", pos_check=False, owner=True)
async def reload(message: discord.Message, *names: str.lower):
    """ Reloads all plugins or the specified plugin. """
    if names:
        reloaded = []
        for name in names:
            if not plugins.get_plugin(name):
                await client.say(message, f"`{name}` is not a plugin.")
                continue

            # The plugin entered is valid so we reload it
            await plugins.save_plugin(name)
            await plugins.call_reload(name)
            reloaded.append(name)

        if reloaded:
            await client.say(message, f'Reloaded plugin{"s" if len(reloaded) > 1 else ""} `{", ".join(reloaded)}`.')
    else:
        # Reload all plugins
        await plugins.save_plugins()

        for plugin_name in plugins.all_keys():
            await plugins.call_reload(plugin_name)

        await client.say(message, "All plugins reloaded.")


@plugin_.command(owner=True, error="You need to specify the name of the plugin to load.")
async def load(message: discord.Message, name: str.lower):
    """ Loads a plugin. """
    assert not plugins.get_plugin(name), f"Plugin `{name}` is already loaded."

    # The plugin isn't loaded so we'll try to load it
    assert plugins.load_plugin(name), f"Plugin `{name}` could not be loaded."

    # The plugin was loaded successfully
    await client.say(message, f"Plugin `{name}` loaded.")


@plugin_.command(owner=True, error="You need to specify the name of the plugin to unload.")
async def unload(message: discord.Message, name: str.lower):
    """ Unloads a plugin. """
    assert plugins.get_plugin(name), f"`{name}` is not a loaded plugin."

    # The plugin is loaded so we unload it
    await plugins.save_plugin(name)
    plugins.unload_plugin(name)
    await client.say(message, f"Plugin `{name}` unloaded.")


@plugins.command(name="lambda", hidden=True)
async def lambda_(message: discord.Message):
    """ Create commands. See `{pre}help do` for information on how the code works.

    **In addition**, there's the `arg(i, default=0)` function for getting arguments in positions,
    where the default argument is what to return when the argument does not exist.
    **Owner command unless no argument is specified.**
    """
    await client.say(message, "**Lambdas:** ```\n" f'{", ".join(sorted(lambdas.data.keys()))}```')


@lambda_.command(aliases="a", owner=True)
async def add(message: discord.Message, trigger: str, python_code: Annotate.Code):
    """ Add a command that runs the specified python code. """
    lambdas.data[trigger] = python_code
    await lambdas.asyncsave()
    await client.say(message, f"Command `{trigger}` set.")


@lambda_.command(aliases="r", owner=True)
async def remove(message: discord.Message, trigger: str):
    """ Remove a command. """
    assert trigger in lambdas.data, f"Command `{trigger}` does not exist."

    # The command specified exists and we remove it
    del lambdas.data[trigger]
    await lambdas.asyncsave()
    await client.say(message, f"Command `{trigger}` removed.")


@lambda_.command(owner=True)
async def enable(message: discord.Message, trigger: str):
    """ Enable a command. """
    # If the specified trigger is in the blacklist, we remove it
    if trigger in lambda_config.data["blacklist"]:
        lambda_config.data["blacklist"].remove(trigger)
        await lambda_config.asyncsave()
        await client.say(message, f"Command `{trigger}` enabled.")
    else:
        assert trigger in lambdas.data, f"Command `{trigger}` does not exist."

        # The command exists so surely it must be disabled
        await client.say(message, f"Command `{trigger}` is already enabled.")


@lambda_.command(owner=True)
async def disable(message: discord.Message, trigger: str):
    """ Disable a command. """
    # If the specified trigger is not in the blacklist, we add it
    if trigger not in lambda_config.data["blacklist"]:
        lambda_config.data["blacklist"].append(trigger)
        await lambda_config.asyncsave()
        await client.say(message, f"Command `{trigger}` disabled.")
    else:
        assert trigger in lambdas.data, f"Command `{trigger}` does not exist."

        # The command exists so surely it must be disabled
        await client.say(message, f"Command `{trigger}` is already disabled.")


def import_module(module: str, attr: str = None):
    """ Remotely import a module or attribute from module into code_globals. """
    # The name of the module in globals
    # If attr starts with :, it defines a new name for the module as whatever follows the colon
    # When nothing follows this colon, the name is set to the last subcommand in the given module
    name = attr or module
    if attr and attr.startswith(":"):
        name = attr[1:] or module.split(".")[-1].replace(" ", "")

    try:
        imported = importlib.import_module(module)
    except ImportError as error:
        e = f"Unable to import module {module}."
        logging.error(e)
        raise ImportError from error
    else:
        if attr and not attr.startswith(":"):
            if hasattr(imported, attr):
                code_globals[name] = getattr(imported, attr)
            else:
                e = f"Module {module} has no attribute {attr}"
                logging.error(e)
                raise KeyError(e)
        else:
            code_globals[name] = imported

    return name


@lambda_.command(name="import", owner=True)
async def import_(message: discord.Message, module: str, attr: str = None):
    """ Import the specified module. Specifying `attr` will act like `from attr import module`.

    If the given attribute starts with a colon :, the name for the module will be defined as
    whatever follows the colon character. If nothing follows, the last subcommand in the module
    is used.
    """
    try:
        name = import_module(module, attr)
    except ImportError:
        await client.say(message, f"Unable to import `{module}`.")
    except KeyError:
        await client.say(message, f"Unable to import `{attr}` from `{module}`.")
    else:
        # There were no errors when importing, so we add the name to our startup imports
        lambda_config.data["imports"].append((module, attr))
        await lambda_config.asyncsave()
        await client.say(message, f"Imported and setup `{name}` for import.")


@lambda_.command()
async def source(message: discord.Message, trigger: str):
    """ Disable source of a command """
    assert trigger in lambdas.data, f"Command `{trigger}` does not exist."

    # The command exists so we display the source
    await client.say(message, f"```py\n{lambdas.data[trigger]}```")


@plugins.command(hidden=True)
async def ping(message: discord.Message):
    """ Tracks the time spent parsing the command and sending a message. """
    # Track the time it took to receive a message and send it.
    start_time = datetime.now()
    first_message = await client.say(message, "Pong!")
    stop_time = datetime.now()

    # Edit our message with the tracked time (in ms)
    time_elapsed = (stop_time - start_time).microseconds / 1000
    await first_message.edit(content=f"Pong! `{time_elapsed:.4f}ms`")


async def get_changelog(num: int):
    """ Get the latest commit messages from PCBOT. """
    since = datetime.now(timezone.utc) - timedelta(days=7)
    commits = await utils.download_json(f"https://api.github.com/repos/{config.github_repo}commits",
                                        since=since.strftime("%Y-%m-%dT00:00:00"))
    changelog = []

    # Go through every commit and add "- " in front of the first line and "  " for all other lines
    # Also add dates after each commit
    for commit in commits[:num]:
        commit_message = commit["commit"]["message"]
        commit_date = commit["commit"]["committer"]["date"]

        formatted_commit = []

        for i, line in enumerate(commit_message.split("\n")):
            if not line == "":
                line = ("- " if i == 0 else "  ") + line

            formatted_commit.append(line)

        # Add the date as well as the
        changelog.append("\n".join(formatted_commit) + "\n  " + commit_date.replace("T", " ").replace("Z", ""))

    # Return formatted changelog
    return "```\n{}```".format("\n\n".join(changelog))


@plugins.command(name=config.name.lower())
async def bot_hub(message: discord.Message):
    """ Display basic information. """
    app_info = await client.application_info()

    await client.say(message, f"**{config.version}** - **{app_info.name}** ```elm\n"
                              f"Owner   : {str(app_info.owner)}\n"
                              f'Up      : {client.time_started.strftime("%d-%m-%Y %H:%M:%S")} UTC\n'
                              f"Guilds  : {len(client.guilds)}```"
                              f'{app_info.description}'
                     )


@bot_hub.command(name="changelog")
async def changelog_(message: discord.Message, num: utils.int_range(f=1) = 3):
    """ Get `num` requests from the changelog. Defaults to 3. """
    await client.say(message, await get_changelog(num))


@bot_hub.command(name="prefix", permissions="administrator", disabled_pm=True)
async def set_prefix(message: discord.Message, prefix: str = None):
    """ Set the bot prefix. **The prefix is case sensitive and may not include spaces.** """
    await config.set_guild_config(message.guild, "command_prefix", utils.split(prefix)[0] if prefix else None)

    pre = config.default_command_prefix if prefix is None else prefix
    await client.say(message, f"Set the guild prefix to `{pre}`.")


@bot_hub.command(name="case", permissions="administrator", disabled_pm=True)
async def set_case_sensitivity(message: discord.Message, value: plugins.true_or_false):
    """ Enable or disable case sensitivity in command triggers. """
    await config.set_guild_config(message.guild, "case_sensitive_commands", value)
    await client.say(message,
                     f'**{"Enabled" if value else "Disabled"}** case sensitive command triggers in this guild.')


def init():
    """ Import any imports for lambdas. """

    # Add essential globals for "do", "eval" and "lambda" commands
    class Plugin:
        """ Class for returning plugins easily by using attributes. """

        def __getattr__(self, item):
            return plugins.get_plugin(item)

        @staticmethod
        def __call___(item):
            """ Backwards compatibility for old plugin(name) method. """
            return plugins.get_plugin(item)

    code_globals.update({
        "utils": utils, "datetime": datetime, "timedelta": timedelta,
        "random": random, "asyncio": asyncio, "plugins": plugins,
        "plugin": Plugin(), "command": plugins.get_command, "execute": plugins.execute
    })

    # Import modules for "do", "eval" and "lambda" commands
    for module, attr in lambda_config.data["imports"]:
        # Let's not import any already existing modules
        if (attr or module) not in code_globals:
            try:
                import_module(module, attr)
            except (KeyError, ImportError):  # The module doesn't work, so we skip it
                pass
            else:
                continue

        # Something went wrong and we'll remove the module from the config
        lambda_config.data["imports"].remove([module, attr])
        lambda_config.save()


@plugins.event()
async def on_message(message: discord.Message):
    """ Perform lambda commands. """
    args = utils.split(message.content)
    if not args:
        return

    # Check if the command is a lambda command and is not disabled (in the blacklist)
    if args[0] in lambdas.data and args[0] not in lambda_config.data["blacklist"]:
        def arg(i, default=0):
            if len(args) > i:
                return args[i]

            return default

        code_globals.update({"arg": arg, "args": args, "message": message, "client": client,
                             "author": message.author, "guild": message.guild, "channel": message.channel})
        python_code = lambdas.data[args[0]]

        # Create an async function so that we can await it using the result of eval
        python_code = "async def lambda_session():\n    " + "\n    ".join(line for line in python_code.split("\n"))
        try:
            exec(python_code, code_globals)
        except SyntaxError as e:
            if plugins.is_owner(message.author):
                await client.say(message, "```" + utils.format_syntax_error(e) + "```")
            else:
                logging.warning("An exception occurred when parsing lambda command:"
                                "\n%s", utils.format_syntax_error(e))
            return True

        # Execute the command
        try:
            await eval("lambda_session()", code_globals)
        except AssertionError as e:  # Send assertion errors to the core module
            raise AssertionError from e
        except Exception as e:
            if plugins.is_owner(message.author):
                await client.say(message, "```" + utils.format_exception(e) + "```")
            else:
                logging.warning("An exception occurred when parsing lambda command:"
                                "\n%s", utils.format_exception(e))

        return True


# Initialize the plugin's modules
init()
