from __future__ import annotations

from datetime import datetime
from typing import TypedDict
from typing import cast

from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import delete
from sqlalchemy import func
from sqlalchemy import insert
from sqlalchemy import select

import app.state.services
from app.repositories import Base
from app.repositories.logs import READ_PARAMS


class PasswordResetTokensTable(Base):
    __tablename__ = "password_reset_tokens"

    id = Column("id", Integer, nullable=False, primary_key=True, autoincrement=True)
    hashed_token = Column("hashed_token", String(80), nullable=False)
    username = Column("username", String(30), nullable=False)
    created_at = Column("created_at", DateTime, nullable=False)

    __table_args__ = (Index("password_reset_tokens_hashed_token_uindex", hashed_token),)


READ_PARAMS = (
    PasswordResetTokensTable.id,
    PasswordResetTokensTable.hashed_token,
    PasswordResetTokensTable.username,
    PasswordResetTokensTable.created_at,
)


class PasswordResetToken(TypedDict):
    id: int
    hashed_token: str
    username: str
    created_at: datetime


async def create(
    username: str,
    hashed_token: str,
) -> PasswordResetToken:
    """Create a new password reset token in the database."""
    insert_stmt = insert(PasswordResetTokensTable).values(
        username=username,
        hashed_token=hashed_token,
        created_at=func.now(),
    )
    rec_id = await app.state.services.database.execute(insert_stmt)

    select_stmt = select(*READ_PARAMS).where(PasswordResetTokensTable.id == rec_id)
    token = await app.state.services.database.fetch_one(select_stmt)
    assert token is not None
    return cast(PasswordResetToken, token)


async def fetch_one(
    hashed_token: str,
) -> PasswordResetToken | None:
    """Fetch a password reset token from the database."""
    select_stmt = select(*READ_PARAMS).where(
        PasswordResetTokensTable.hashed_token == hashed_token,
    )
    token = await app.state.services.database.fetch_one(select_stmt)
    return cast(PasswordResetToken | None, token)


async def delete_one(
    hashed_token: str,
) -> PasswordResetToken | None:
    """Delete a password reset token from the database."""
    select_stmt = select(*READ_PARAMS).where(
        PasswordResetTokensTable.hashed_token == hashed_token,
    )
    token = await app.state.services.database.fetch_one(select_stmt)
    if token is None:
        return None

    delete_stmt = delete(PasswordResetTokensTable).where(
        PasswordResetTokensTable.hashed_token == hashed_token,
    )
    await app.state.services.database.execute(delete_stmt)

    return cast(PasswordResetToken, token)
