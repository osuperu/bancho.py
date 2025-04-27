from __future__ import annotations

from datetime import datetime
from typing import Any
from typing import TypedDict

from tenacity import retry
from tenacity.stop import stop_after_attempt

import app.settings
from app.logging import Ansi
from app.logging import log


class BeatmapApiResponse(TypedDict):
    data: list[dict[str, Any]] | None
    status_code: int


class ScoreApiResponse(TypedDict):
    data: list[dict[str, Any]] | None
    status_code: int


class ReplayApiResponse(TypedDict):
    data: dict[str, Any] | None
    status_code: int


@retry(reraise=True, stop=stop_after_attempt(3))
async def api_get_beatmaps(**params: Any) -> BeatmapApiResponse:
    """\
    Fetch data from the osu!api with a beatmap's md5.

    Optionally use osu.direct's API if the user has not provided an osu! api key.
    """
    if app.settings.DEBUG:
        log(f"Doing api (getbeatmaps) request {params}", Ansi.LMAGENTA)

    if app.settings.OSU_API_KEY:
        # https://github.com/ppy/osu-api/wiki#apiget_beatmaps
        url = "https://old.ppy.sh/api/get_beatmaps"
        params["k"] = str(app.settings.OSU_API_KEY)
    else:
        # https://osu.direct/doc
        url = "https://osu.direct/api/get_beatmaps"

    response = await app.state.services.http_client.get(url, params=params)
    response_data = response.json()
    if response.status_code == 200 and response_data:  # (data may be [])
        return {"data": response_data, "status_code": response.status_code}

    return {"data": None, "status_code": response.status_code}


@retry(reraise=True, stop=stop_after_attempt(5))
async def api_get_scores(
    scoring_metric: str,
    **params: Any,
) -> list[dict[str, Any]] | None:
    if app.settings.DEBUG:
        log(f"Doing api (getscores) request {params}", Ansi.LMAGENTA)

    url = "https://old.ppy.sh/api/get_scores"
    params["k"] = str(app.settings.OSU_API_KEY)

    response = await app.state.services.http_client.get(url, params=params)
    response_data = response.json()

    scores: list[dict[str, Any]] = []
    date_format = "%Y-%m-%d %H:%M:%S"
    if response.status_code == 200 and response_data:
        for row in response_data:
            scores.append(
                {
                    "id": row["score_id"],
                    "_score": (
                        int(row["score"])
                        if scoring_metric == "score"
                        else float(row["pp"])
                    ),
                    "max_combo": row["maxcombo"],
                    "n50": row["count50"],
                    "n100": row["count100"],
                    "n300": row["count300"],
                    "nmiss": row["countmiss"],
                    "nkatu": row["countkatu"],
                    "ngeki": row["countgeki"],
                    "perfect": row["perfect"],
                    "mods": row["enabled_mods"],
                    "time": int(
                        datetime.strptime(row["date"], date_format).timestamp(),
                    ),
                    "userid": row["user_id"],
                    "name": row["username"],
                },
            )
        return scores


@retry(reraise=True, stop=stop_after_attempt(3))
async def api_get_osu_file(beatmap_id: int) -> bytes:
    url = f"https://old.ppy.sh/osu/{beatmap_id}"
    response = await app.state.services.http_client.get(url)
    response.raise_for_status()
    return response.read()


@retry(reraise=True, stop=stop_after_attempt(3))
async def api_get_replay(score_id: int, mode: int) -> ReplayApiResponse:
    url = f"https://old.ppy.sh/api/get_replay?k={app.settings.OSU_API_KEY}&s={score_id}&m={mode}"
    response = await app.state.services.http_client.get(url)
    response_data = response.json()

    if response.status_code == 200 and response_data:
        return {"data": response_data, "status_code": response.status_code}

    return {"data": None, "status_code": response.status_code}


@retry(reraise=True, stop=stop_after_attempt(3))
async def api_get_avatar(user_id: int) -> bytes:
    url = f"https://a.ppy.sh/{user_id}"
    response = await app.state.services.http_client.get(url)
    response.raise_for_status()
    return response.read()
