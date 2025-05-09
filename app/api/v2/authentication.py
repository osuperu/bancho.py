from __future__ import annotations

import hashlib
from collections.abc import Awaitable
from collections.abc import Callable
from typing import Any

import bcrypt
from fastapi import APIRouter
from fastapi import Cookie
from fastapi import Request
from fastapi import Response
from fastapi import status
from fastapi.responses import JSONResponse

import app.settings
from app.api.v2.common import responses
from app.api.v2.common.responses import Failure
from app.api.v2.models.authentication import AuthenticationRequest
from app.api.v2.models.authentication import RegistrationRequest
from app.constants import regexes
from app.repositories import stats as stats_repo
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
    response = await app.state.services.http_client.post(
        "https://hcaptcha.com/siteverify",
        data={
            "secret": app.settings.HCAPTCHA_SECRET_KEY,
            "response": args.hcaptcha_token,
        },
    )
    response_data = response.json()

    if not response_data["success"]:
        return responses.failure(
            message="Invalid captcha.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

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


@router.post("/register")
async def register(request: Request, args: RegistrationRequest) -> Any:
    response = await app.state.services.http_client.post(
        "https://hcaptcha.com/siteverify",
        data={
            "secret": app.settings.HCAPTCHA_SECRET_KEY,
            "response": args.hcaptcha_token,
        },
    )
    response_data = response.json()

    if not response_data["success"]:
        return responses.failure(
            message="Invalid captcha.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # Usernames must:
    # - be within 2-15 characters in length
    # - not contain both ' ' and '_', one is fine
    # - not be in the config's `disallowed_names` list
    # - not already be taken by another player
    if not regexes.USERNAME.match(args.username):
        return responses.failure(
            message="Username must be between 2 and 15 characters long.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if "_" in args.username and " " in args.username:
        return responses.failure(
            message='Username may contain "_" and " ", but not both.',
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if args.username in app.settings.DISALLOWED_NAMES:
        return responses.failure(
            message="Disallowed username; pick another.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if await users_repo.fetch_one(name=args.username):
        return responses.failure(
            message="Username already taken by another player.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # Emails must:
    # - match the regex `^[^@\s]{1,200}@[^@\s\.]{1,30}\.[^@\.\s]{1,24}$`
    # - not already be taken by another player
    if not regexes.EMAIL.match(args.email):
        return responses.failure(
            message="Invalid email syntax.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    else:
        if await users_repo.fetch_one(email=args.email):
            return responses.failure(
                message="Email already taken by another player.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

    # Passwords must:
    # - be within 8-32 characters in length
    # - have more than 3 unique characters
    # - not be in the config's `disallowed_passwords` list
    if not 8 <= len(args.password) <= 32:
        return responses.failure(
            message="Password must be between 8 and 32 characters long.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if len(set(args.password)) <= 3:
        return responses.failure(
            message="Password must contain more than 3 unique characters.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if args.password.lower() in app.settings.DISALLOWED_PASSWORDS:
        return responses.failure(
            message="That password was deemed too simple.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    ip = app.state.services.ip_resolver.get_ip(request.headers)
    geoloc = await app.state.services.fetch_geoloc(ip, request.headers)

    pw_md5 = hashlib.md5(args.password.encode()).hexdigest().encode()
    pw_bcrypt = bcrypt.hashpw(pw_md5, bcrypt.gensalt())

    country = geoloc["country"]["acronym"] if geoloc is not None else "xx"

    if country != "pe":
        return responses.failure(
            message="Registration is only available to Peruvian players.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    user = await users_repo.create(
        name=args.username,
        email=args.email,
        pw_bcrypt=pw_bcrypt,
        country=country,
    )

    await stats_repo.create_all_modes(player_id=user["id"])

    auth_response = await authentication.authenticate(
        username=args.username,
        password=args.password,
    )

    if auth_response is None:
        return responses.failure(
            message="Failed to authenticate after registration.",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    http_response = JSONResponse(
        content=auth_response.identity.model_dump(),
        status_code=status.HTTP_201_CREATED,
    )
    http_response.set_cookie(
        "X-Bpy-Token",
        value=auth_response.unhashed_access_token,
        expires=60 * 60 * 24 * 30,
        secure=True,
        httponly=True,
        samesite="none",
    )

    return http_response
