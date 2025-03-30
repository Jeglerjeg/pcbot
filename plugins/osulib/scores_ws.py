import asyncio
import logging

from websockets.asyncio.client import connect

import plugins
from plugins.osulib import db, config
from plugins.osulib.enums import GameMode
from plugins.osulib.models.score import OsuScore
from plugins.osulib.tracking import notify_pp, add_new_user
import json

client = plugins.client  # type: bot.Client

tracked_users = {}
for member in db.get_linked_osu_profiles():
    if member.osu_id in tracked_users:
        tracked_users[member.osu_id].append(member.id)
    else:
        tracked_users[member.osu_id] = [member.id]

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
    try:
        async for event in websocket:
            # `event` consists of JSON bytes of a score as sent by the osu!api
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
                    if score.pp < db_user.min_pp:
                        continue

                    last_user_events = db.get_recent_events(int(member_id))
                    if not last_user_events:
                        db.insert_recent_events(int(member_id))
                        last_user_events = db.get_recent_events(int(member_id))

                    if score.id > last_user_events.last_pp_notification:
                        client.loop.create_task(notify_pp(member_id, score, db_user, last_user_events))
    except asyncio.CancelledError:
        raise