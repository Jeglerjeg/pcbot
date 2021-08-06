""" Basic API integration for ordr.

    Can render replays and fetch replays by ID
"""

from aiohttp import FormData

from pcbot import utils, config, Config

host = "https://ordr-api.issou.best/"

ordr_config = Config("ordr", pretty=True, data=dict(
    verificationKey="change to your API key",
    resolution="1280x720",  # The resolution of the replay
    globalVolume=80,  # The global volume of the replay
    musicVolume=80,  # The music volume of the replay
    hitsoundVolume=80,  # The hitsound volume of the replay
    showHitErrorMeter="true",  # Whether or not to show the hiterror meter
    showUnstableRate="true",  # Whether or not to display the UR
    showScore="true",  # Whether or not to display the score
    showHPbar="true",  # Whether or not to display the HP bar
    showComboCounter="true",  # Whether or not to display the combo counter
    showPPCounter="true",  # Whether or not to display the PP counter
    showScoreboard="false",  # Whether or not to display the scoreboard (This might
    showBorders="false",  # Whether or not to display playfield borders
    showMods="true",  # Whether or not to display mod icons
    showResultScreen="false",  # Whether or not to show the results screen
    skin="heckin",  # The name or ID of the skin to use
    useSkinCursor="true",  # Whether or not to use the skin cursor
    useBeatmapColors="false",  # Whether or not to use beatmap colors instead of skin colors
    useSkinColors="true",  # Whether or not to use skin colors instead of beatmap colors
    useSkinHitsounds="false",  # Whether or not to use skin hitsounds instead of beatmap hitsounds
    cursorScaleToCS="false",  # Whether or not the cursor should scale with CS
    cursorRainbow="false",  # Whether or not the cursor should rainbow, only works if useSkinCursor is False
    cursorTrailGlow="false",  # Whether or not the cursor trail should have a glow
    drawFollowPoints="true",  # Whether or not followpoints should be shown
    scaleToTheBeat="false",  # Whether or not objects should scale to the beat
    sliderMerge="false",  # Whether or not sliders should be merged
    objectsRainbow="false",  # Whether or not objects should rainbow. This overrides beatmap or skin colors
    objectsFlashToTheBeat="false",  # Whether or not objects should flash to the beat
    useHitCircleColor="false",
    seizureWarning="false",
    loadStoryboard="false",
    loadVideo="false",
    introBGDim=80,
    inGameBGDim=90,
    breakBGDim=80,
    BGParallax="false",
    showDanserLogo="true",
    skip="false",
    cursorRipples="false",
    cursorSize=1,
    cursorTrail="true",
    drawComboNumbers="true",
    sliderSnakingIn="true",
    sliderSnakingOut="false",
))


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
        "sliderSnakingOut": ordr_config.data["sliderSnakingOut"]
    }

    if replay:
        params["replayFile"] = replay
    elif replay_url:
        params["replayURL"] = replay_url

    if ordr_config.data["verificationKey"] != "change to your API key":
        params["verificationKey"] = ordr_config.data["verificationKey"]

    data = FormData()
    for value in params:
        data.add_field(value, params[value])

    try:
        results = await utils.post_request(url=host + "renders", call=utils._convert_json, data=data)
    except ValueError as e:
        results = e

    return results
