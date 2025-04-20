"""bancho.py's v2 apis for interacting with players"""

from __future__ import annotations

import hashlib

import bcrypt
from fastapi import APIRouter
from fastapi import Cookie
from fastapi import Depends
from fastapi import status
from fastapi.param_functions import Query
from fastapi.security import HTTPAuthorizationCredentials as HTTPCredentials
from fastapi.security import HTTPBearer

import app.state.sessions
from app.api.v2.common import responses
from app.api.v2.common.responses import Failure
from app.api.v2.common.responses import Success
from app.api.v2.models.players import Player
from app.api.v2.models.players import PlayerStats
from app.api.v2.models.players import PlayerStatus
from app.api.v2.models.players import UpdatePlayerEmailRequest
from app.api.v2.models.players import UpdatePlayerPasswordRequest
from app.api.v2.models.players import UpdatePlayerUsernameRequest
from app.constants import regexes
from app.repositories import relationships as relationships_repo
from app.repositories import stats as stats_repo
from app.repositories import tokens as tokens_repo
from app.repositories import users as users_repo
from app.usecases import authentication

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
    user_access_token: str = Cookie(..., alias="X-Bpy-Token", strict=True),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
) -> Success[list[Player]] | Failure:
    hashed_access_token = hashlib.md5(user_access_token.encode()).hexdigest()

    token_data = await tokens_repo.fetch_one(hashed_access_token)
    if token_data is None:
        return responses.failure(
            message="Invalid token.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    user = await relationships_repo.fetch_friends(
        user_id=token_data["userid"],
        page=page,
        page_size=page_size,
    )
    total_users = await relationships_repo.fetch_friends_count(
        user_id=token_data["userid"],
    )

    response = [Player.from_mapping(rec) for rec in user]

    return responses.success(
        content=response,
        meta={
            "total": total_users,
            "page": page,
            "page_size": page_size,
        },
    )


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


@router.put("/players/{player_id}/username")
async def update_player_username(
    player_id: int,
    args: UpdatePlayerUsernameRequest,
) -> Success[Player] | Failure:
    player = await users_repo.fetch_one(id=player_id, fetch_all_fields=True)

    if player is None:
        return responses.failure(
            message="Player not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    pw_md5 = hashlib.md5(args.current_password.encode()).hexdigest()

    if not bcrypt.checkpw(pw_md5.encode(), player["pw_bcrypt"].encode()):
        return responses.failure(
            message="Invalid password.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    player = await users_repo.partial_update(
        id=player_id,
        name=args.new_username,
    )

    response = Player.from_mapping(player)  # type: ignore
    return responses.success(response)


@router.put("/players/{player_id}/email")
async def update_player_email(
    player_id: int,
    args: UpdatePlayerEmailRequest,
) -> Success[Player] | Failure:
    player = await users_repo.fetch_one(id=player_id, fetch_all_fields=True)

    if player is None:
        return responses.failure(
            message="Player not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    pw_md5 = hashlib.md5(args.current_password.encode()).hexdigest()

    if not bcrypt.checkpw(pw_md5.encode(), player["pw_bcrypt"].encode()):  # type: ignore
        return responses.failure(
            message="Invalid password.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    player = await users_repo.partial_update(
        id=player_id,
        email=args.new_email,
    )

    response = Player.from_mapping(player)  # type: ignore
    return responses.success(response)


@router.put("/players/{player_id}/password")
async def update_player_password(
    player_id: int,
    args: UpdatePlayerPasswordRequest,
) -> Success[Player] | Failure:
    player = await users_repo.fetch_one(id=player_id, fetch_all_fields=True)

    if player is None:
        return responses.failure(
            message="Player not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    pw_md5 = hashlib.md5(args.current_password.encode()).hexdigest()

    if not bcrypt.checkpw(pw_md5.encode(), player["pw_bcrypt"].encode()):  # type: ignore
        return responses.failure(
            message="Invalid password.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    new_pw_md5 = hashlib.md5(args.new_password.encode()).hexdigest()
    new_pw_bcrypt = bcrypt.hashpw(new_pw_md5.encode(), bcrypt.gensalt())

    player = await users_repo.partial_update(
        id=player_id,
        pw_bcrypt=new_pw_bcrypt,
    )

    response = Player.from_mapping(player)  # type: ignore
    return responses.success(response)
