from __future__ import annotations

import secrets
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from .config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"


def google_oauth_configured() -> bool:
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)


def new_state_token() -> str:
    """CSRF-protection value for the OAuth redirect round-trip. The caller
    (api.py) is responsible for storing/verifying it (e.g. a short-lived
    signed cookie) — this module only generates it."""
    return secrets.token_urlsafe(24)


def build_authorization_url(state: str) -> str:
    if not google_oauth_configured():
        raise HTTPException(503, "Google OAuth is not configured on this server")
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return f"{GOOGLE_AUTH_ENDPOINT}?{urlencode(params)}"


def exchange_code_for_id_token(code: str) -> str:
    """Exchanges an authorization `code` for tokens at Google's token
    endpoint and returns the raw `id_token` JWT (still unverified at this
    point — verify_id_token() below checks its signature)."""
    response = httpx.post(
        GOOGLE_TOKEN_ENDPOINT,
        data={
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        },
        timeout=10.0,
    )
    if response.status_code != 200:
        raise HTTPException(401, "Google token exchange failed")
    body = response.json()
    id_token_jwt = body.get("id_token")
    if not id_token_jwt:
        raise HTTPException(401, "Google did not return an id_token")
    return id_token_jwt


def verify_id_token(id_token_jwt: str) -> dict[str, Any]:
    """Verifies the id_token's signature against Google's published public
    keys (fetched/cached internally by the google-auth library) and its
    audience/issuer claims. Raises 401 on any failure rather than trusting
    unverified claims."""
    try:
        claims = google_id_token.verify_oauth2_token(
            id_token_jwt, google_requests.Request(), audience=GOOGLE_CLIENT_ID
        )
    except ValueError as error:
        raise HTTPException(401, "Invalid Google id_token") from error
    if not claims.get("email_verified", False):
        raise HTTPException(401, "Google account email is not verified")
    return claims
