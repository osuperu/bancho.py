"""bancho.py's v2 apis for interacting with players"""

from __future__ import annotations

import hashlib

import bcrypt
from fastapi import APIRouter
from fastapi import Depends
from fastapi import File
from fastapi import UploadFile
from fastapi import status
from fastapi.param_functions import Query
from fastapi.security import HTTPBearer

import app.state.sessions
from app.api.v2.authentication import authenticate_user_session
from app.api.v2.common import responses
from app.api.v2.common.responses import Failure
from app.api.v2.common.responses import Success
from app.api.v2.models.players import Player
from app.api.v2.models.players import PlayerStats
from app.api.v2.models.players import PlayerStatus
from app.api.v2.models.players import UpdatePlayerEmailRequest
from app.api.v2.models.players import UpdatePlayerPasswordRequest
from app.api.v2.models.players import UpdatePlayerUsernameRequest
from app.repositories import relationships as relationships_repo
from app.repositories import stats as stats_repo
from app.repositories import users as users_repo
from app.repositories.users import User

router = APIRouter()
oauth2_scheme = HTTPBearer(auto_error=False)


@router.get("/players")
async def get_players(
    priv: int | None = None,
    country: str | None = None,
    clan_id: int | None = None,
    clan_priv: int | None = None,
    preferred_mode: int | None = None,
    play_style: int | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
) -> Success[list[Player]] | Failure:
    players = await users_repo.fetch_many(
        priv=priv,
        country=country,
        clan_id=clan_id,
        clan_priv=clan_priv,
        preferred_mode=preferred_mode,
        play_style=play_style,
        page=page,
        page_size=page_size,
    )
    total_players = await users_repo.fetch_count(
        priv=priv,
        country=country,
        clan_id=clan_id,
        clan_priv=clan_priv,
        preferred_mode=preferred_mode,
        play_style=play_style,
    )

    response = [Player.from_mapping(rec) for rec in players]

    return responses.success(
        content=response,
        meta={
            "total": total_players,
            "page": page,
            "page_size": page_size,
        },
    )


@router.get("/players/friends")
async def get_player_friends(
    user: User | Failure = Depends(authenticate_user_session()),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
) -> Success[list[Player]] | Failure:
    if isinstance(user, Failure):
        return user

    friends = await relationships_repo.fetch_friends(
        user_id=user["id"],
        page=page,
        page_size=page_size,
    )
    total_friends = await relationships_repo.fetch_friends_count(
        user_id=user["id"],
    )

    response = [Player.from_mapping(rec) for rec in friends]

    return responses.success(
        content=response,
        meta={
            "total": total_friends,
            "page": page,
            "page_size": page_size,
        },
    )


@router.put("/players/username")
async def update_player_username(
    args: UpdatePlayerUsernameRequest,
    user: User | Failure = Depends(authenticate_user_session()),
) -> Success[Player] | Failure:
    if isinstance(user, Failure):
        return user

    pw_md5 = hashlib.md5(args.current_password.encode()).hexdigest()

    if not bcrypt.checkpw(pw_md5.encode(), user["pw_bcrypt"].encode()):
        return responses.failure(
            message="Invalid password.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    updated_user = await users_repo.partial_update(
        id=user["id"],
        name=args.new_username,
    )

    response = Player.from_mapping(updated_user)  # type: ignore
    return responses.success(response)


@router.put("/players/email")
async def update_player_email(
    args: UpdatePlayerEmailRequest,
    user: User | Failure = Depends(authenticate_user_session()),
) -> Success[Player] | Failure:
    if isinstance(user, Failure):
        return user

    pw_md5 = hashlib.md5(args.current_password.encode()).hexdigest()

    if not bcrypt.checkpw(pw_md5.encode(), user["pw_bcrypt"].encode()):  # type: ignore
        return responses.failure(
            message="Invalid password.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    updated_user = await users_repo.partial_update(
        id=user["id"],
        email=args.new_email,
    )

    response = Player.from_mapping(updated_user)  # type: ignore
    return responses.success(response)


@router.put("/players/avatar")
async def update_player_avatar(
    avatar: UploadFile = File(..., alias="avatar"),
    user: User | Failure = Depends(authenticate_user_session()),
) -> Success[Player] | Failure:
    if isinstance(user, Failure):
        return user

    if avatar.content_type not in ("image/png", "image/jpeg"):
        return responses.failure(
            message="Invalid file type.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    avatar_file = avatar.file.read()

    if len(avatar_file) > 4 * 1024 * 1024:
        return responses.failure(
            message="File too large.",
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        )

    ext = "png" if avatar.content_type == "image/png" else "jpg"
    app.state.services.storage.upload_avatar(user["id"], ext, avatar_file)

    response = Player.from_mapping(user)
    return responses.success(response)


@router.put("/players/password")
async def update_player_password(
    args: UpdatePlayerPasswordRequest,
    user: User | Failure = Depends(authenticate_user_session()),
) -> Success[Player] | Failure:
    if isinstance(user, Failure):
        return user

    pw_md5 = hashlib.md5(args.current_password.encode()).hexdigest()

    if not bcrypt.checkpw(pw_md5.encode(), user["pw_bcrypt"].encode()):  # type: ignore
        return responses.failure(
            message="Invalid password.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    new_pw_md5 = hashlib.md5(args.new_password.encode()).hexdigest()
    new_pw_bcrypt = bcrypt.hashpw(new_pw_md5.encode(), bcrypt.gensalt())

    updated_user = await users_repo.partial_update(
        id=user["id"],
        pw_bcrypt=new_pw_bcrypt,
    )

    response = Player.from_mapping(updated_user)  # type: ignore
    return responses.success(response)


@router.get("/players/{player_id}")
async def get_player(player_id: int) -> Success[Player] | Failure:
    data = await users_repo.fetch_one(id=player_id)
    if data is None:
        return responses.failure(
            message="Player not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    response = Player.from_mapping(data)
    return responses.success(response)


@router.get("/players/{player_id}/status")
async def get_player_status(player_id: int) -> Success[PlayerStatus] | Failure:
    player = app.state.sessions.players.get(id=player_id)

    if not player:
        return responses.failure(
            message="Player status not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    response = PlayerStatus(
        login_time=int(player.login_time),
        action=int(player.status.action),
        info_text=player.status.info_text,
        mode=int(player.status.mode),
        mods=int(player.status.mods),
        beatmap_id=player.status.map_id,
    )
    return responses.success(response)


@router.get("/players/{player_id}/stats/{mode}")
async def get_player_mode_stats(
    player_id: int,
    mode: int,
) -> Success[PlayerStats] | Failure:
    data = await stats_repo.fetch_one(player_id, mode)
    if data is None:
        return responses.failure(
            message="Player stats not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    response = PlayerStats.from_mapping(data)
    return responses.success(response)


@router.get("/players/{player_id}/stats")
async def get_player_stats(
    player_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
) -> Success[list[PlayerStats]] | Failure:
    data = await stats_repo.fetch_many(
        player_id=player_id,
        page=page,
        page_size=page_size,
    )
    total_stats = await stats_repo.fetch_count(
        player_id=player_id,
    )

    response = [PlayerStats.from_mapping(rec) for rec in data]
    return responses.success(
        response,
        meta={
            "total": total_stats,
            "page": page,
            "page_size": page_size,
        },
    )
