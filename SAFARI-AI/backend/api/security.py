"""Admin access.

Admins sign in with SAFARI_ADMIN_USERNAME and SAFARI_ADMIN_PASSWORD and receive a signed session
token that expires after SAFARI_ADMIN_SESSION_HOURS. Scripts may still send SAFARI_ADMIN_TOKEN.
Requests carry either one in the X-Admin-Token header. With neither a password nor a token
configured, admin is open to this machine only.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import time

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from services.common.settings import Settings, load_settings

LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}
SESSION_PREFIX = "s1"
FAILED_LOGIN_DELAY_S = 1.0


def login_enabled(settings: Settings) -> bool:
    return bool(settings.admin_username and settings.admin_password)


def auth_required(settings: Settings) -> bool:
    return login_enabled(settings) or bool(settings.admin_token)


def _signing_key(settings: Settings) -> bytes:
    # Without an explicit secret the key follows the credentials, so changing the password signs everyone out.
    material = settings.secret_key or f"{settings.admin_username}\0{settings.admin_password}\0{settings.admin_token}"
    return hashlib.sha256(f"safari-admin-session\0{material}".encode()).digest()


def _sign(settings: Settings, payload: str) -> str:
    digest = hmac.new(_signing_key(settings), payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def issue_session(settings: Settings, now: float | None = None) -> tuple[str, int]:
    expires = int((now or time.time()) + settings.admin_session_hours * 3600)
    user = base64.urlsafe_b64encode(settings.admin_username.encode()).decode().rstrip("=")
    payload = f"{SESSION_PREFIX}.{user}.{expires}"
    return f"{payload}.{_sign(settings, payload)}", expires


def valid_session(settings: Settings, token: str, now: float | None = None) -> bool:
    if not login_enabled(settings):
        return False
    parts = token.split(".")
    if len(parts) != 4 or parts[0] != SESSION_PREFIX:
        return False
    payload = ".".join(parts[:3])
    if not hmac.compare_digest(parts[3], _sign(settings, payload)):
        return False
    try:
        user = base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)).decode()
        expires = int(parts[2])
    except ValueError:
        return False
    return user == settings.admin_username and expires > (now or time.time())


def check_admin(request: Request, token: str | None) -> None:
    settings = load_settings()
    if auth_required(settings):
        if token and valid_session(settings, token):
            return
        if token and settings.admin_token and hmac.compare_digest(token, settings.admin_token):
            return
        raise HTTPException(status_code=401, detail="Sign in to continue" if token is None else "Your session has expired. Sign in again.")
    host = request.client.host if request.client else ""
    if host not in LOCAL_HOSTS:
        raise HTTPException(status_code=401, detail="Set SAFARI_ADMIN_USERNAME and SAFARI_ADMIN_PASSWORD to use admin remotely")


def require_admin(request: Request, x_admin_token: str | None = Header(default=None)) -> None:
    """FastAPI dependency form of `check_admin`."""
    check_admin(request, x_admin_token)


class Credentials(BaseModel):
    username: str = ""
    password: str = ""


login_router = APIRouter()


@login_router.post("/v1/admin/login")
async def login(credentials: Credentials) -> dict:
    settings = load_settings()
    if not login_enabled(settings):
        raise HTTPException(status_code=503, detail="Admin login is not configured. Set SAFARI_ADMIN_USERNAME and SAFARI_ADMIN_PASSWORD.")
    # Compare both fields every time so a wrong username takes as long as a wrong password.
    user_ok = hmac.compare_digest(credentials.username.strip().encode(), settings.admin_username.encode())
    password_ok = hmac.compare_digest(credentials.password.encode(), settings.admin_password.encode())
    if not (user_ok and password_ok):
        await asyncio.sleep(FAILED_LOGIN_DELAY_S)
        raise HTTPException(status_code=401, detail="Wrong username or password")
    token, expires = issue_session(settings)
    return {"token": token, "expires": expires, "username": settings.admin_username}
