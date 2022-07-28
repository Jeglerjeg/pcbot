from datetime import datetime
from typing import Optional

from plugins.osulib.enums import GameMode


class Beatmap:
    accuracy: float
    ar: float
    beatmapset_id: int
    beatmapset: Optional[dict]
    checksum: Optional[str]
    failtimes = Optional[dict]
    max_combo = Optional[int]
    bpm: Optional[float]
    convert: bool
    count_circles: int
    count_sliders: int
    count_spinners: int
    cs: int
    deleted_at: Optional[datetime]
    difficulty_rating: float
    drain: float
    hit_length: int
    id: int
    is_scoreable: bool
    last_updated: datetime
    mode: GameMode
    mode_int: int
    passcount: int
    playcount: int
    ranked: int
    status: str
    total_length: int
    url: str
    user_id: int
    version: str

    def __init__(self, json_data: dict):
        self.accuracy = json_data["accuracy"]
        self.ar = json_data["ar"]
        self.beatmapset_id = json_data["beatmapset_id"]
        if "beatmapset" in json_data:
            self.beatmapset = json_data["beatmapset"]
        if "checksum" in json_data:
            self.checksum = json_data["checksum"]
        if "failtimes" in json_data:
            self.failtimes = json_data["failtimes"]
        if "max_combo" in json_data:
            self.max_combo = json_data["max_combo"]
        if "bpm" in json_data and json_data["bpm"]:
            self.bpm = json_data["bpm"]
        self.convert = json_data["convert"]
        self.count_circles = json_data["count_circles"]
        self.count_sliders = json_data["count_sliders"]
        self.count_spinners = json_data["count_spinners"]
        self.cs = json_data["cs"]
        if "deleted_at" in json_data and json_data["deleted_at"]:
            self.deleted_at = datetime.fromisoformat(json_data["deleted_at"])
        self.difficulty_rating = json_data["difficulty_rating"]
        self.drain = json_data["drain"]
        self.hit_length = json_data["hit_length"]
        self.id = json_data["id"]
        self.is_scoreable = json_data["is_scoreable"]
        self.last_updated = datetime.fromisoformat(json_data["last_updated"])
        self.mode = GameMode.get_mode(json_data["mode"])
        self.mode_int = json_data["mode_int"]
        self.passcount = json_data["passcount"]
        self.playcount = json_data["playcount"]
        self.ranked = json_data["ranked"]
        self.status = json_data["status"]
        self.total_length = json_data["total_length"]
        self.url = json_data["url"]
        self.user_id = json_data["user_id"]
        self.version = json_data["version"]

    def __getitem__(self, item):
        return getattr(self, item)

    def __repr__(self):
        return self.to_dict()

    def to_dict(self):
        readable_dict = {}
        for attr, value in self.__dict__.items():
            if isinstance(value, GameMode):
                readable_dict[attr] = value.name
                continue
            elif isinstance(value, datetime):
                readable_dict[attr] = value.isoformat()
                continue
            readable_dict[attr] = value
        return readable_dict

    def add_max_combo(self, max_combo: int):
        self.max_combo = max_combo
