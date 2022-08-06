from datetime import datetime
from typing import Optional

from plugins.osulib.enums import GameMode


class BeatmapsetCovers:
    cover: str
    cover2x: str
    card: str
    card2x: str
    list: str
    list2x: str
    slimcover: str
    slimcover2x: str

    def __init__(self, raw_data: dict):
        self.cover = raw_data["cover"]
        self.cover2x = raw_data["cover@2x"]
        self.card = raw_data["card"]
        self.card2x = raw_data["card@2x"]
        self.list = raw_data["list"]
        self.list2x = raw_data["list@2x"]
        self.slimcover = raw_data["slimcover"]
        self.slimcover2x = raw_data["slimcover@2x"]

    def __repr__(self):
        return self.__dict__


class Beatmap:
    accuracy: float
    ar: float
    beatmapset_id: int
    beatmapset: Optional
    checksum: Optional[str]
    failtimes = Optional[dict]
    new_bpm: Optional[int]
    max_pp: Optional[float]
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
        if "beatmapset" in json_data and json_data["beatmapset"]:
            self.beatmapset = Beatmapset(json_data["beatmapset"])
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

    def add_max_pp(self, max_pp: float):
        self.max_pp = max_pp

    def add_new_bpm(self, bpm):
        self.new_bpm = bpm


class BeatmapsetCompact:
    artist: str
    artist_unicode: str
    covers: BeatmapsetCovers
    creator: str
    favourite_count: int
    id: int
    play_count: int
    source: str
    status: str
    title: str
    title_unicode: str
    user_id: int

    def __init__(self, raw_data: dict):
        self.artist = raw_data["artist"]
        self.artist_unicode = raw_data["artist_unicode"]
        self.covers = BeatmapsetCovers(raw_data["covers"])
        self.creator = raw_data["creator"]
        self.favourite_count = raw_data["favourite_count"]
        self.id = raw_data["id"]
        self.play_count = raw_data["play_count"]
        self.source = raw_data["source"]
        self.status = raw_data["status"]
        self.title = raw_data["title"]
        self.title_unicode = raw_data["title_unicode"]
        self.user_id = raw_data["user_id"]

    def __repr__(self):
        return self.to_dict()

    def to_dict(self):
        readable_dict = {}
        for attr, value in self.__dict__.items():
            if isinstance(value, GameMode):
                readable_dict[attr] = value.name
                continue
            readable_dict[attr] = value
        return readable_dict


class Beatmapset(BeatmapsetCompact):
    bpm: float
    ranked: int
    beatmaps: Optional[list[Beatmap]]
    converts: Optional[list[Beatmap]]

    def __init__(self, raw_data: dict):
        super().__init__(raw_data)
        self.bpm = raw_data["bpm"]
        self.ranked = raw_data["ranked"]
        if "beatmaps" in raw_data:
            self.beatmaps = [Beatmap(beatmap) for beatmap in raw_data["beatmaps"]]
        if "converts" in raw_data:
            self.converts = [Beatmap(beatmap) for beatmap in raw_data["converts"]]
