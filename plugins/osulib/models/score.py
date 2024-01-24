from datetime import datetime, timezone
from typing import Optional

from dateutil import parser

from plugins.osulib.enums import GameMode
from plugins.osulib.models.beatmap import Beatmap, BeatmapsetCompact
from plugins.osulib.models.user import OsuUserCompact


class ScoreStatistics:
    perfect: int
    great: int
    good: int
    ok: int
    meh: int
    small_tick_hit: int
    small_tick_miss: int
    large_tick_hit: int
    large_tick_miss: int
    miss: int

    def __init__(self, raw_data: dict):
        self.perfect = raw_data["perfect"] if "perfect" in raw_data else 0
        self.great = raw_data["great"] if "great" in raw_data else 0
        self.good = raw_data["good"] if "good" in raw_data else 0
        self.ok = raw_data["ok"] if "ok" in raw_data else 0
        self.meh = raw_data["meh"] if "meh" in raw_data else 0
        self.small_tick_hit = raw_data["small_tick_hit"] if "small_tick_hit" in raw_data else 0
        self.small_tick_miss = raw_data["small_tick_miss"] if "small_tick_miss" in raw_data else 0
        self.large_tick_hit = raw_data["large_tick_hit"] if "large_tick_hit" in raw_data else 0
        self.large_tick_miss = raw_data["large_tick_miss"] if "large_tick_miss" in raw_data else 0
        self.miss = raw_data["miss"] if "miss" in raw_data else 0

    def __repr__(self):
        return str(self.__dict__)


class MaximumScoreStatistics:
    great: int
    large_tick_hit: int
    legacy_combo_increase: int
    ignore_hit: int

    def __init__(self, raw_data: dict):
        self.great = raw_data["great"] if "great" in raw_data else 0
        self.large_tick_hit = raw_data["large_tick_hit"] if "large_tick_hit" in raw_data else 0
        self.legacy_combo_increase = raw_data["legacy_combo_increase"] if "legacy_combo_increase" in raw_data else 0
        self.ignore_hit = raw_data["ignore_hit"] if "ignore_hit" in raw_data else 0

    def __repr__(self):
        return str(self.__dict__)


class OsuScore:
    id: int
    best_id: int
    user_id: int
    beatmap_id: int
    accuracy: float
    mods: list
    total_score: int
    max_combo: int
    legacy_perfect: bool
    statistics: ScoreStatistics
    maximum_statistics: Optional[MaximumScoreStatistics]
    passed: bool
    pp: float
    rank: str
    ended_at: datetime
    mode: GameMode
    replay: bool
    new_pp: Optional[float]
    position: Optional[int]
    pp_difference: Optional[float]
    beatmap: Optional[Beatmap]
    beatmapset: Optional[BeatmapsetCompact]
    rank_country: Optional[int]
    rank_global: Optional[int]
    weight: Optional[dict]
    user: Optional[OsuUserCompact]

    def __init__(self, data):
        self.total_score = data["total_score"]
        self.legacy_perfect = data["legacy_perfect"]
        self.mode = GameMode(data["ruleset_id"])
        self.statistics = ScoreStatistics(data["statistics"])
        self.id = data["id"]
        self.best_id = data["best_id"]
        self.user_id = data["user_id"]
        self.beatmap_id = data["beatmap_id"]
        self.accuracy = data["accuracy"]
        self.mods = data["mods"]
        self.max_combo = data["max_combo"]
        self.passed = data["passed"]
        self.pp = data["pp"] if data["pp"] is not None else 0.0
        self.rank = data["rank"]
        self.ended_at = parser.isoparse(data["ended_at"]).replace(tzinfo=timezone.utc)
        self.replay = data["replay"]
        if "new_pp" in data:
            self.new_pp = data["new_pp"]
        else:
            self.new_pp = None
        if "position" in data:
            self.position = data["position"]
        else:
            self.position = None
        if "pp_difference" in data:
            self.pp_difference = data["pp_difference"]
        else:
            self.pp_difference = None
        if "beatmap" in data:
            self.beatmap = Beatmap(data["beatmap"])
        else:
            self.beatmap = None
        if "beatmapset" in data and data["beatmapset"]:
            self.beatmapset = BeatmapsetCompact(data["beatmapset"])
        else:
            self.beatmapset = None
        if "maximum_statistics" in data:
            self.maximum_statistics = MaximumScoreStatistics(data["maximum_statistics"])
        else:
            self.maximum_statistics = None
        if "rank_global" in data:
            self.rank_global = data["rank_global"]
        else:
            self.rank_global = None
        if "rank_country" in data:
            self.rank_country = data["rank_country"]
        else:
            self.rank_country = None
        if "weight" in data:
            self.weight = data["weight"]
        else:
            self.weight = None
        if "user" in data:
            self.user = OsuUserCompact(data["user"], from_db=False)
        else:
            self.user = None

    def __getitem__(self, item):
        return getattr(self, item)

    def __repr__(self):
        return str(self.to_dict())

    def to_dict(self):
        readable_dict = {}
        for attr, value in self.__dict__.items():
            if isinstance(value, GameMode):
                readable_dict["ruleset_id"] = value.value
                continue
            if isinstance(value, Beatmap):
                readable_dict[attr] = value.to_dict()
                continue
            if isinstance(value, datetime):
                readable_dict[attr] = value.isoformat()
                continue
            if isinstance(value, ScoreStatistics):
                readable_dict[attr] = value.__dict__
                continue
            readable_dict[attr] = value
        return readable_dict

    def add_position(self, position: int):
        self.position = position
