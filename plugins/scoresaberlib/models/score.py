from datetime import datetime, timezone
from typing import Optional

from dateutil import parser

from plugins.scoresaberlib.models.player import ScoreSaberLeaderboardPlayer


class ScoreSaberScore:
    id: int
    player: Optional[ScoreSaberLeaderboardPlayer]
    rank: int
    base_score: int
    modified_score: int
    pp: float
    weight: float
    modifiers: str
    multiplier: float
    bad_cuts: int
    missed_notes: int
    max_combo: int
    full_combo: bool
    hmd: int
    time_set: datetime
    has_replay: bool
    def __init__(self, raw_data: dict):
        self.id = raw_data["id"]
        if "leaderboardPlayerInfo" in raw_data:
            self.player = ScoreSaberLeaderboardPlayer(raw_data["leaderboardPlayerInfo"])
        else:
            self.player = None
        self.rank = raw_data["rank"]
        self.base_score = raw_data["baseScore"]
        self.modified_score = raw_data["modifiedScore"]
        self.pp = raw_data["pp"]
        self.weight = raw_data["weight"]
        self.modifiers = raw_data["modifiers"]
        self.multiplier = raw_data["multiplier"]
        self.bad_cuts = raw_data["badCuts"]
        self.missed_notes = raw_data["missedNotes"]
        self.max_combo = raw_data["maxCombo"]
        self.full_combo = raw_data["fullCombo"]
        self.hmd = raw_data["hmd"]
        self.time_set = parser.isoparse(raw_data["timeSet"]).replace(tzinfo=timezone.utc)
        self.has_replay = raw_data["hasReplay"]

    def __repr__(self):
        return str(self.to_dict())

    def to_dict(self):
        readable_dict = {}
        for attr, value in self.__dict__.items():
            if isinstance(value, datetime):
                readable_dict[attr] = value.isoformat()
                continue
            readable_dict[attr] = value
        return readable_dict