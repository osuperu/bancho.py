from __future__ import annotations

import hashlib
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
from app.repositories.tokens import Token
from app.usecases import authentication

router = APIRouter()


def auth_failure_response(reason: str) -> dict[str, Any]:
    return {"error": reason}


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
