from __future__ import annotations

from . import BaseModel


class AuthenticationRequest(BaseModel):
    username: str
    password: str
