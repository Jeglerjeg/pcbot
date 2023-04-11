from datetime import datetime
from random import randint
from typing import Optional

from plugins.osulib.constants import not_playing_skip
from plugins.osulib.enums import GameMode


class OsuUser:
    id: int
    username: str
    avatar_url: str
    country_code: str
    mode: GameMode
    pp: float
    accuracy: float
    country_rank: int
    global_rank: int
    max_combo: int
    ranked_score: int
    ticks: Optional[int]
    time_cached: Optional[datetime]

    def __init__(self, data, from_db: bool = True):
        if from_db:
            self.id = data.id
            self.username = data.username
            self.avatar_url = data.avatar_url
            self.country_code = data.country_code
            self.mode = GameMode(data.mode)
            self.pp = data.pp
            self.accuracy = data.accuracy
            self.country_rank = data.country_rank
            self.global_rank = data.global_rank
            self.max_combo = data.max_combo
            self.ranked_score = data.ranked_score
            self.ticks = data.ticks
            self.time_cached = datetime.fromtimestamp(data.time_cached)
        else:
            self.id = data["id"]
            self.username = data["username"]
            self.avatar_url = data["avatar_url"]
            self.country_code = data["country_code"]
            self.mode = GameMode.get_mode(data["playmode"])
            self.pp = data["statistics"]["pp"] if data["statistics"]["pp"] else 0.0
            self.accuracy = data["statistics"]["hit_accuracy"] if data["statistics"]["hit_accuracy"] else 0.0
            self.country_rank = data["statistics"]["country_rank"] if data["statistics"]["country_rank"] else 0
            self.global_rank = data["statistics"]["global_rank"] if data["statistics"]["global_rank"] else 0
            self.max_combo = data["statistics"]["maximum_combo"] if data["statistics"]["maximum_combo"] else 0
            self.ranked_score = data["statistics"]["ranked_score"] if data["statistics"]["ranked_score"] else 0
            self.ticks = None
            self.time_cached = None

    def to_db_query(self, discord_id: int, new_user: bool = False, ticks: int = None):
        if new_user:
            ticks = randint(0, not_playing_skip - 1)

        return {"discord_id": discord_id, "id": self.id, "username": self.username, "avatar_url": self.avatar_url,
                "country_code": self.country_code, "mode": self.mode.value, "pp": self.pp, "accuracy": self.accuracy,
                "country_rank": self.country_rank, "global_rank": self.global_rank, "max_combo": self.max_combo,
                "ranked_score": self.ranked_score, "ticks": ticks, "time_cached": int(self.time_cached.timestamp())}

    def __getitem__(self, item):
        return getattr(self, item)

    def __repr__(self):
        return str(self.to_dict())

    def to_dict(self):
        readable_dict = {}
        for attr, value in self.__dict__.items():
            if isinstance(value, GameMode):
                readable_dict[attr] = value.name
                continue
            if isinstance(value, datetime):
                readable_dict[attr] = value.isoformat()
                continue
            readable_dict[attr] = value
        return readable_dict

    def add_tick(self):
        self.ticks += 1

    def set_time_cached(self, time: datetime):
        self.time_cached = time
