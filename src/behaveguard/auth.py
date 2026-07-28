from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request

from .config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    JWT_ALGORITHM,
    JWT_SECRET_KEY,
    REFRESH_TOKEN_EXPIRE_DAYS,
)

# --- Password hashing (bcrypt) ---------------------------------------------


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        # Malformed/foreign hash (e.g. an OAuth-only account with no
        # password_hash reaching this by mistake) — treat as "doesn't match"
        # rather than raising, so callers don't need a separate code path.
        return False


# --- Access tokens (JWT) ----------------------------------------------------


def create_access_token(user_id: str, role: str, org_id: str | None) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "role": role,
        "org_id": org_id,
        "iat": now,
        "exp": now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
        "type": "access",
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as error:
        raise HTTPException(401, "Access token expired") from error
    except jwt.InvalidTokenError as error:
        raise HTTPException(401, "Invalid access token") from error
    if payload.get("type") != "access":
        raise HTTPException(401, "Invalid token type")
    return payload


# --- Refresh tokens (opaque, hashed at rest) --------------------------------


def new_refresh_token() -> tuple[str, str, datetime]:
    """Returns (raw_token, sha256_hex_hash, expires_at).

    The raw token is handed to the client and never stored; only its hash is
    persisted (see db.models.RefreshToken), so a database leak alone can't be
    replayed as a live session.
    """
    import hashlib

    raw = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    expires_at = datetime.now(UTC) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    return raw, token_hash, expires_at


def hash_refresh_token(raw: str) -> str:
    import hashlib

    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# --- FastAPI dependencies ----------------------------------------------------


class CurrentUser:
    __slots__ = ("id", "role", "org_id")

    def __init__(self, user_id: str, role: str, org_id: str | None) -> None:
        self.id = user_id
        self.role = role
        self.org_id = org_id

    @property
    def is_admin(self) -> bool:
        return self.role in ("org_admin", "platform_admin")

    @property
    def is_platform_admin(self) -> bool:
        return self.role == "platform_admin"


def get_current_user(request: Request) -> CurrentUser:
    from .database import get_user  # local import avoids a circular import with database.py

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "Missing or malformed Authorization header")
    token = auth_header.removeprefix("Bearer ").strip()
    payload = decode_access_token(token)
    try:
        user = get_user(payload["sub"])
    except KeyError as error:
        raise HTTPException(401, "User no longer exists") from error
    if user["status"] != "active":
        raise HTTPException(403, "Account is not active")
    return CurrentUser(user_id=user["id"], role=user["role"], org_id=user["org_id"])


def require_role(*roles: str):
    def _check(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if current_user.role not in roles:
            raise HTTPException(403, f"Requires one of roles: {', '.join(roles)}")
        return current_user

    return _check


require_admin = require_role("org_admin", "platform_admin")
require_platform_admin = require_role("platform_admin")
