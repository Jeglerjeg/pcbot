import pickle
from datetime import datetime, timezone
from typing import Optional

from dateutil import parser

from plugins.osulib import db
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
        return str(self.__dict__)


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
    time_cached: datetime

    def __init__(self, data, from_db: bool = False, beatmapset: bool = True):
        if from_db:
            self.from_db(data, beatmapset)
        else:
            self.from_file(data)

    def from_db(self, data, beatmapset: bool):
        self.accuracy = data.accuracy
        self.ar = data.ar
        self.beatmapset_id = data.beatmapset_id
        if beatmapset:
            self.beatmapset = Beatmapset(db.get_beatmapset(self.beatmapset_id), from_db=True,
                                         beatmaps=False)
        self.checksum = data.checksum
        self.max_combo = data.max_combo
        self.bpm = data.bpm
        self.convert = data.convert
        self.count_circles = data.count_circles
        self.count_sliders = data.count_sliders
        self.count_spinners = data.count_spinners
        self.cs = data.cs
        self.difficulty_rating = data.difficulty_rating
        self.drain = data.drain
        self.hit_length = data.hit_length
        self.id = data.id
        self.mode = GameMode(data.mode)
        self.mode_int = data.mode
        self.passcount = data.passcount
        self.playcount = data.playcount
        self.ranked = data.ranked
        self.status = data.status
        self.total_length = data.total_length
        self.user_id = data.user_id
        self.version = data.version
        self.time_cached = data.time_cached.replace(tzinfo=timezone.utc)

    def from_file(self, data: dict):
        self.accuracy = data["accuracy"]
        self.ar = data["ar"]
        self.beatmapset_id = data["beatmapset_id"]
        if "beatmapset" in data and data["beatmapset"]:
            self.beatmapset = Beatmapset(data["beatmapset"])
        if "checksum" in data:
            self.checksum = data["checksum"]
        if "failtimes" in data:
            self.failtimes = data["failtimes"]
        if "max_combo" in data:
            self.max_combo = data["max_combo"]
        if "bpm" in data and data["bpm"]:
            self.bpm = data["bpm"]
        self.convert = data["convert"]
        self.count_circles = data["count_circles"]
        self.count_sliders = data["count_sliders"]
        self.count_spinners = data["count_spinners"]
        self.cs = data["cs"]
        if "deleted_at" in data and data["deleted_at"]:
            self.deleted_at = parser.isoparse(data["deleted_at"]).replace(tzinfo=timezone.utc)
        self.difficulty_rating = data["difficulty_rating"]
        self.drain = data["drain"]
        self.hit_length = data["hit_length"]
        self.id = data["id"]
        self.is_scoreable = data["is_scoreable"]
        self.last_updated = parser.isoparse(data["last_updated"]).replace(tzinfo=timezone.utc)
        self.mode = GameMode.get_mode(data["mode"])
        self.mode_int = data["mode_int"]
        self.passcount = data["passcount"]
        self.playcount = data["playcount"]
        self.ranked = data["ranked"]
        self.status = data["status"]
        self.total_length = data["total_length"]
        self.url = data["url"]
        self.user_id = data["user_id"]
        self.version = data["version"]

    def __repr__(self):
        return str(self.to_dict())

    def to_db_query(self):
        return {"accuracy": self.accuracy, "ar": self.ar, "beatmapset_id": self.beatmapset_id,
                "checksum": self.checksum, "max_combo": self.max_combo, "bpm": self.bpm, "convert": self.convert,
                "count_circles": self.count_circles, "count_sliders": self.count_sliders,
                "count_spinners": self.count_spinners, "cs": self.cs, "difficulty_rating": self.difficulty_rating,
                "drain": self.drain, "hit_length": self.hit_length, "id": self.id, "mode": self.mode_int,
                "passcount": self.passcount, "playcount": self.playcount, "ranked": self.ranked, "status": self.status,
                "total_length": self.total_length, "user_id": self.user_id, "version": self.version,
                "time_cached": datetime.now(timezone.utc)}

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
    nsfw: bool
    play_count: int
    source: str
    status: str
    title: str
    title_unicode: str
    user_id: int
    beatmaps: Optional[list[Beatmap]]
    converts: Optional[list[Beatmap]]

    def __init__(self, raw_data, from_db: bool = False):
        if from_db:
            pass
        else:
            self.artist = raw_data["artist"]
            self.artist_unicode = raw_data["artist_unicode"]
            if raw_data["covers"]:
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
            if "beatmaps" in raw_data:
                self.beatmaps = [Beatmap(beatmap) for beatmap in raw_data["beatmaps"]]
            if "converts" in raw_data:
                self.converts = [Beatmap(beatmap) for beatmap in raw_data["converts"]]

    def __repr__(self):
        return str(self.to_dict())

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
    time_cached: datetime

    def __init__(self, raw_data, from_db: bool = False, beatmaps: bool = True):
        super().__init__(raw_data, from_db)
        if from_db:
            self.from_db(raw_data, beatmaps)
        else:
            self.from_file(raw_data)

    def from_db(self, raw_data, beatmaps: bool):
        self.artist = raw_data.artist
        self.artist_unicode = raw_data.artist_unicode
        covers = pickle.loads(raw_data.covers)
        if covers:
            self.covers = covers
        self.creator = raw_data.creator
        self.favourite_count = raw_data.favourite_count
        self.id = raw_data.id
        self.play_count = raw_data.play_count
        self.source = raw_data.source
        self.status = raw_data.status
        self.title = raw_data.title
        self.title_unicode = raw_data.title_unicode
        self.user_id = raw_data.user_id
        if beatmaps:
            fetched_beatmaps = db.get_beatmaps_by_beatmapset_id(self.id)
            self.beatmaps = [(Beatmap(beatmap,
                                         from_db=True, beatmapset=False)) for beatmap in fetched_beatmaps]
        self.bpm = raw_data.bpm
        self.ranked = raw_data.ranked
        self.time_cached = raw_data.time_cached.replace(tzinfo=timezone.utc)

    def from_file(self, raw_data: dict):
        self.bpm = raw_data["bpm"]
        self.ranked = raw_data["ranked"]

    def to_db_query(self):
        return {"artist": self.artist, "artist_unicode": self.artist_unicode,
                "covers": pickle.dumps(self.covers),
                "creator": self.creator, "favourite_count": self.favourite_count, "id": self.id,
                "play_count": self.play_count, "source": self.source, "status": self.status, "title": self.title,
                "title_unicode": self.title_unicode, "user_id": self.user_id,
                "beatmaps": pickle.dumps([beatmap.id for beatmap in self.beatmaps]), "bpm": self.bpm,
                "ranked": self.ranked, "time_cached": datetime.now(timezone.utc)}
