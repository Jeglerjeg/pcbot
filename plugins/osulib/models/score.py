from datetime import datetime
from typing import Optional

from plugins.osulib.enums import GameMode
from plugins.osulib.models.beatmap import Beatmap


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
    beatmapset: Optional[dict]
    rank_country: Optional[int]
    rank_global: Optional[int]
    weight: Optional[float]
    user: Optional[dict]

    def __init__(self, json_data: dict):
        self.total_score = json_data["total_score"]
        self.legacy_perfect = json_data["legacy_perfect"]
        self.mode = GameMode(json_data["ruleset_id"])
        self.statistics = ScoreStatistics(json_data["statistics"])
        self.id = json_data["id"]
        self.best_id = json_data["best_id"]
        self.user_id = json_data["user_id"]
        self.beatmap_id = json_data["beatmap_id"]
        self.accuracy = json_data["accuracy"]
        self.mods = json_data["mods"]
        self.max_combo = json_data["max_combo"]
        self.passed = json_data["passed"]
        self.pp = json_data["pp"] if json_data["pp"] is not None else 0.0
        self.rank = json_data["rank"]
        self.ended_at = datetime.fromisoformat(json_data["ended_at"])
        self.replay = json_data["replay"]
        if "new_pp" in json_data:
            self.new_pp = json_data["new_pp"]
        if "position" in json_data:
            self.position = json_data["position"]
        if "pp_difference" in json_data:
            self.pp_difference = json_data["pp_difference"]
        if "beatmap" in json_data:
            self.beatmap = Beatmap(json_data["beatmap"])
        if "beatmapset" in json_data:
            self.beatmapset = json_data["beatmapset"]
        if "rank_global" in json_data:
            self.rank_global = json_data["rank_global"]
        if "rank_country" in json_data:
            self.rank_country = json_data["rank_country"]
        if "weight" in json_data:
            self.weight = json_data["weight"]
        if "user" in json_data:
            self.user = json_data["user"]

    def __getitem__(self, item):
        return getattr(self, item)

    def __repr__(self):
        return self.to_dict()

    def to_dict(self):
        readable_dict = {}
        for attr, value in self.__dict__.items():
            if isinstance(value, GameMode):
                readable_dict["ruleset_id"] = value.value
                continue
            elif isinstance(value, Beatmap):
                readable_dict[attr] = value.to_dict()
                continue
            elif isinstance(value, datetime):
                readable_dict[attr] = value.isoformat()
                continue
            elif isinstance(value, ScoreStatistics):
                readable_dict[attr] = value.__dict__
                continue
            readable_dict[attr] = value
        return readable_dict

    def add_position(self, position: int):
        self.position = position
