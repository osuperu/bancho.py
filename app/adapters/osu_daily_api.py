# https://osudaily.net/api.php
from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from typing import TypedDict

from fastapi import status
from tenacity import TryAgain
from tenacity import retry
from tenacity import stop_after_attempt

import app.settings
from app.constants.gamemodes import GameMode
from app.logging import Ansi
from app.logging import log
from app.state import services


class ClosestRankApiResponse(TypedDict):
    data: dict[str, Any] | None
    status_code: int


@retry(reraise=True, stop=stop_after_attempt(5))
async def get_closest_rank(pp: float, mode: GameMode) -> ClosestRankApiResponse:
    if app.settings.DEBUG:
        log(f"Doing api (pp) request for {pp} pp and mode {mode}", Ansi.LMAGENTA)

    url = "https://osudaily.net/api/pp.php"
    params: Mapping[str, str | float | int] = {
        "k": app.settings.OSU_DAILY_API_KEY,
        "t": "pp",
        "v": pp,
        "m": mode,
    }

    response = await services.http_client.get(url, params=params)

    if "A maintenance job is in progress." in response.content.decode("utf-8"):
        return {"data": None, "status_code": status.HTTP_503_SERVICE_UNAVAILABLE}

    response_data = response.json()
    if response.status_code == 200 and response_data:
        if (
            "error" in response_data
            and response_data["error"] == "Only 1 request per second is authorized"
        ):
            raise TryAgain
        return {"data": response_data, "status_code": response.status_code}

    return {"data": None, "status_code": response.status_code}
