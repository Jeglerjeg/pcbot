from pcbot import Config

# Configuration data for this plugin, including settings for members and the API key
scoresaber_config = Config("scoresaber", pretty=True, data={
    "pp_threshold": 0.13,  # The amount of pp gain required to post a score
    "score_request_limit": 100,  # The maximum number of scores to request, between 0-100
    "minimum_pp_required": 0,  # The minimum pp required to assign a gamemode/profile in general
    "update_interval": 30,  # The sleep time in seconds between updates
    "guild": {},  # Guild specific info for score- and map notification channels
    "not_playing_skip": 10,  # Number of rounds between every time someone not playing is updated
    "score_update_delay": 5,  # Seconds to wait to retry get_new_score if new score is not found
    "notify_empty_scores": False,  # Whether or not to notify pp gain when a score isn't found (only if pp mode is off)
})