from __future__ import annotations

import aiosu
from aiosu.models import Beatmap
from aiosu.models import Beatmapset
from aiosu.models import Gamemode
from aiosu.models import Mods
from aiosu.models.score import Score

from app.logging import Ansi
from app.logging import log
from app.state import services


async def lookup_beatmap(
    beatmap_md5: str | None = None,
    file_name: str | None = None,
    beatmap_id: int | None = None,
) -> Beatmap | None:
    kwargs: dict[str, str | int] = {}
    if beatmap_md5 is not None:
        kwargs["checksum"] = beatmap_md5
    if file_name is not None:
        kwargs["filename"] = file_name
    if beatmap_id is not None:
        kwargs["id"] = beatmap_id

    try:
        aiosu_beatmap = await services.osu_api_v2.lookup_beatmap(**kwargs)
    except aiosu.exceptions.APIException as exc:
        if exc.status == 404:
            aiosu_beatmap = None
        else:
            raise
    except Exception as exc:
        log(f"Failed to lookup beatmap {beatmap_id} from osu! api v2: {exc}", Ansi.LRED)
        return None

    if aiosu_beatmap is None:
        log(
            f"Beatmap not found",
            Ansi.LRED,
        )
        return None

    assert aiosu_beatmap.checksum is not None
    assert aiosu_beatmap.last_updated is not None

    return aiosu_beatmap


async def get_beatmapset(
    beatmapset_id: int,
) -> Beatmapset | None:
    try:
        aiosu_beatmapset = await services.osu_api_v2.get_beatmapset(
            beatmapset_id=beatmapset_id,
        )
    except aiosu.exceptions.APIException as exc:
        if exc.status == 404:
            aiosu_beatmapset = None
        else:
            raise
    except Exception as exc:
        log(
            f"Failed to get beatmapset {beatmapset_id} from osu! api v2: {exc}",
            Ansi.LRED,
        )
        raise

    if aiosu_beatmapset is None:
        log(
            f"Beatmapset not found",
            Ansi.LRED,
        )
        return None

    assert aiosu_beatmapset.last_updated is not None

    return aiosu_beatmapset


async def get_beatmap_scores(
    beatmap_id: int,
    mode: int,
    mods: int | None = None,
) -> list[Score] | None:
    try:
        if mods is not None:
            aiosu_scores = await services.osu_api_v2.get_beatmap_scores(
                beatmap_id=beatmap_id,
                mode=Gamemode(mode),
                mods=Mods(mods),
                legacy_only=True,
            )
        else:
            aiosu_scores = await services.osu_api_v2.get_beatmap_scores(
                beatmap_id=beatmap_id,
                mode=Gamemode(mode),
                legacy_only=True,
            )
    except aiosu.exceptions.APIException as exc:
        if exc.status in (
            404,
            422,
        ):  # 422: You must be an osu!supporter to use this feature.
            aiosu_scores = None
        else:
            raise
    except Exception as exc:
        log(f"Failed to get beatmap scores from osu! api v2: {exc}", Ansi.LRED)
        return None

    if aiosu_scores is None:
        log(
            f"Beatmap scores not found or you don't have supporter",
            Ansi.LRED,
        )
        return None

    return aiosu_scores
