from __future__ import annotations

from typing import TypedDict
from typing import cast

from sqlalchemy import Column
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import delete
from sqlalchemy import insert
from sqlalchemy import select

import app.state.services
from app.repositories import Base


# TODO: Rename to access_tokens.py
class TokensTable(Base):
    __tablename__ = "tokens"

    id = Column("id", Integer, nullable=False, primary_key=True, autoincrement=True)
    userid = Column("userid", Integer, nullable=False)
    priv = Column("priv", Integer, nullable=False, default="1")
    description = Column("description", String(64), nullable=False)
    token = Column("token", String(32), nullable=False)
    private = Column("private", Integer, nullable=False)

    __table_args__ = (Index("tokens_token_uindex", token),)


READ_PARAMS = (
    TokensTable.id,
    TokensTable.userid,
    TokensTable.priv,
    TokensTable.description,
    TokensTable.token,
    TokensTable.private,
)


class Token(TypedDict):
    id: int
    userid: int
    priv: int
    description: str
    token: str
    private: bool


async def create(
    user_id: int,
    hashed_access_token: str,
) -> Token:
    """Create a new token in the database."""
    insert_stmt = insert(TokensTable).values(
        userid=user_id,
        priv=0,
        description="Access token",
        token=hashed_access_token,
        private=True,
    )
    rec_id = await app.state.services.database.execute(insert_stmt)

    select_stmt = select(*READ_PARAMS).where(TokensTable.id == rec_id)
    token = await app.state.services.database.fetch_one(select_stmt)
    assert token is not None
    return cast(Token, token)


async def fetch_one(hashed_access_token: str) -> Token | None:
    """Fetch a token entry from the database."""
    select_stmt = select(*READ_PARAMS).where(TokensTable.token == hashed_access_token)
    token = await app.state.services.database.fetch_one(select_stmt)
    return cast(Token | None, token)


async def delete_one(hashed_access_token: str) -> Token | None:
    """Delete an existing achievement."""
    select_stmt = select(*READ_PARAMS).where(TokensTable.token == hashed_access_token)
    token = await app.state.services.database.fetch_one(select_stmt)
    if token is None:
        return None

    delete_stmt = delete(TokensTable).where(TokensTable.token == hashed_access_token)
    await app.state.services.database.execute(delete_stmt)

    return cast(Token, token)
