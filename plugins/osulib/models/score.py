import pickle
from datetime import datetime, timezone
from typing import Optional

from plugins.osulib.enums import GameMode
from plugins.osulib.models.beatmap import Beatmap, BeatmapsetCompact


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
    user: Optional[dict]

    def __init__(self, data, db: bool = False):
        if db:
            self.from_db(data)
        else:
            self.from_api(data)

    def from_db(self, data):
        self.id = data.id
        self.best_id = data.best_id
        self.user_id = data.user_id
        self.beatmap_id = data.beatmap_id
        self.accuracy = data.accuracy
        self.mods = pickle.loads(data.mods)
        self.total_score = data.total_score
        self.max_combo = data.max_combo
        self.legacy_perfect = data.legacy_perfect
        self.statistics = ScoreStatistics(pickle.loads(data.statistics))
        self.passed = data.passed
        self.pp = data.pp
        self.rank = data.rank
        self.ended_at = data.ended_at.replace(tzinfo=timezone.utc)
        self.mode = GameMode(data.mode)
        self.replay = data.replay
        self.position = data.position
        self.weight = pickle.loads(data.weight)

    def from_api(self, data: dict):
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
        self.ended_at = datetime.fromisoformat(data["ended_at"][:-1]).replace(tzinfo=timezone.utc)
        self.replay = data["replay"]
        if "new_pp" in data:
            self.new_pp = data["new_pp"]
        if "position" in data:
            self.position = data["position"]
        if "pp_difference" in data:
            self.pp_difference = data["pp_difference"]
        if "beatmap" in data:
            self.beatmap = Beatmap(data["beatmap"])
        if "beatmapset" in data and data["beatmapset"]:
            self.beatmapset = BeatmapsetCompact(data["beatmapset"])
        if "rank_global" in data:
            self.rank_global = data["rank_global"]
        if "rank_country" in data:
            self.rank_country = data["rank_country"]
        if "weight" in data:
            self.weight = data["weight"]
        if "user" in data:
            self.user = data["user"]

    def __getitem__(self, item):
        return getattr(self, item)

    def __repr__(self):
        return str(self.to_dict())

    def to_db_query(self):
        return {"id": self.id, "best_id": self.best_id, "user_id": self.user_id, "beatmap_id": self.beatmap_id,
                "accuracy": self.accuracy, "mods": pickle.dumps(self.mods), "total_score": self.total_score,
                "max_combo": self.max_combo, "legacy_perfect": self.legacy_perfect,
                "statistics": pickle.dumps(self.statistics.__dict__), "passed": self.passed, "pp": self.pp,
                "rank": self.rank, "ended_at": self.ended_at, "mode": self.mode.value, "replay": self.replay,
                "position": self.position, "weight": pickle.dumps(self.weight)}

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
