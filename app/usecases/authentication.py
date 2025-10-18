from __future__ import annotations

import hashlib
import secrets
from datetime import datetime

import bcrypt
from pydantic import BaseModel

import app.settings
from app.adapters import smtp
from app.constants.privileges import Privileges
from app.logging import Ansi
from app.logging import log
from app.repositories import password_reset_tokens as password_reset_tokens_repo
from app.repositories import tokens as tokens_repo
from app.repositories import users as users_repo
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
    user = await users_repo.fetch_one(
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
    access_token = await tokens_repo.create(
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


async def initialize_password_reset(username: str):
    user = await users_repo.fetch_one(name=username)
    if user is None:
        log(f"Password reset requested for non-existent user {username}", Ansi.LYELLOW)
        return False

    unhashed_password_reset_token = secrets.token_urlsafe(nbytes=32)
    hashed_password_reset_token = hashlib.md5(
        unhashed_password_reset_token.encode(),
        usedforsecurity=False,
    ).hexdigest()
    password_reset_token = await password_reset_tokens_repo.create(
        username=user["name"],
        hashed_token=hashed_password_reset_token,
    )

    log(f"User {username} initiated password reset process", Ansi.LCYAN)

    response = await smtp.send_html_email(
        to_address=user["email"],
        subject="Restablecimiento de contraseña de osu!Peru",
        body=(
            f"Hola {user['name']},<br /><br />"
            "Alguien (<i>que realmente esperamos que hayas sido tú</i>), solicitó un restablecimiento de contraseña "
            "para tu cuenta de osu!Peru.<br /><br />"
            f"En caso de que hayas sido tú, por favor <a href='https://{app.settings.DOMAIN}/reset-password?token={password_reset_token['hashed_token']}'>haz clic aquí</a> "
            "para restablecer tu contraseña en osu!Peru, de lo contrario, ignora este correo electrónico.<br /><br />"
            "- El equipo de osu!Peru"
        ),
    )
    if not response:
        log(f"Failed to send password reset email to {user['email']}", Ansi.LRED)
        return False

    return True


async def verify_password_reset(hashed_password_reset_token: str, new_password: str):

    password_reset_token = await password_reset_tokens_repo.fetch_one(
        hashed_token=hashed_password_reset_token,
    )
    if password_reset_token is None:
        return False

    user = await users_repo.fetch_one(name=password_reset_token["username"])
    if user is None:
        return False

    pw_bcrypt = bcrypt.hashpw(
        hashlib.md5(new_password.encode()).hexdigest().encode(),
        bcrypt.gensalt(),
    )

    await users_repo.partial_update(
        id=user["id"],
        pw_bcrypt=pw_bcrypt,
    )
    await password_reset_tokens_repo.delete_one(
        hashed_token=password_reset_token["hashed_token"],
    )

    log(f"User {user['name']} has successfully reset their password", Ansi.LCYAN)

    return True


async def logout(trusted_access_token: Token) -> None:
    await tokens_repo.delete_one(trusted_access_token["token"])

    return None
