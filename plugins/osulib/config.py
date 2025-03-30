from pcbot import Config

# Configuration data for this plugin, including settings for members and the API key
osu_config = Config("osu", pretty=True, data={
    "client_id": "change to your client ID",
    "client_secret": "change to your client secret",
    "pp_threshold": 0.13,  # The amount of pp gain required to post a score
    "score_request_limit": 100,  # The maximum number of scores to request, between 0-100
    "minimum_pp_required": 0,  # The minimum pp required to assign a gamemode/profile in general
    "use_mentions_in_scores": True,  # Whether the bot will mention people when they set a *score*
    "update_interval": 30,  # The sleep time in seconds between updates
    "not_playing_skip": 10,  # Number of rounds between every time someone not playing is updated
    "map_event_repeat_interval": 6,  # The time in hours before a map event will be treated as "new"
    "guild": {},  # Guild specific info for score- and map notification channels
    "map_cache": {},  # Cache for map events, primarily used for calculating and caching pp of the difficulties
    "score_update_delay": 5,  # Seconds to wait to retry get_new_score if new score is not found
    "ratelimit": 60,  # Amount of API requests allowed per minute
    "leaderboard": {},  # A list of users that have manually turned on/off leaderboard notifications
    "beatmap_updates": {},  # A list of users that have manually turned on/off beatmap update notifications
    "opt_in_leaderboard": True,  # Whether or not leaderboard notifications should be opt-in
    "opt_in_beatmaps": False,  # Whether or not beatmap update notifications should be opt-in
    "notify_empty_scores": False,  # Whether or not to notify pp gain when a score isn't found (only if pp mode is off)
    "scores_ws_url": "Change to the scores-ws URL"
})
