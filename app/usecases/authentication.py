from __future__ import annotations

import hashlib
import secrets
from datetime import datetime

import bcrypt
from fastapi import status
from pydantic import BaseModel

from app.api.v2.common import responses
from app.api.v2.common.responses import Failure
from app.constants.privileges import Privileges
from app.repositories import tokens
from app.repositories import users
from app.repositories.tokens import Token


class Identity(BaseModel):
    user_id: int
    username: str
    privileges: Privileges


class AuthorizationGrant(BaseModel):
    unhashed_access_token: str
    identity: Identity
    privileges: Privileges
    expires_at: datetime | None


async def authenticate(
    username: str,
    password: str,
) -> AuthorizationGrant | None:
    user = await users.fetch_one(
        name=username,
        fetch_all_fields=True,
    )
    if user is None:
        return None

    pw_bcrypt = user["pw_bcrypt"].encode()
    pw_md5 = hashlib.md5(password.encode()).hexdigest().encode()

    if not bcrypt.checkpw(pw_md5, pw_bcrypt):
        return None

    unhashed_access_token = secrets.token_urlsafe(nbytes=32)
    hashed_access_token = hashlib.md5(
        unhashed_access_token.encode(),
        usedforsecurity=False,
    ).hexdigest()
    access_token = await tokens.create(
        user_id=user["id"],
        hashed_access_token=hashed_access_token,
    )

    return AuthorizationGrant(
        unhashed_access_token=unhashed_access_token,
        privileges=Privileges(access_token["priv"]),
        expires_at=None,
        identity=Identity(
            user_id=user["id"],
            username=user["name"],
            privileges=Privileges(user["priv"]),
        ),
    )


async def logout(trusted_access_token: Token) -> None:
    await tokens.delete_one(trusted_access_token["token"])

    return None
