"""bmap: static beatmap info (thumbnails, previews, etc.)"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi import Path
from fastapi import Response
from fastapi import status
from fastapi.requests import Request
from fastapi.responses import RedirectResponse

from app import utils
from app.api.domains.osu import AUDIO_PATH
from app.api.domains.osu import THUMBNAILS_PATH
from app.repositories.maps import INITIAL_MAP_ID

# import app.settings

router = APIRouter(tags=["Beatmaps"])


@router.get("/thumb/{file}")
async def thumbnail(file: str = Path(...)) -> Response:
    map_set_id = file.removesuffix(".jpg")
    large = map_set_id.endswith("l")

    map_set_id = map_set_id[:-1] if large else map_set_id

    if int(map_set_id) >= INITIAL_MAP_ID:
        thumbnail_file = THUMBNAILS_PATH / f"{map_set_id}.jpg"

        if thumbnail_file.exists():
            if not large:
                thumbnail_file = utils.resize_image(
                    thumbnail_file.read_bytes(),
                    target_width=80,
                    target_height=60,
                )
            else:
                thumbnail_file = thumbnail_file.read_bytes()

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
        audio_file = AUDIO_PATH / f"{map_set_id}.mp3"

        if audio_file.exists():
            return Response(
                status_code=status.HTTP_200_OK,
                media_type="audio/mpeg",
                content=audio_file.read_bytes(),
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
