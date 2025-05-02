from __future__ import annotations

from fastapi import APIRouter
from fastapi import Response
from fastapi.responses import RedirectResponse

import app.state
from app.adapters.osu_api_v1 import api_get_avatar
from app.repositories import users as users_repo

router = APIRouter(tags=["Avatars"])


@router.get("/{user_id}.{ext}")
async def get_avatar(user_id: int, ext: str) -> Response:
    user = await users_repo.fetch_one(user_id)

    if user is None or user_id == 1:
        avatar = app.state.services.storage.get_default_avatar()
        return Response(content=avatar, media_type="image/jpeg")

    avatar = app.state.services.storage.get_avatar(str(user["id"]), ext)

    if avatar is None:
        avatar = app.state.services.storage.get_default_avatar()
        return Response(content=avatar, media_type="image/jpeg")

    return Response(avatar, media_type=f"image/{ext}")


@router.get("/{user_id}")
async def get_avatar_osu(user_id: int) -> Response:
    for ext in ("jpg", "png"):
        avatar = app.state.services.storage.get_avatar(str(user_id), ext)
        if avatar is not None:
            return Response(avatar, media_type=f"image/{ext}")

    if app.state.services.storage.get_bancho_default_avatar() == await api_get_avatar(
        user_id,
    ):
        avatar = app.state.services.storage.get_default_avatar()
        return Response(content=avatar, media_type="image/jpeg")

    # we do it this way for bancho leaderboard feature
    return RedirectResponse(url=f"https://a.ppy.sh/{user_id}")
