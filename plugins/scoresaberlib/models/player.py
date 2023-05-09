from typing import Optional


class ScoreSaberLeaderboardPlayer:
    id: int
    name: str
    profile_picture: str
    country: str
    permissions: int
    role: str
    def __init__(self, raw_data: dict):
        self.id = raw_data["id"]
        self.name = raw_data["name"]
        self.profile_picture = raw_data["profilePicture"]
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

    def __init__(self, raw_data: dict):
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
    banned: bool
    inactive: bool

    def __init__(self, raw_data: dict):
        super().__init__(raw_data)
        self.pp = raw_data["pp"]
        self.rank = raw_data["rank"]
        self.country_rank = raw_data["countryRank"]
        if raw_data["scoreStats"]:
            self.score_stats = ScoreSaberPlayerScoreStats(raw_data["scoreStats"])
        else:
            self.score_stats = None
        self.banned = raw_data["banned"]
        self.inactive = raw_data["inactive"]

    def __repr__(self):
        return str(self.to_dict())

    def to_dict(self):
        readable_dict = {}
        for attr, value in self.__dict__.items():
            readable_dict[attr] = value
        return readable_dict