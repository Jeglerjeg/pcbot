from datetime import datetime, timezone
from typing import Optional

from dateutil import parser

class Difficulty:
    leaderboard_id: int
    difficulty: int
    gamemode: str
    difficulty_raw: str

    def __init__(self, raw_data: dict):
        self.leaderboard_id = raw_data["leaderboardId"]
        self.difficulty = raw_data["difficulty"]
        self.gamemode = raw_data["gameMode"]
        self.difficulty_raw = raw_data["difficultyRaw"]

    def __repr__(self):
        return str(self.to_dict())

    def to_dict(self):
        readable_dict = {}
        for attr, value in self.__dict__.items():
            readable_dict[attr] = value
        return readable_dict

class ScoreSaberLeaderboardInfo:
    id: int
    difficulty: Difficulty
    song_hash: str
    song_name: str
    song_sub_name: str
    song_author_name: str
    level_author_name: str
    max_score: int
    created_date: datetime
    ranked_date: Optional[datetime]
    qualified_date: Optional[datetime]
    loved_date: Optional[datetime]
    ranked: bool
    qualified: bool
    loved: bool
    max_pp: float
    stars: float
    positive_modifiers: bool
    plays: int
    daily_plays: int
    cover_image: str
    def __init__(self, raw_data: dict):
        self.id = raw_data["id"]
        self.difficulty = Difficulty(raw_data["difficulty"])
        self.song_hash = raw_data["songHash"]
        self.song_name = raw_data["songName"]
        self.song_sub_name = raw_data["songSubName"]
        self.song_author_name = raw_data["songAuthorName"]
        self.level_author_name = raw_data["levelAuthorName"]
        self.max_score = raw_data["maxScore"]
        self.created_date = parser.isoparse(raw_data["createdDate"]).replace(tzinfo=timezone.utc)
        if raw_data["rankedDate"]:
            self.ranked_date = parser.isoparse(raw_data["rankedDate"]).replace(tzinfo=timezone.utc)
        else:
            self.ranked_date = None
        if raw_data["qualifiedDate"]:
            self.qualified_date = parser.isoparse(raw_data["qualifiedDate"]).replace(tzinfo=timezone.utc)
        else:
            self.qualified_date = None
        if raw_data["lovedDate"]:
            self.loved_date = parser.isoparse(raw_data["lovedDate"]).replace(tzinfo=timezone.utc)
        else:
            self.loved_date = None
        self.ranked = raw_data["ranked"]
        self.qualified = raw_data["qualified"]
        self.loved = raw_data["loved"]
        self.max_pp = raw_data["maxPP"]
        self.stars = raw_data["stars"]
        self.positive_modifiers = raw_data["positiveModifiers"]
        self.plays = raw_data["plays"]
        self.daily_plays = raw_data["dailyPlays"]
        self.cover_image = raw_data["coverImage"]

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