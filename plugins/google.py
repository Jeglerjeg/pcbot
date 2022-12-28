import random

import discord

import plugins
from pcbot import Annotate, utils, Config

client = plugins.client

# api_keys is a list of objects with keys "key" and "cx" 
#
# e.g 
# "api_keys": [
#   {"key": "abc", "cx": "123"},
#   {"key": "def", "cx": "456"}
# ]
config = Config("google", data=dict(api_keys=[]), pretty=True)
result_cache = {}
blacklisted_url_keywords = [
    "lookaside.fbsbx.com",  # occurs frequently and images don't embed
    ":///",  # most commonly x-raw-image:///, but this should catch other non-hosted urls
]


async def on_reload(name):
    global result_cache
    local_cache = result_cache

    await plugins.reload(name)

    result_cache = local_cache


def get_auth():
    assert "api_keys" in config.data and len(
        config.data["api_keys"]) > 0, "This command is not configured. An API key must be added to `google.json`"
    key_pair = random.choice(config.data["api_keys"])
    return key_pair["key"], key_pair["cx"]


@plugins.command()
async def img(message: discord.Message, query: Annotate.CleanContent):
    """ Retrieve an image from google. Safe search is enabled outside 
    age-restricted channels. 
    """
    safe = not getattr(message.channel, "nsfw", False)

    # Only use cache for safe results in safe channels
    # Any unsafe queries will be re-cached if they return results
    # NSFW channels may use any cached results
    use_cache = query in result_cache and (not safe or result_cache[query]["safe"])

    if use_cache:
        json = result_cache[query]
        json["index"] += 1
    else:
        # Randomly get authentication to allow for more requests
        key, cx = get_auth()

        json = await utils.download_json(
            "https://customsearch.googleapis.com/customsearch/v1",
            key=key,
            cx=cx,
            q=query,
            searchType="image",
            safe="active" if safe else "off"
        )

        assert "error" not in json, "Search failed, try again"
        assert "items" in json, "No results for {}".format(query)

        # Assign an index so that multiple searches with the same query
        # cycles through the cache
        json["index"] = 0
        json["safe"] = safe
        result_cache[query] = json

    items = json["items"]

    item = None
    while item is None:
        item = items[json["index"] % len(items)]

        # Ignore blacklisted keywords
        if any(s in item["link"] for s in blacklisted_url_keywords):
            json["index"] += 1
            item = None

    await client.say(message, item["link"])
