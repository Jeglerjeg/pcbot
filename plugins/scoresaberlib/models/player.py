from datetime import datetime, timezone
from random import randint
from typing import Optional

from plugins.scoresaberlib import config

not_playing_skip = config.scoresaber_config.data.get("update_interval", 5)


class ScoreSaberLeaderboardPlayer:
    id: int
    name: str
    profile_picture: str
    country: str
    permissions: Optional[int]
    role: Optional[str]

    def __init__(self, raw_data, from_db: bool = True):
        if from_db:
            self.id = raw_data.id
            self.name = raw_data.name
            self.profile_picture = raw_data.profile_picture
            self.country = raw_data.country
            self.permissions = None
            self.role = None
        else:
            self.id = raw_data["id"]
            self.name = raw_data["name"]
            self.profile_picture = raw_data["profilePicture"]
            self.country = raw_data["country"]
            self.permissions = raw_data["permissions"]
            self.role = raw_data["role"]

    def __repr__(self):
        return str(self.to_dict())

    def to_dict(self):
        readable_dict = {}
        for attr, value in self.__dict__.items():
            readable_dict[attr] = value
        return readable_dict


class ScoreSaberPlayerScoreStats:
    total_score: int
    total_ranked_score: int
    average_ranked_accuracy: int
    total_playcount = int
    ranked_playcount = int
    replays_watched = int

    def __init__(self, raw_data):
        self.total_score = raw_data["totalScore"]
        self.total_ranked_score = raw_data["totalRankedScore"]
        self.average_ranked_accuracy = raw_data["averageRankedAccuracy"]
        self.total_playcount = raw_data["totalPlayCount"]
        self.ranked_playcount = raw_data["rankedPlayCount"]
        self.replays_watched = raw_data["replaysWatched"]

    def __repr__(self):
        return str(self.to_dict())

    def to_dict(self):
        readable_dict = {}
        for attr, value in self.__dict__.items():
            readable_dict[attr] = value
        return readable_dict


class ScoreSaberPlayer(ScoreSaberLeaderboardPlayer):
    pp: int
    rank: int
    country_rank: int
    score_stats: Optional[ScoreSaberPlayerScoreStats]
    banned: Optional[bool]
    inactive: Optional[bool]
    ticks: Optional[int]
    time_cached: Optional[datetime]
    last_pp_notification: Optional[datetime]

    def __init__(self, raw_data, from_db: bool = True):
        super().__init__(raw_data, from_db)
        if from_db:
            self.pp = raw_data.pp
            self.rank = raw_data.rank
            self.country_rank = raw_data.country_rank
            score_stats = {"totalScore": 0, "totalRankedScore": raw_data.total_ranked_score,
                           "averageRankedAccuracy": raw_data.average_ranked_accuracy, "totalPlayCount": 0,
                           "rankedPlayCount": 0, "replaysWatched": 0}
            self.score_stats = ScoreSaberPlayerScoreStats(score_stats)
            self.banned = None
            self.inactive = None
            self.ticks = raw_data.ticks
            self.time_cached = datetime.fromtimestamp(raw_data.time_cached, tz=timezone.utc)
            self.last_pp_notification = datetime.fromtimestamp(raw_data.last_pp_notification, tz=timezone.utc)
        else:
            self.pp = raw_data["pp"]
            self.rank = raw_data["rank"]
            self.country_rank = raw_data["countryRank"]
            if raw_data["scoreStats"]:
                self.score_stats = ScoreSaberPlayerScoreStats(raw_data["scoreStats"])
            else:
                self.score_stats = None
            self.banned = raw_data["banned"]
            self.inactive = raw_data["inactive"]
            self.ticks = None
            self.time_cached = None
            self.last_pp_notification = None

    def __repr__(self):
        return str(self.to_dict())

    def to_dict(self):
        readable_dict = {}
        for attr, value in self.__dict__.items():
            readable_dict[attr] = value
        return readable_dict

    def to_db_query(self, discord_id: int, new_user: bool = False, ticks: int = None):
        if new_user:
            ticks = randint(0, not_playing_skip - 1)
            self.last_pp_notification = datetime.now(tz=timezone.utc)

        return {"discord_id": discord_id, "id": self.id, "name": self.name, "profile_picture": self.profile_picture,
                "country": self.country, "pp": self.pp,
                "average_ranked_accuracy": self.score_stats.average_ranked_accuracy if self.score_stats else 0.0,
                "country_rank": self.country_rank, "rank": self.rank,
                "total_ranked_score": self.score_stats.total_ranked_score if self.score_stats else 0,
                "ticks": ticks, "time_cached": int(self.time_cached.timestamp()),
                "last_pp_notification": int(self.last_pp_notification.timestamp())}

    def add_tick(self):
        self.ticks += 1

    def set_time_cached(self, time: datetime):
        self.time_cached = time

    def set_last_pp_notification(self, time: datetime):
        self.last_pp_notification = time