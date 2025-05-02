from __future__ import annotations

from . import BaseModel


class AuthenticationRequest(BaseModel):
    username: str
    password: str
    hcaptcha_token: str


class RegistrationRequest(BaseModel):
    username: str
    email: str
    password: str
    hcaptcha_token: str
