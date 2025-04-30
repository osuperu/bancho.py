from __future__ import annotations

from typing import Any

from tenacity import retry
from tenacity.stop import stop_after_attempt

import app.settings
from app.logging import Ansi
from app.logging import log
from app.state import services


async def get_osu_file(beatmap_id: int) -> bytes | None:
    try:
        if app.settings.DEBUG:
            log(
                f"Doing osu! api (osu_file) request for beatmap {beatmap_id}",
                Ansi.LMAGENTA,
            )

        aiosu_osu_file = await services.osu_api_v1.get_beatmap_osu(
            beatmap_id=beatmap_id,
        )
    except Exception:
        log(f"Failed to fetch osu file ({beatmap_id}.osu) from osu! api", Ansi.LRED)
        return None

    if aiosu_osu_file is None:
        log(
            f"Beatmap {beatmap_id}.osu not found",
            Ansi.LRED,
        )
        return None

    return aiosu_osu_file.read().encode("utf-8")


async def get_replay(
    score_id: int,
    mode: int,
) -> Any | None:
    try:
        if app.settings.DEBUG:
            log(
                f"Doing osu! api (get_replay) request for score {score_id}",
                Ansi.LMAGENTA,
            )

        aiosu_replay = await services.osu_api_v1.get_replay(
            score_id=score_id,
            mode=mode,
        )
    except Exception:
        log(f"Failed to fetch replay ({score_id}.osr) from osu! api", Ansi.LRED)
        return None

    return aiosu_replay


@retry(reraise=True, stop=stop_after_attempt(3))
async def api_get_avatar(user_id: int) -> bytes:
    # TODO: this is not technically part of the api
    if app.settings.DEBUG:
        log(f"Doing osu! api (avatar) request for user {user_id}", Ansi.LMAGENTA)

    url = f"https://a.ppy.sh/{user_id}"
    response = await services.http_client.get(url)
    response.raise_for_status()
    return response.read()
