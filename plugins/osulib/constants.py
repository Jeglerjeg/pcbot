import re

from plugins.osulib import config

host = "https://osu.ppy.sh/"
max_diff_length = 22  # The maximum amount of characters in a beatmap difficulty
logging_interval = 30  # The time it takes before posting logging information to the console.
update_interval = config.osu_config.data.get("update_interval", 30)
not_playing_skip = config.osu_config.data.get("not_playing_skip", 10)
pp_threshold = config.osu_config.data.get("pp_threshold", 0.13)
score_request_limit = config.osu_config.data.get("score_request_limit", 100)
minimum_pp_required = config.osu_config.data.get("minimum_pp_required", 0)
use_mentions_in_scores = config.osu_config.data.get("use_mentions_in_scores", True)
notify_empty_scores = config.osu_config.data.get("notify_empty_scores", False)
cache_user_profiles = config.osu_config.data.get("cache_user_profiles", True)
event_repeat_interval = config.osu_config.data.get("map_event_repeat_interval", 6)
ratelimit = config.osu_config.data.get("ratelimit", 60)
timestamp_pattern = re.compile(r"(\d+:\d+:\d+\s(\([\d,]+\))?\s*)-")
rank_regex = re.compile(r"#\d+")
mode_names = {
    "osu": ["standard", "osu", "std", "osu!"],
    "taiko": ["taiko", "osu!taiko"],
    "fruits": ["catch", "ctb", "fruits", "osu!catch"],
    "mania": ["mania", "keys", "osu!mania"]
}
