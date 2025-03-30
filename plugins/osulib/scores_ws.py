import asyncio
import logging

from websockets.asyncio.client import connect

import plugins
from plugins.osulib import db, config, api
from plugins.osulib.constants import score_request_limit
from plugins.osulib.enums import GameMode
from plugins.osulib.models.score import OsuScore
from plugins.osulib.tracking import notify_pp, add_new_user
import json

from plugins.osulib.utils import score_utils

client = plugins.client  # type: bot.Client

tracked_users = {}
for member in db.get_linked_osu_profiles():
    if member.osu_id in tracked_users:
        tracked_users[member.osu_id].add(member.id)
    else:
        tracked_users[member.osu_id] = {member.id}

async def run():
    # Create the websocket stream
    scores_ws_url = config.osu_config.data.get("scores_ws_url")
    if scores_ws_url == "Change to the scores-ws websocket URL":
        scores_ws_url = "ws://127.0.0.1:7727"
    try:
        async with connect(scores_ws_url) as websocket:
            # Send the initial message within 5 seconds of connecting the websocket.
            # Must be either "connect" or a score id to resume from
            await websocket.send("connect")

            # Let's run it for a bit until we disconnect manually
            await process_scores(websocket)
    except Exception as e:
        logging.error(f"Couldn't connect: {e}")

async def process_scores(websocket):
    async for event in websocket:
        try:
            score = json.loads(event)
            if int(score["user_id"]) in tracked_users:
                score = OsuScore(score)
                for member_id in tracked_users[score.user_id]:
                    db_user = db.get_osu_user(member_id)
                    if not db_user:
                        await add_new_user(member_id, score.user_id)
                    db_user = db.get_osu_user(member_id)

                    if score.mode != GameMode(db_user.mode):
                        continue

                    last_user_events = db.get_recent_events(int(member_id))
                    if not last_user_events:
                        db.insert_recent_events(int(member_id))
                        last_user_events = db.get_recent_events(int(member_id))

                    if score.id > last_user_events.last_pp_notification:
                        params = {
                            "mode": GameMode(db_user.mode).name,
                            "limit": score_request_limit,
                        }
                        api_user_scores = await api.get_user_scores(score.user_id, "best", params=params)
                        if check_top100(score, api_user_scores):
                            client.loop.create_task(notify_pp(member_id, score, db_user, last_user_events))
        except Exception as e:
            logging.error(e)


def check_top100(score: OsuScore, score_list: list[OsuScore]):
    sorted_scores = score_utils.get_sorted_scores(score_list, "pp")
    if score.pp < sorted_scores[len(sorted_scores) - 1].pp:
        return False
    for api_score in sorted_scores:
        if api_score.beatmap_id == score.beatmap_id and score.pp < api_score.pp:
            return False
    return True