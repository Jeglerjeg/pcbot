from datetime import datetime, timezone
from random import randint
from typing import Optional

from plugins.osulib.constants import not_playing_skip
from plugins.osulib.enums import GameMode

from dateutil import parser


class RespektiveScoreRank:
    rank: int
    user_id: int
    username: str
    score: int

    def __init__(self, data):
        self.rank = data["rank"]
        self.user_id = data["user_id"]
        self.username = data["username"]
        self.score = data["score"]


class UserGroup:
    id: int
    identifier: str
    name: str
    short_name: str
    colour: str

    def __init__(self, data: dict):
        self.id = data["id"]
        self.identifier = data["identifier"]
        self.name = data["name"]
        self.short_name = data["short_name"]
        self.colour = data["colour"]

    def __repr__(self):
        return str(self.to_dict())

    def to_dict(self):
        readable_dict = {}
        for attr, value in self.__dict__.items():
            readable_dict[attr] = value
        return readable_dict


class UserGrades:
    ss: int
    ssh: int
    s: int
    sh: int
    a: int

    def __init__(self, data: dict):
        self.ss = data["ss"]
        self.ssh = data["ssh"]
        self.s = data["s"]
        self.sh = data["sh"]
        self.a = data["a"]


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
    groups: Optional[list[UserGroup]]
    follower_count: Optional[int]
    is_supporter: Optional[bool]
    support_level: Optional[int]
    level: Optional[float]
    profile_colour: Optional[str]
    cover_url: Optional[str]
    join_date: Optional[datetime]
    total_score: Optional[int]
    play_time: Optional[float]
    play_count: Optional[int]
    grades: Optional[UserGrades]
    medal_count: Optional[int]
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
            self.groups = None
            self.follower_count = None
            self.is_supporter = None
            self.support_level = None
            self.level = None
            self.profile_colour = None
            self.cover_url = None
            self.join_date = None
            self.total_score = None
            self.play_time = None
            self.play_count = None
            self.grades = None
            self.medal_count = None
        else:
            self.id = data["id"]
            self.username = data["username"]
            self.avatar_url = data["avatar_url"]
            self.country_code = data["country_code"]
            self.mode = GameMode.get_mode(data["playmode"])
            self.pp = data["statistics"]["pp"] if data["statistics"]["pp"] else 0.0
            self.accuracy = data["statistics"]["hit_accuracy"] if "statistics" in data and \
                                                                  "hit_accuracy" in data["statistics"] and \
                                                                  data["statistics"]["hit_accuracy"] else 0
            self.country_rank = data["statistics"]["country_rank"] if "statistics" in data and \
                                                                      "country_rank" in data["statistics"] and \
                                                                      data["statistics"]["country_rank"] else 0
            self.global_rank = data["statistics"]["global_rank"] if "statistics" in data and \
                                                                    "global_rank" in data["statistics"] and \
                                                                    data["statistics"]["global_rank"] else 0
            self.max_combo = data["statistics"]["maximum_combo"] if "statistics" in data and \
                                                                    "maximum_combo" in data["statistics"] and \
                                                                    data["statistics"]["maximum_combo"] else 0
            self.ranked_score = data["statistics"]["ranked_score"] if "statistics" in data and \
                                                                      "ranked_score" in data["statistics"] and \
                                                                      data["statistics"]["ranked_score"] else 0
            if "groups" in data:
                groups = []
                for group in data["groups"]:
                    groups.append(UserGroup(group))
                self.groups = groups
            else:
                self.groups = None
            self.follower_count = data["follower_count"]
            self.is_supporter = data["is_supporter"]
            self.support_level = data["support_level"]
            self.level = float(f'{data["statistics"]["level"]["current"]}.{data["statistics"]["level"]["progress"]}')
            self.profile_colour = data["profile_colour"]
            self.cover_url = data["cover"]["url"]
            self.join_date = parser.isoparse(data["join_date"]).replace(tzinfo=timezone.utc)
            self.total_score = data["statistics"]["total_score"] if "statistics" in data and \
                                                                    "total_score" in data["statistics"] and \
                                                                    data["statistics"]["total_score"] else 0
            self.play_time = data["statistics"]["play_time"] if "statistics" in data and \
                                                                "play_time" in data["statistics"] and \
                                                                data["statistics"]["play_time"] else 0
            self.play_count = data["statistics"]["play_count"] if "statistics" in data and \
                                                                  "play_count" in data["statistics"] and \
                                                                  data["statistics"]["play_count"] else 0
            self.grades = UserGrades(data["statistics"]["grade_counts"]) if "statistics" in data and \
                                                                            "grade_counts" in data["statistics"] and \
                                                                            data["statistics"]["grade_counts"] else None
            self.medal_count = len(data["user_achievements"])
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
