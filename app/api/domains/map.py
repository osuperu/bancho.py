"""bmap: static beatmap info (thumbnails, previews, etc.)"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi import Path
from fastapi import Response
from fastapi import status
from fastapi.responses import RedirectResponse

import app.state
from app import utils
from app.repositories.maps import INITIAL_MAP_ID

router = APIRouter(tags=["Beatmaps"])


@router.get("/thumb/{file}")
async def thumbnail(file: str = Path(...)) -> Response:
    map_set_id = file.removesuffix(".jpg")
    large = map_set_id.endswith("l")

    map_set_id = map_set_id[:-1] if large else map_set_id

    if int(map_set_id) >= INITIAL_MAP_ID:
        thumbnail_file = app.state.services.storage.get_beatmap_thumbnail(map_set_id)

        if thumbnail_file is not None:
            if not large:
                thumbnail_file = utils.resize_image(
                    thumbnail_file,
                    target_width=80,
                    target_height=60,
                )

            return Response(
                status_code=status.HTTP_200_OK,
                media_type="image/jpeg",
                content=thumbnail_file,
            )
        else:
            return Response(
                status_code=status.HTTP_404_NOT_FOUND,
                content="Thumbnail not found",
            )

    return RedirectResponse(
        url=f"https://b.ppy.sh/thumb/{file}",
        status_code=status.HTTP_301_MOVED_PERMANENTLY,
    )


@router.get("/preview/{file}")
async def preview(file: str = Path(...)) -> Response:
    map_set_id = file.removesuffix(".mp3")

    if int(map_set_id) >= INITIAL_MAP_ID:
        audio_file = app.state.services.storage.get_beatmap_audio(map_set_id)

        if audio_file is not None:
            return Response(
                status_code=status.HTTP_200_OK,
                media_type="audio/mpeg",
                content=audio_file,
            )
        else:
            return Response(
                status_code=status.HTTP_404_NOT_FOUND,
                content="Preview not found",
            )

    return RedirectResponse(
        url=f"https://b.ppy.sh/preview/{file}",
        status_code=status.HTTP_301_MOVED_PERMANENTLY,
    )
