import logging

from pcbot import utils
from plugins.scoresaberlib.models.leaderboard_info import ScoreSaberLeaderboardInfo
from plugins.scoresaberlib.models.player import ScoreSaberPlayer
from plugins.scoresaberlib.models.score import ScoreSaberScore

try:
    import pyrate_limiter
except ImportError:
    pyrate_limiter = None
    logging.info("pyrate_limiter is not installed, scoresaber api functionality is unavailable.")

if pyrate_limiter:
    hourly_rate = pyrate_limiter.RequestRate(400, pyrate_limiter.Duration.MINUTE)  # Amount of requests per minute
    limiter = pyrate_limiter.Limiter(hourly_rate)
else:
    limiter = None

requests_sent = 0

def def_section(api_name: str, first_element: bool = False, api_url: str = "https://scoresaber.com/api/"):
    """ Add a section using a template to simplify adding API functions. """
    async def template(url=api_url, request_tries: int = 1, **params):
        if not limiter:
            return None
        async with limiter.ratelimit("scoresaber", delay=True):
            # Download using a URL of the given API function name
            for _ in range(request_tries):
                try:
                    response = await utils.download_json(url + api_name, **params)

                except ValueError as e:
                    logging.warning("ValueError Calling %s: %s", url + api_name, e)
                else:
                    global requests_sent
                    requests_sent += 1

                    if response is not None:
                        break
            else:
                return None

            # Unless we want to extract the first element, return the entire object (usually a list)
            if not first_element:
                return response

            # If the returned value should be the first element, see if we can cut it
            return response[0] if len(response) > 0 else None

    # Set the correct name of the function and add simple docstring
    template.__name__ = api_name
    template.__doc__ = "Get " + ("list" if not first_element else "dict") + " using " + api_url + api_name
    return template


async def get_user_map_score(map_id: int, username: str):
    """ Returns a user's score on a map. """
    request = def_section(f"leaderboard/by-id/{map_id}/scores")
    params = {
        "search": username,
    }

    result = await request(**params)
    if not result or "errorMessage" in str(result) or "scores" not in result:
        result = None
    else:
        result = ScoreSaberScore(result["scores"][0])
    return result

async def get_leaderboard_info(map_id: int):
    """ Returns a map. """
    request = def_section(f"leaderboard/by-id/{map_id}/info")

    result = await request()
    if not result or "errorMessage" in str(result):
        result = None
    else:
        result = ScoreSaberLeaderboardInfo(result)
    return result

async def get_user_scores(user_id: int, sort: str, limit: int):
    """ Returns a user's best or recent. """
    request = def_section(f"player/{user_id}/scores")
    params = {
        "sort": sort,
        "limit": limit
    }

    result = await request(**params)
    if not result or "errorMessage" in str(result) or "playerScores" not in result:
        result = None
    else:
        result = [(ScoreSaberScore(scoresaber_score["score"]), ScoreSaberLeaderboardInfo(scoresaber_score["leaderboard"])) for scoresaber_score in result["playerScores"]]
    return result

async def get_user(user: str):
    """ Returns a user. """
    request = def_section(f"players")
    params = {
        "search": user,
    }

    result = await request(**params)
    if not result or "errorMessage" in str(result) or "players" not in result:
        result = None
    else:
        result = ScoreSaberPlayer(result["players"][0])
    return result

async def get_user_by_id(user_id: int):
    """ Returns a user. """
    request = def_section(f"player/{user_id}/basic")

    result = await request()
    if not result or "errorMessage" in str(result):
        result = None
    else:
        result = ScoreSaberPlayer(result)
    return result