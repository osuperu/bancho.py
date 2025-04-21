from __future__ import annotations

import hashlib
from collections.abc import Awaitable
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter
from fastapi import Cookie
from fastapi import Response
from fastapi import status
from fastapi.responses import JSONResponse

from app.api.v2.common import responses
from app.api.v2.common.responses import Failure
from app.api.v2.models.authentication import AuthenticationRequest
from app.repositories import tokens
from app.repositories import tokens as tokens_repo
from app.repositories import users as users_repo
from app.repositories.tokens import Token
from app.repositories.users import User
from app.usecases import authentication

router = APIRouter()


def auth_failure_response(reason: str) -> dict[str, Any]:
    return {"error": reason}


def authenticate_user_session(
    token_alias: str = "X-Bpy-Token",
) -> Callable[[str], Awaitable[User | Failure]]:
    """Get a dependency function that authenticates a user by their access token.

    Args:
        token_alias: The name of the cookie containing the access token.

    Returns:
        A dependency function that returns a User if successful,
        or a Failure response if authentication fails.
    """

    async def wrapper(
        user_access_token: str = Cookie(..., alias=token_alias, strict=True),
    ) -> User | Failure:
        hashed_access_token = hashlib.md5(user_access_token.encode()).hexdigest()

        token_data = await tokens_repo.fetch_one(hashed_access_token)
        if token_data is None:
            return responses.failure(
                message="Invalid token.",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        user = await users_repo.fetch_one(
            id=token_data["userid"],
            fetch_all_fields=True,
        )
        if user is None:
            return responses.failure(
                message="User not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        return user

    return wrapper


@router.post("/authenticate")
async def authenticate(args: AuthenticationRequest) -> Any:
    _response = await authentication.authenticate(
        username=args.username,
        password=args.password,
    )

    if _response is None:
        return responses.failure(
            message="Incorrect username or password.",
        )

    http_response = JSONResponse(
        content=_response.identity.model_dump(),
        status_code=200,
    )
    http_response.set_cookie(
        "X-Bpy-Token",
        value=_response.unhashed_access_token,
        expires=60 * 60 * 24 * 30,
        secure=True,
        httponly=True,
        samesite="none",
    )

    return http_response


@router.post("/logout")
async def logout(
    user_access_token: str = Cookie(..., alias="X-Bpy-Token", strict=True),
) -> Any:
    trusted_access_token = await authorize_request(
        user_access_token=user_access_token,
        expected_user_id=None,
    )

    if trusted_access_token is None:
        return responses.failure(
            message="Invalid credentials.",
        )

    await authentication.logout(
        trusted_access_token=trusted_access_token,
    )

    http_response = Response(status_code=204)
    http_response.delete_cookie(
        "X-Bpy-Token",
        secure=True,
        httponly=True,
        samesite="none",
    )
    return http_response


async def authorize_request(
    user_access_token: str,
    expected_user_id: int | None = None,
) -> Token | None:
    hahsed_access_token = hashlib.md5(user_access_token.encode()).hexdigest()
    trusted_access_token = await tokens.fetch_one(
        hashed_access_token=hahsed_access_token,
    )

    if trusted_access_token is None:
        return None

    if (
        expected_user_id is not None
        and trusted_access_token["userid"] != expected_user_id
    ):
        return None

    return trusted_access_token
