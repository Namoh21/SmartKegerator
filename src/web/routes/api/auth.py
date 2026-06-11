from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel

from web.api_auth import _bearer, create_token, require_admin
from web.auth import verify_password
from web.server import get_config, get_db

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    token:      str
    token_type: str = "Bearer"
    expires_at: int
    username:   str


class ConfigResponse(BaseModel):
    site_name:   str
    theme:       str
    server_url:  str   # http://{lan_ip}:{port} — for Android setup screen display


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/auth/login", response_model=TokenResponse)
async def login(body: LoginRequest):
    """Exchange admin credentials for a Bearer token."""
    db    = get_db()
    admin = db.get_admin_by_username(body.username.strip())
    if not admin or not verify_password(body.password, admin["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid username or password")
    token, expires_at = create_token(admin["id"], admin["username"], admin["password_hash"])
    return TokenResponse(token=token, expires_at=expires_at, username=admin["username"])


@router.get("/auth/me")
async def me(payload: dict = Depends(require_admin)):
    """Return the identity of the currently authenticated admin."""
    return {"username": payload["sub"], "admin_id": payload["admin_id"]}


@router.get("/config", response_model=ConfigResponse)
async def get_app_config(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
):
    """Return site-level settings the Android app needs at startup.

    Public by default for app discovery on the LAN. When the owner enables
    web.require_login_for_read (privacy mode / tunnel exposure), a valid
    admin token is required — same revocation checks as every other endpoint.
    """
    cfg = get_config()
    if cfg.get("web", {}).get("require_login_for_read"):
        await require_admin(creds)
    import socket
    ui   = cfg.get("ui",  {})
    port = int(cfg.get("web", {}).get("port", 8080))
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        ip = "localhost"
    return ConfigResponse(
        site_name  = ui.get("name",  "SmartKegerator"),
        theme      = ui.get("theme", "dark_blue"),
        server_url = f"http://{ip}:{port}",
    )
