import copy
from enum import Enum

from plugins.osulib.constants import mode_names
from pcbot import utils


class UpdateModes(Enum):
    """ Enums for the various notification update modes.
    Values are valid names in a tuple. """
    Full = ("full", "on", "enabled", "f", "e")
    No_Mention = ("no_mention", "nomention", "silent")
    Minimal = ("minimal", "quiet", "m")
    PP = ("pp", "diff", "p")
    Disabled = ("none", "off", "disabled", "n", "d")

    @classmethod
    def get_mode(cls, mode: str):
        """ Return the mode with the specified name. """
        for enum in cls:
            if mode.lower() in enum.value:
                return enum

        return None


class Mods(Enum):
    """ Enum for displaying mods. """
    NF = 0
    EZ = 1
    TD = 2
    HD = 3
    HR = 4
    SD = 5
    DT = 6
    RX = 7
    HT = 8
    NC = 9
    FL = 10
    AU = 11
    SO = 12
    AP = 13
    PF = 14
    Key4 = 15
    Key5 = 16
    Key6 = 17
    Key7 = 18
    Key8 = 19
    FI = 20
    RD = 21
    Cinema = 22
    Key9 = 24
    KeyCoop = 25
    Key1 = 26
    Key3 = 27
    Key2 = 28
    ScoreV2 = 29
    LastMod = 30

    def __new__(cls, num):
        """ Convert the given value to 2^num. """
        obj = object.__new__(cls)
        obj._value_ = 2 ** num
        return obj

    @classmethod
    def list_mods(cls, bitwise: int):
        """ Return a list of mod enums from the given bitwise (enabled_mods in the osu! API) """
        bin_str = str(bin(bitwise))[2:]
        bin_list = [int(d) for d in bin_str[::-1]]
        mods_bin = (pow(2, i) for i, d in enumerate(bin_list) if d == 1)
        mods = [cls(mod) for mod in mods_bin]

        # Manual checks for multiples
        if Mods.DT in mods and Mods.NC in mods:
            mods.remove(Mods.DT)

        return mods

    @staticmethod
    def format_mod_settings(mods: list):
        """ Add mod settings to the acronym for formatting purposes"""
        for mod in mods:
            if "settings" not in mod:
                continue
            settings = []
            if mod["acronym"] == "DT" or mod["acronym"] == "NC" or mod["acronym"] == "HT" or mod["acronym"] == "DC":
                if "speed_change" in mod["settings"]:
                    settings.append(f'{utils.format_number(mod["settings"]["speed_change"], 2)}x')
            if mod["acronym"] == "DA":
                if "circle_size" in mod["settings"]:
                    settings.append(f'CS{utils.format_number(mod["settings"]["circle_size"], 2)}')
                if "approach_rate" in mod["settings"]:
                    settings.append(f'AR{utils.format_number(mod["settings"]["approach_rate"], 2)}')
                if "drain_rate" in mod["settings"]:
                    settings.append(f'HP{utils.format_number(mod["settings"]["drain_rate"], 2)}')
                if "overall_difficulty" in mod["settings"]:
                    settings.append(f'OD{utils.format_number(mod["settings"]["overall_difficulty"], 2)}')
            if settings:
                mod["acronym"] = f'{mod["acronym"]}({",".join(settings)})'
        return mods

    @classmethod
    def format_mods(cls, mods, score_display: bool = False):
        """ Return a string with the mods in a sorted format, such as DTHD.

        mods is either a bitwise or a list of mod enums.
        """
        if isinstance(mods, int):
            mods = cls.list_mods(mods)
        assert isinstance(mods, list)

        if score_display:
            mods = cls.format_mod_settings(copy.deepcopy(mods))
            return ",".join((mod["acronym"] for mod in mods) if mods else ["Nomod"])

        return "".join((mod["acronym"] for mod in mods) if mods else ["Nomod"])


class GameMode(Enum):
    """ Enum for gamemodes. """
    osu = 0
    taiko = 1
    fruits = 2
    mania = 3

    @classmethod
    def get_mode(cls, mode: str):
        """ Return the mode with the specified string. """
        for mode_name, names in mode_names.items():
            for name in names:
                if name.lower().startswith(mode.lower()):
                    return GameMode.__members__[mode_name]

        return None
