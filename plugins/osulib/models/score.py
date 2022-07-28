from datetime import datetime
from typing import Optional


class OsuScore:
    id: int
    best_id: int
    user_id: int
    beatmap_id: int
    accuracy: float
    mods: list
    score: int
    max_combo: int
    perfect: bool
    count_perfect: int
    count_300: int
    count_200: int
    count_100: int
    count_50: int
    count_smalltickhit: int
    count_smalltickmiss: int
    count_largetickhit: int
    count_largetickmiss: int
    count_miss: int
    passed: bool
    pp: float
    rank: str
    ended_at: datetime
    mode: int
    replay: bool
    new_pp: Optional[float]
    position: Optional[int]
    pp_difference: Optional[float]
    beatmap: Optional[dict]
    beatmapset: Optional[dict]
    rank_country: Optional[int]
    rank_global: Optional[int]
    weight: Optional[float]
    user: Optional[dict]

    def __init__(self, json_data: dict, from_file: bool = False):
        if from_file:
            self.score = json_data["score"]
            self.perfect = json_data["perfect"]
            self.mode = json_data["mode"]
            self.count_max = json_data["count_max"]
            self.count_300 = json_data["count_300"]
            self.count_200 = json_data["count_200"]
            self.count_100 = json_data["count_100"]
            self.count_50 = json_data["count_50"]
            self.count_smalltickhit = json_data["count_smalltickhit"]
            self.count_smalltickmiss = json_data["count_smalltickmiss"]
            self.count_largetickhit = json_data["count_largetickhit"]
            self.count_largetickmiss = json_data["count_largetickmiss"]
            self.count_miss = json_data["count_miss"]
        else:
            self.score = json_data["total_score"]
            self.perfect = json_data["legacy_perfect"]
            self.mode = json_data["ruleset_id"]
            self.count_max = json_data["statistics"]["perfect"] if "perfect" in json_data["statistics"] else 0
            self.count_300 = json_data["statistics"]["great"] if "great" in json_data["statistics"] else 0
            self.count_200 = json_data["statistics"]["good"] if "good" in json_data["statistics"] else 0
            self.count_100 = json_data["statistics"]["ok"] if "ok" in json_data["statistics"] else 0
            self.count_50 = json_data["statistics"]["meh"] if "meh" in json_data["statistics"] else 0
            self.count_smalltickhit = json_data["statistics"]["small_tick_hit"] if "small_tick_hit" in \
                                                                                   json_data["statistics"] else 0
            self.count_smalltickmiss = json_data["statistics"]["small_tick_miss"] if "small_tick_miss" in \
                                                                                     json_data["statistics"] else 0
            self.count_largetickhit = json_data["statistics"]["large_tick_hit"] if "large_tick_hit" in \
                                                                                   json_data["statistics"] else 0
            self.count_largetickmiss = json_data["statistics"]["large_tick_miss"] if "large_tick_miss" in \
                                                                                     json_data["statistics"] else 0
            self.count_miss = json_data["statistics"]["miss"] if "miss" in json_data["statistics"] else 0
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
            self.beatmap = json_data["beatmap"]
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

    def to_dict(self):
        readable_dict = {}
        for attr, value in self.__dict__.items():
            if isinstance(value, datetime):
                readable_dict[attr] = value.isoformat()
                continue
            readable_dict[attr] = value
        return readable_dict

    def add_position(self, position: int):
        self.position = position
