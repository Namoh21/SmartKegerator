"""
JWT authentication for the mobile REST API (/api/v1/).

Admins authenticate with POST /api/v1/auth/login and receive a Bearer
token.  All write endpoints require that token; most read endpoints require
admin auth as well (GET /api/v1/config is public for app discovery).
"""
from __future__ import annotations

import time
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_ALGORITHM  = "HS256"
_TOKEN_DAYS = 30          # tokens live 30 days; revoked when the admin's password changes

_bearer = HTTPBearer(auto_error=False)


def _secret() -> str:
    from web.server import _SESSION_SECRET  # noqa: PLC0415
    return _SESSION_SECRET


def create_token(admin_id: int, username: str, password_hash: str) -> tuple[str, int]:
    """Return (signed_token, expires_at_unix_ts).

    The token carries a fingerprint of the admin's password hash so it
    becomes invalid as soon as the password changes or the admin is deleted.
    """
    from web.auth import credential_fingerprint  # noqa: PLC0415
    now     = int(time.time())
    expires = now + _TOKEN_DAYS * 86400
    payload = {
        "sub":      username,
        "admin_id": admin_id,
        "pwd":      credential_fingerprint(password_hash),
        "iat":      now,
        "exp":      expires,
    }
    return jwt.encode(payload, _secret(), algorithm=_ALGORITHM), expires


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, _secret(), algorithms=[_ALGORITHM])
    except jwt.PyJWTError:
        return None


async def require_admin(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    """FastAPI dependency — raises HTTP 401 when no valid admin token is present."""
    if not creds:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(creds.credentials)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # The signature alone is not enough: the admin must still exist and the
    # token's password fingerprint must match the current password hash, so
    # deleting an admin or changing the password revokes outstanding tokens.
    from web.auth import credential_fingerprint  # noqa: PLC0415
    from web.server import get_db               # noqa: PLC0415
    admin = get_db().get_admin_by_id(payload.get("admin_id", -1))
    if not admin or payload.get("pwd") != credential_fingerprint(admin["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token revoked — log in again",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload
