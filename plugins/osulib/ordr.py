""" Basic API integration for ordr.

    Can render replays and fetch replays by ID
"""
import json
import logging
from datetime import datetime, timezone

import socketio
from aiohttp import FormData

from pcbot import utils, config, Config

host = "https://apis.issou.best/ordr/"
ws_link = "https://apis.issou.best"
socket_path = "/ordr/ws"
requested_renders = {}

ordr_client = socketio.AsyncClient()

ordr_config = Config("ordr", pretty=True, data={
    "verificationKey": "change to your API key",
    "resolution": "1280x720",  # The resolution of the replay
    "globalVolume": 80,  # The global volume of the replay
    "musicVolume": 80,  # The music volume of the replay
    "hitsoundVolume": 80,  # The hitsound volume of the replay
    "showHitErrorMeter": "true",  # Whether or not to show the hiterror meter
    "showUnstableRate": "true",  # Whether or not to display the UR
    "showScore": "true",  # Whether or not to display the score
    "showHPbar": "true",  # Whether or not to display the HP bar
    "showComboCounter": "true",  # Whether or not to display the combo counter
    "showPPCounter": "true",  # Whether or not to display the PP counter
    "showScoreboard": "false",  # Whether or not to display the scoreboard (This might
    "showBorders": "false",  # Whether or not to display playfield borders
    "showMods": "true",  # Whether or not to display mod icons
    "showResultScreen": "false",  # Whether or not to show the results screen
    "skin": "heckin",  # The name or ID of the skin to use
    "useSkinCursor": "true",  # Whether or not to use the skin cursor
    "useBeatmapColors": "false",  # Whether or not to use beatmap colors instead of skin colors
    "useSkinColors": "true",  # Whether or not to use skin colors instead of beatmap colors
    "useSkinHitsounds": "false",  # Whether or not to use skin hitsounds instead of beatmap hitsounds
    "cursorScaleToCS": "false",  # Whether or not the cursor should scale with CS
    "cursorRainbow": "false",  # Whether or not the cursor should rainbow, only works if useSkinCursor is False
    "cursorTrailGlow": "false",  # Whether or not the cursor trail should have a glow
    "drawFollowPoints": "true",  # Whether or not followpoints should be shown
    "scaleToTheBeat": "false",  # Whether or not objects should scale to the beat
    "sliderMerge": "false",  # Whether or not sliders should be merged
    "objectsRainbow": "false",  # Whether or not objects should rainbow. This overrides beatmap or skin colors
    "objectsFlashToTheBeat": "false",  # Whether or not objects should flash to the beat
    "useHitCircleColor": "false",  # Whether or not the slider body should have the same color as the hitcircles
    "seizureWarning": "false",  # Whether or not to display the 5 second seizure warning before the render
    "loadStoryboard": "false",  # Whether or not to load the beatmap storyshow
    "loadVideo": "false",  # Whether or not to load the beatmap video
    "introBGDim": 80,  # How dimmed the intro BG should be in percentage from 0 to 100
    "inGameBGDim": 90,  # How dimmed the ingame BG should be in percentage from 0 to 100
    "breakBGDim": 80,  # How dimmed the break BG should be in percentage from 0 to 100
    "BGParallax": "false",  # Whether or not the BG should have parralax
    "showDanserLogo": "true",  # Whether or not to show the danser logo before the render
    "skip": "false",  # Whether or not to skip the intro
    "cursorRipples": "false",  # Whether or not to show cursor ripples
    "cursorSize": 1,  # The size of the cursor from 0.5 to 2
    "cursorTrail": "true",  # Whether or not to show the cursortrail
    "drawComboNumbers": "true",  # Whether or not to show combo number in hitcircles
    "sliderSnakingIn": "true",  # Whether or not sliders should snake in
    "sliderSnakingOut": "false",  # Whether or not sliders should snake out
    "showHitCounter": "true",  # Whether or not the hit counter (100s, 50s, misses) should be shown
    "showKeyOverlay": "true",  # Whether or not the key overlay should be shown
    "showAvatarsOnScoreboard": "false",  # Whether or not to show avatars on the scoreboard. May break some skins
    "showAimErrorMeter": "false",  # Whether or not to show an aim error meter
    "playNightcoreSamples": "true",  # Whether or not to play nightcore hitsounds
})


def get_render_error(error_code: int):
    error = ""
    if error_code == 1:
        error = "Render stopped manually by ordr."
    elif error_code == 2:
        error = "Error downloading replay."
    elif error_code == 3:
        error = "Error downloading replay."
    elif error_code == 4:
        error = "Beatmap mirrors unavailable."
    elif error_code == 5:
        error = "Replay file corrupted."
    elif error_code == 6:
        error = "Only osu!standard is supported for replay rendering."
    elif error_code == 7:
        error = "Replay has no input data."
    elif error_code == 8:
        error = "Custom difficulties or unsubmitted maps are unsupported."
    elif error_code == 9:
        error = "Audio for this beatmap is unavailable."
    elif error_code == 10:
        error = "Cannot connect to osu!api."
    elif error_code == 11:
        error = "Auto is not supported."
    elif error_code == 12:
        error = "Invalid characters in replay username."
    elif error_code == 13:
        error = "The beatmap is longer than 15 minutes."
    elif error_code == 14:
        error = "This player is banned from ordr."
    elif error_code == 15:
        error = "Beatmap not found on any mirrors."
    elif error_code == 16:
        error = "This IP is banned from ordr."
    elif error_code == 17:
        error = "This username is banned from ordr."
    elif error_code == 18:
        error = "An unknown error from the renderer occured."
    elif error_code == 19:
        error = "The renderer cannot download the beatmap."
    elif error_code == 20:
        error = "Beatmap version is not the same on mirrors as the replay."
    elif error_code == 21:
        error = "Replay is corrupted (danser can't process it)."
    elif error_code == 22:
        error = "Server-side error finalizing the video."
    elif error_code == 23:
        error = "Server-side error preparing the replay."
    elif error_code == 24:
        error = "The beatmap has no name."
    elif error_code == 25:
        error = "The replay is missing input data."
    elif error_code == 26:
        error = "The replay has incompatible mods."
    elif error_code == 27:
        error = "Something went wrong while rendering."
    elif error_code == 28:
        error = "The renderer cannot download the replay."
    elif error_code == 29:
        error = "The replay is already rendering."
    elif error_code == 30:
        error = "The star rating is greater than 20."
    elif error_code == 31:
        error = "This mapper is blacklisted from ordr."
    return error


@ordr_client.event()
async def render_done_json(data: json):
    render_id = data["renderID"]
    video_url = data["videoUrl"]
    if render_id in requested_renders:
        await requested_renders[render_id]["message"].edit(content=video_url)
        requested_renders.pop(render_id)


@ordr_client.event()
async def render_failed_json(data: json):
    render_id = data["renderID"]
    error_message = data["errorMessage"]
    if render_id in requested_renders:
        await requested_renders[render_id]["message"].edit(content=error_message)
        requested_renders.pop(render_id)


@ordr_client.event()
async def render_progress_json(data: json):
    render_id = data["renderID"]
    progress = data["progress"]
    renderer = data["renderer"]
    if render_id in requested_renders:
        if (datetime.now(timezone.utc) - requested_renders[render_id]["edited"]).total_seconds() > 5:
            await requested_renders[render_id]["message"].edit(content=f"{progress}\nRendered by: {renderer}")
            requested_renders[render_id]["edited"] = datetime.now(timezone.utc)


@ordr_client.event()
async def connect():
    logging.info("Client successfully connected to ordr websocket.")


@ordr_client.event()
async def disconnect():
    logging.info("Disconnected from ordr websocket. Attempting to reconnect.")


@ordr_client.event()
async def connect_error(_):
    logging.info("Connection to ordr websocket failed.")


async def get_render(render_id: int):
    """ Return an ordr render by it's ID """
    params = {
        "renderID": render_id
    }

    results = await utils.download_json(url=host + "renders", **params)
    if not results:
        return None
    result = results["renders"][0]
    return result


async def send_render_job(option):
    """ Send a replay to be rendered by ordr.
    """
    replay = None
    replay_url = None

    if isinstance(option, (bytes, bytearray)):
        replay = option
    elif utils.http_url_pattern.match(option):
        replay_url = option

    params = {
        "username": config.name,
        "resolution": ordr_config.data["resolution"],
        "globalVolume": ordr_config.data["globalVolume"],
        "musicVolume": ordr_config.data["musicVolume"],
        "hitsoundVolume": ordr_config.data["hitsoundVolume"],
        "showHitErrorMeter": ordr_config.data["showHitErrorMeter"],
        "showUnstableRate": ordr_config.data["showUnstableRate"],
        "showScore": ordr_config.data["showScore"],
        "showHPbar": ordr_config.data["showHPbar"],
        "showComboCounter": ordr_config.data["showComboCounter"],
        "showPPCounter": ordr_config.data["showPPCounter"],
        "showScoreboard": ordr_config.data["showScoreboard"],
        "showBorders": ordr_config.data["showBorders"],
        "showMods": ordr_config.data["showMods"],
        "showResultScreen": ordr_config.data["showResultScreen"],
        "skin": ordr_config.data["skin"],
        "useSkinCursor": ordr_config.data["useSkinCursor"],
        "useSkinColors": ordr_config.data["useSkinColors"],
        "useBeatmapColors": ordr_config.data["useBeatmapColors"],
        "useSkinHitsounds": ordr_config.data["useSkinHitsounds"],
        "cursorScaleToCS": ordr_config.data["cursorScaleToCS"],
        "cursorTrailGlow": ordr_config.data["cursorTrailGlow"],
        "drawFollowPoints": ordr_config.data["drawFollowPoints"],
        "scaleToTheBeat": ordr_config.data["scaleToTheBeat"],
        "sliderMerge": ordr_config.data["sliderMerge"],
        "cursorRainbow": ordr_config.data["cursorRainbow"],
        "objectsRainbow": ordr_config.data["objectsRainbow"],
        "objectsFlashToTheBeat": ordr_config.data["objectsFlashToTheBeat"],
        "useHitCircleColor": ordr_config.data["useHitCircleColor"],
        "seizureWarning": ordr_config.data["seizureWarning"],
        "loadStoryboard": ordr_config.data["loadStoryboard"],
        "loadVideo": ordr_config.data["loadVideo"],
        "introBGDim": ordr_config.data["introBGDim"],
        "inGameBGDim": ordr_config.data["inGameBGDim"],
        "breakBGDim": ordr_config.data["breakBGDim"],
        "BGParallax": ordr_config.data["BGParallax"],
        "showDanserLogo": ordr_config.data["showDanserLogo"],
        "skip": ordr_config.data["skip"],
        "cursorRipples": ordr_config.data["cursorRipples"],
        "cursorSize": ordr_config.data["cursorSize"],
        "cursorTrail": ordr_config.data["cursorTrail"],
        "drawComboNumbers": ordr_config.data["drawComboNumbers"],
        "sliderSnakingIn": ordr_config.data["sliderSnakingIn"],
        "sliderSnakingOut": ordr_config.data["sliderSnakingOut"],
        "showHitCounter": ordr_config.data["showHitCounter"],
        "showKeyOverlay": ordr_config.data["showKeyOverlay"],
        "showAvatarsOnScoreboard": ordr_config.data["showAvatarsOnScoreboard"],
        "showAimErrorMeter": ordr_config.data["showAimErrorMeter"],
        "playNightcoreSamples": ordr_config.data["playNightcoreSamples"]
    }

    if replay:
        params["replayFile"] = replay
    elif replay_url:
        params["replayURL"] = replay_url

    if ordr_config.data["verificationKey"] != "change to your API key":
        params["verificationKey"] = ordr_config.data["verificationKey"]

    data = FormData()
    for param, value in params.items():
        data.add_field(param, value)

    try:
        results = await utils.post_request(url=host + "renders", call=utils.convert_to_json, data=data)
    except ValueError as e:
        results = e

    return results


async def establish_ws_connection():
    if ordr_client.connected:
        await ordr_client.disconnect()
    try:
        await ordr_client.connect(ws_link, socketio_path=socket_path)
    except socketio.exceptions.ConnectionError:
        logging.error("Failed to connnect to ordr websocket.")
