from __future__ import annotations

from typing import Literal

import aiosu

import app
from app.constants.mods import Mods
from app.logging import Ansi
from app.logging import log


async def lookup_beatmap(
    beatmap_md5: str | None = None,
    file_name: str | None = None,
    beatmap_id: int | None = None,
):
    kwargs = {}
    if beatmap_md5 is not None:
        kwargs["checksum"] = beatmap_md5
    if file_name is not None:
        kwargs["filename"] = file_name
    if beatmap_id is not None:
        kwargs["id"] = beatmap_id

    log(f"kwargs: {kwargs}", Ansi.LGREEN)

    try:
        aiosu_beatmap = await app.state.services.osu_api_v2.lookup_beatmap(**kwargs)
    except aiosu.exceptions.APIException as exc:
        if exc.status == 404:
            aiosu_beatmap = None
        else:
            raise
    except Exception as exc:
        log(f"Failed to lookup beatmap {beatmap_id} from osu! api v2: {exc}", Ansi.LRED)
        return

    if aiosu_beatmap is None:
        log(
            f"Beatmap not found",
            Ansi.LRED,
        )
        return

    assert aiosu_beatmap.checksum is not None
    assert aiosu_beatmap.last_updated is not None

    return aiosu_beatmap


async def get_beatmapset(
    beatmapset_id: int,
):
    try:
        log(f"beatmapset_id: {beatmapset_id}", Ansi.LGREEN)
        aiosu_beatmapset = await app.state.services.osu_api_v2.get_beatmapset(
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
        return

    if aiosu_beatmapset is None:
        log(
            f"Beatmapset not found",
            Ansi.LRED,
        )
        return

    assert aiosu_beatmapset.last_updated is not None

    return aiosu_beatmapset


async def get_beatmap_scores(
    beatmap_id: int,
    mode: int,
    mods: int | None = None,
):
    try:
        if mods is not None:
            aiosu_scores = await app.state.services.osu_api_v2.get_beatmap_scores(
                beatmap_id=beatmap_id,
                mode=aiosu.models.gamemode.Gamemode(mode),
                mods=aiosu.models.mods.Mods(mods),
                legacy_only=True,
            )
        else:
            aiosu_scores = await app.state.services.osu_api_v2.get_beatmap_scores(
                beatmap_id=beatmap_id,
                mode=aiosu.models.gamemode.Gamemode(mode),
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
        return

    if aiosu_scores is None:
        log(
            f"Beatmap scores not found or you don't have supporter",
            Ansi.LRED,
        )
        return

    return aiosu_scores
