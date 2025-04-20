from __future__ import annotations

from enum import StrEnum
from typing import TypedDict
from typing import cast

from sqlalchemy import Column
from sqlalchemy import Enum
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import func
from sqlalchemy import select

import app.state.services
from app.repositories import Base
from app.repositories import users as users_repo
from app.repositories.users import User


class RelationshipType(StrEnum):
    FRIEND = "friend"
    BLOCK = "block"


class RelationshipsTable(Base):
    __tablename__ = "relationships"

    user1 = Column(Integer, nullable=False, primary_key=True)
    user2 = Column(Integer, nullable=False, primary_key=True)
    type = Column(Enum(RelationshipType, name="type"), nullable=False)


READ_PARAMS = (
    RelationshipsTable.user1,
    RelationshipsTable.user2,
    RelationshipsTable.type,
)


class Relationship(TypedDict):
    user1: int
    user2: int
    type: RelationshipType


async def fetch_friends(
    user_id: int,
    page: int | None = None,
    page_size: int | None = None,
) -> list[User]:
    select_stmt = (
        select(READ_PARAMS)
        .where(RelationshipsTable.user1 == user_id)
        .where(RelationshipsTable.type == RelationshipType.FRIEND)
    )

    if page is not None and page_size is not None:
        select_stmt = select_stmt.limit(page_size).offset((page - 1) * page_size)

    relationships = await app.state.services.database.fetch_all(select_stmt)

    users = []
    for relationship in relationships:
        user = await users_repo.fetch_one(id=relationship["user2"])
        if user is not None:
            users.append(user)

    return users


async def fetch_friends_count(
    user_id: int,
) -> int:
    select_stmt = (
        select(func.count().label("count"))
        .where(RelationshipsTable.user1 == user_id)
        .where(RelationshipsTable.type == RelationshipType.FRIEND)
    )

    rec = await app.state.services.database.fetch_one(select_stmt)
    assert rec is not None
    return cast(int, rec["count"])
