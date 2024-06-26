""" PCBOT's plugin handler.
"""

import importlib
import inspect
import logging
import os
from collections import namedtuple, defaultdict
from functools import partial

import discord
import pendulum

from pcbot import config, Annotate, identifier_prefix, format_exception

loaded_plugins = {}
events = defaultdict(list)
Command = namedtuple("Command", "name name_prefix aliases owner permissions roles guilds "
                                "usage description function parent sub_commands depth hidden error pos_check "
                                "disabled_pm doc_args")
lengthy_annotations = (Annotate.Content, Annotate.CleanContent, Annotate.LowerContent,
                       Annotate.LowerCleanContent, Annotate.Code)
argument_format = "{open}{name}{suffix}{close}"

owner_cfg = config.Config("owner")
disabled_plugins_config = config.Config("disabled_plugins", pretty=True, data={"disabled_plugins": []})
CoolDown = namedtuple("CoolDown", "date command specific")
cooldown_data = defaultdict(list)  # member: []

client = None  # The client. This variable holds the bot client and is to be used by plugins


def set_client(c: discord.Client):
    """ Sets the client. Should be used before any plugins are loaded. """
    global client
    client = c


def get_plugin(name):
    """ Return the loaded plugin by name or None. """
    if name in loaded_plugins:
        return loaded_plugins[name]

    return None


def all_items():
    """ Return a view object of every loaded plugin by key, value. """
    return loaded_plugins.items()


def all_keys():
    """ Return a view object of every loaded plugin by key. """
    return loaded_plugins.keys()


def all_values():
    """ Return a view object of every loaded plugin by value. """
    return loaded_plugins.values()


def _format_usage(func, pos_check):
    """ Parse and format the usage of a command. """
    signature = inspect.signature(func)
    usage = []

    for i, param in enumerate(signature.parameters.values()):
        if i == 0:
            continue

        # If there is a placeholder annotation, this command is a group and should not have a formatted usage
        if getattr(param.annotation, "__name__", "") == "placeholder":
            return None

        param_format = getattr(param.annotation, "argument", argument_format)
        name = param.name
        opened, closed, suffix = "[", "]", ""

        if param.default is param.empty and (param.kind is not param.VAR_POSITIONAL or pos_check is True):
            opened, closed = "<", ">"

        if param.kind is param.VAR_POSITIONAL or param.annotation in lengthy_annotations \
                or getattr(param.annotation, "allow_spaces", False):
            suffix = " ..."

        usage.append(param_format.format(open=opened, close=closed, name=name, suffix=suffix))

    return " ".join(usage)


def _parse_str_list(obj, name, cmd_name):
    """ Return the list from the parsed str or an empty list if object is None. """
    if isinstance(obj, str):
        return obj.split(" ")
    if isinstance(obj, list):
        return obj

    if obj is not None:
        logging.warning("Invalid parameter in command '%s': %s must be a str or a list", cmd_name, name)
    return []


def _name_prefix(name, parent):
    """ Generate a function for generating the command's prefix in the given guild. """

    def decorator(guild: discord.Guild):
        pre = config.guild_command_prefix(guild)
        return parent.name_prefix(guild) + " " + name if parent is not None else pre + name

    return decorator


def command(**options):
    """ Decorator function that adds a command to the module's __commands dict.
    This allows the user to dynamically create commands without the use of a dictionary
    in the module itself.

    Command attributes are:
        name        : str         : The commands name. Will use the function name by default.
        aliases     : str / list  : Aliases for this command as a str separated by whitespace or a list.
        usage       : str         : The command usage following the command trigger, e.g the "[cmd]" in "help [cmd]".
        description : str         : The commands description. By default this uses the docstring of the function.
        hidden      : bool        : Whether or not to show this function in the builtin help command.
        error       : str         : An optional message to send when argument requirements are not met.
        pos_check   : func / bool : An optional check function for positional arguments, eg: pos_check=lambda s: s
                                    When this attribute is a bool and True, force positional arguments.
        doc_args    : dict        : Arguments to send to the docstring under formatting.
        owner       : bool        : When True, only triggers for the owner.
        permissions : str / list  : Permissions required for this command as a str separated by whitespace or a list.
        roles       : str / list  : Roles required for this command as a str separated by whitespace or a list.
        guilds      : list[int]   : a list of valid guild ids.
        disabled_pm : bool        : Command is disabled in PMs when True.
    """

    def decorator(func):
        # Make sure the first parameter in the function is a message object
        params = inspect.signature(func).parameters
        param = params[list(params.keys())[0]]  # The first parameter
        if not param.name == "message" and param.annotation is not discord.Message:
            raise SyntaxError("First command parameter must be named message or be of type discord.Message")

        # Define all function stats
        name = options.get("name", func.__name__)
        aliases = options.get("aliases")
        hidden = options.get("hidden", False)
        parent = options.get("parent", None)
        depth = parent.depth + 1 if parent is not None else 0
        name_prefix = _name_prefix(name, parent)
        error = options.get("error", None)
        pos_check = options.get("pos_check", False)
        description = options.get("description") or func.__doc__ or "Undocumented."
        disabled_pm = options.get("disabled_pm", False)
        doc_args = options.get("doc_args", {})
        owner = options.get("owner", False)
        permissions = options.get("permissions")
        roles = options.get("roles")
        guilds = options.get("guilds")

        # Parse str lists
        aliases = _parse_str_list(aliases, "aliases", name)
        permissions = _parse_str_list(permissions, "permissions", name)
        roles = _parse_str_list(roles, "roles", name)

        # Set the usage of this command
        usage_suffix = options.get("usage", _format_usage(func, pos_check))

        # Convert to a function that uses the name_prefix
        if usage_suffix is not None:
            def usage(guild):
                return name_prefix(guild) + " " + usage_suffix
        else:
            def usage(guild):
                return None

        # Properly format description when using docstrings
        # Kinda like markdown; new line = (blank line) or (/ at end of line)
        if description == func.__doc__:
            new_desc = ""

            for line in description.split("\n"):
                line = line.strip()

                if line == "/":
                    new_desc += "\n\n"
                elif line.endswith("/"):
                    new_desc += line[:-1] + "\n"
                elif line == "":
                    new_desc += "\n"
                else:
                    new_desc += line + " "

            description = new_desc

        # Format the description for any optional keys, and store the {pre} argument for later
        description = description.replace("{pre}", "%pre%").format(**doc_args)
        description = description.replace("%pre%", "{pre}")

        # Notify the user about command permissions
        if owner:
            description += "\n:information_source:`Only the bot owner can execute this command.`"
        if permissions:
            description += '\n:information_source:`Permissions required: ' \
                           f'{", ".join(" ".join(s.capitalize() for s in p.split("_")) for p in permissions)}`'
        if roles:
            description += f'\n:information_source:`Roles required: {", ".join(roles)}`'

        # Load the plugin the function is from, so that we can modify the __commands attribute
        loaded_plugin = inspect.getmodule(func)
        commands = getattr(loaded_plugin, "__commands", [])

        # Assert that __commands is usable and that this command doesn't already exist
        if not isinstance(commands, list):
            raise NameError("__commands is reserved for the plugin's commands, and must be of type list")

        # Assert that there are no commands already defined with the given name in this scope
        if any(cmd.name == name for cmd in (commands if not parent else parent.sub_commands)):
            raise KeyError("You can't assign two commands with the same name")

        # Create our command
        cmd = Command(name=name, aliases=aliases, usage=usage, name_prefix=name_prefix, description=description,
                      function=func, parent=parent, sub_commands=[], depth=depth, hidden=hidden, error=error,
                      pos_check=pos_check, disabled_pm=disabled_pm, doc_args=doc_args, owner=owner,
                      permissions=permissions, roles=roles, guilds=guilds)

        # If the command has a parent (is a subcommand)
        if parent:
            parent.sub_commands.append(cmd)
        else:
            commands.append(cmd)

        # Update the plugin's __commands attribute
        setattr(loaded_plugin, "__commands", commands)

        # Create a decorator for the command function that automatically assigns the parent
        setattr(func, "command", partial(command, parent=cmd))

        # Add the cmd attribute to this function, in order to get the command assigned to the function
        setattr(func, "cmd", cmd)

        logging.debug("Registered %s %s from plugin %s", "subcommand" if parent else "command", name,
                      loaded_plugin.__name__)
        return func

    return decorator


def event(name=None, bot=False, self=False):
    """ Decorator to add event listeners in plugins. """

    def decorator(func):
        event_name = name or func.__name__

        if event_name == "on_ready":
            logging.warning("on_ready in plugins is reserved for bot initialization only (use it without the "
                            "event listener call). It was not added to the list of events.")
            return func

        if self and not bot:
            logging.warning("self=True has no effect in event %s. Consider setting bot=True", func.__name__)

        # Set the bot attribute, which determines whether the function will be triggered by messages from bot accounts
        # The self attribute denotes if own messages will be logged
        setattr(func, "bot", bot)
        setattr(func, "self", self)

        # Register our event
        events[event_name].append(func)
        return func

    return decorator


def argument(arg_format=argument_format, *, pass_message=False, allow_spaces=False):
    """ Decorator for easily setting custom argument usage formats. """

    def decorator(func):
        func.argument = arg_format
        func.pass_message = pass_message
        func.allow_spaces = allow_spaces
        return func

    return decorator


def format_usage(cmd: Command, guild: discord.Guild, message: discord.Message, sub_command_format: bool = False):
    """ Format the usage string of the given command. Places any usage
    of a sub command on a newline.

    :param cmd: Type Command.
    :param guild: The guild to generate the usage in.
    :param message: The message object to run permission checks on.
    :param sub_command_format: Whether or not the command should be formatted as a subcommand.
    :return: str: formatted usage.
    """
    if cmd.hidden and cmd.parent is not None:
        return None

    if not can_use_command(cmd, message.author, message.channel) and sub_command_format:
        return None

    command_prefix = config.guild_command_prefix(guild)
    usage = [cmd.usage(guild)]
    for sub_command in cmd.sub_commands:
        # Recursively format the usage of the next sub commands
        formatted = format_usage(sub_command, guild, message, sub_command_format=True)

        if formatted:
            usage.append(formatted)

    return "\n".join(s for s in usage if s is not None).format(pre=command_prefix) if usage else None


def format_help(cmd: Command, guild: discord.Guild, message: discord.Message, no_subcommand: bool = False):
    """ Format the help string of the given command as a message to be sent.

    :param cmd: Type Command
    :param guild: The guild to generate help in.
    :param message: The message object format_usage runs permission checks on.
    :param no_subcommand: Use only the given command's usage.
    :return: str: help message.
    """
    usage = cmd.usage(guild) if no_subcommand else format_usage(cmd, guild, message)

    # If there is no usage, the command isn't supposed to be displayed as such
    # Therefore, we switch to using the parent command instead
    if usage is None and cmd.parent is not None:
        return format_help(cmd.parent, guild, message)

    command_prefix = config.guild_command_prefix(guild)
    desc = cmd.description.format(pre=command_prefix)

    # Format aliases
    alias_format = ""
    if cmd.aliases:
        # Don't add blank space unless necessary
        if not desc.strip().endswith("```"):
            alias_format += "\n"
        formatted_aliases = ", ".join((command_prefix if identifier_prefix.match(alias[0]) and cmd.parent is None
                                       else "") + alias for alias in cmd.aliases)
        alias_format += f'**Aliases**: ```{formatted_aliases}```'

    return f"**Usage**: ```{usage}```**Description**: {desc}{alias_format}"


def parent_attr(cmd: Command, attr: str):
    """ Return the attribute from the parent if there is one. """
    return getattr(cmd.parent, attr, False) or getattr(cmd, attr)


def compare_command_name(trigger: str, cmd: Command, case_sensitive: bool = True):
    """ Compare the given trigger with the command's name and aliases.

    :param trigger: a str representing the command name or alias.
    :param cmd: The Command object to compare.
    :param case_sensitive: When True, case is preserved in command name triggers.
    """
    if case_sensitive:
        return trigger == cmd.name or trigger in cmd.aliases

    return trigger.lower() == cmd.name.lower() or trigger.lower() in (name.lower() for name in cmd.aliases)


def get_command(trigger: str, case_sensitive: bool = True):
    """ Find and return a command function from a plugin.

    :param trigger: a str representing the command name or alias.
    :param case_sensitive: When True, case is preserved in command name triggers.
    """
    for loaded_plugin in all_values():
        commands = getattr(loaded_plugin, "__commands", None)

        # Skip any plugin with no commands
        if not commands:
            continue

        for cmd in loaded_plugin.__commands:
            if compare_command_name(trigger, cmd, case_sensitive):
                return cmd

        continue

    return None


def get_sub_command(cmd, *args: str, case_sensitive: bool = True):
    """ Go through all arguments and return any group command function.

    :param cmd: type plugins.Command
    :param args: str of arguments following the command trigger.
    :param case_sensitive: When True, case is preserved in command name triggers.
    """
    for arg in args:
        for sub_cmd in cmd.sub_commands:
            if compare_command_name(arg, sub_cmd, case_sensitive):
                cmd = sub_cmd
                break
        else:
            break

    return cmd


def is_owner(user: discord.User):
    """ Return true if user/member is the assigned bot owner.

    :param user: discord.User, discord.Member or a str representing the user's ID.
    :raises: TypeError: user is wrong type.
    """
    if hasattr(user, 'id'):
        user = str(user.id)
    elif not isinstance(user, str):
        raise TypeError("member must be an instance of discord.User or a str representing the user's ID.")

    if user == owner_cfg.data:
        return True

    return False


def has_permissions(cmd: Command, author: discord.Member, channel: discord.TextChannel):
    """ Return True if the member has permissions to execute the command. """
    if not cmd.permissions:
        return True

    member_perms = channel.permissions_for(author)
    if all(getattr(member_perms, perm, False) for perm in cmd.permissions):
        return True

    return False


def has_roles(cmd: Command, author: discord.Member):
    """ Return True if the member has the required roles.
    """
    if not cmd.roles:
        return True

    member_roles = [r.name for r in author.roles[1:]]
    if any(r in member_roles for r in cmd.roles):
        return True

    return False


def is_valid_guild(cmd: Command, guild: discord.Guild):
    """ Return True if the command is allowed in guild. """
    if not cmd.guilds or guild.id in cmd.guilds:
        return True

    return False


def can_use_command(cmd: Command, author, channel: discord.TextChannel = None):
    """ Return True if the member who sent the message can use this command. """
    if cmd.owner and not is_owner(author):
        return False
    if channel is not None and not has_permissions(cmd, author, channel):
        return False
    if not has_roles(cmd, author):
        return False

    # Handle guild specific commands for both guild and PM commands
    if isinstance(author, discord.User) and cmd.guilds:
        return False
    if isinstance(author, discord.Member) and not is_valid_guild(cmd, author.guild):
        return False

    return True


async def execute(cmd, message: discord.Message, *args, **kwargs):
    """ Execute a command specified by name, alias or command object.
    This is really only useful as a shortcut for other commands.

    :param cmd: either plugins.Command or str
    :param message: required message object in order to execute a command
    :param args, kwargs: any arguments passed into the command.

    :raises: NameError when command does not exist.
    """
    # Get the command object if the given command represents a name
    if not isinstance(cmd, Command):
        cmd = get_command(cmd, config.guild_case_sensitive_commands(message.guild))

    try:
        await cmd.function(message, *args, **kwargs)
    except AttributeError as e:
        raise NameError(f"{cmd} is not a command") from e


def load_plugin(name: str, package: str = "plugins"):
    """ Load a plugin with the name name. If package isn't specified, this
    looks for plugin with specified name in /plugins/

    Any loaded plugin is imported and stored in the self.plugins dictionary.
    """
    if (not name.startswith("__") or not name.endswith("__")) and \
            name not in disabled_plugins_config.data["disabled_plugins"]:
        try:
            loaded_plugin = importlib.import_module(f"{package}.{name}")
        except ImportError as e:
            logging.error("An error occurred when loading plugin %s:\n%s", name, format_exception(e))
            return False
        except Exception as e:
            logging.error("An error occurred when loading plugin %s:\n%s", name, format_exception(e))
            return False

        loaded_plugins[name] = loaded_plugin
        logging.debug("LOADED PLUGIN %s", name)
        return True

    return False


async def on_reload(name: str):
    """ The default on_reload function.
    """
    await reload(name)


async def reload(name: str):
    """ Reload a plugin.

    This must be called from an on_reload function or coroutine.
    """
    if name in loaded_plugins:
        # Remove all registered commands
        if hasattr(loaded_plugins[name], "__commands"):
            delattr(loaded_plugins[name], "__commands")

        # Remove all registered events from the given plugin
        for funcs in events.values():
            for func in funcs:
                if func.__module__.endswith(name):
                    funcs.remove(func)

        loaded_plugins[name] = importlib.reload(loaded_plugins[name])

        logging.debug("Reloaded plugin %s", name)


async def call_reload(name: str):
    """ Initiates reload of plugin. """
    # See if the plugin has an on_reload() function, and call that
    if hasattr(loaded_plugins[name], "on_reload"):
        if callable(loaded_plugins[name].on_reload):
            result = loaded_plugins[name].on_reload(name)
            if inspect.isawaitable(result):
                await result
    else:
        await on_reload(name)


def unload_plugin(name: str):
    """ Unload a plugin by removing it from the plugin dictionary. """
    if name in loaded_plugins:
        del loaded_plugins[name]
        logging.debug("Unloaded plugin %s", name)


def load_plugins(directory: str = "plugins"):
    """ Perform load_plugin(name, directory) on all plugins in the given directory. """
    for plugin_name in os.listdir(f"{directory}/"):
        name = os.path.splitext(plugin_name)[0]

        if not name.endswith("lib"):  # Exclude libraries
            load_plugin(name, directory)


async def save_plugin(name):
    """ Save a plugin's files if it has a save function. """
    if name in all_keys():
        loaded_plugin = get_plugin(name)

        if callable(getattr(loaded_plugin, "save", False)):
            try:
                await loaded_plugin.save(loaded_plugins)
            except Exception as e:
                logging.error("An error occurred when saving plugin %s:\n%s", name, format_exception(e))


async def save_plugins():
    """ Looks for any save function in a plugin and saves.
    Set up for saving on !stop and periodic saving every 30 minutes.
    """
    for name in all_keys():
        await save_plugin(name)


@argument(arg_format="{open}on | off{close}")
def true_or_false(arg: str):
    """ Return True or False flexibly based on the input. """
    if arg.lower() in ("yes", "true", "enable", "1", "on"):
        return True
    if arg.lower() in ("no", "false", "disable", "0", "off"):
        return False

    return None
