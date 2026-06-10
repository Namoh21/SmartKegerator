from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from web.api_auth import create_token, require_admin
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
async def get_app_config():
    """Return site-level settings the Android app needs at startup."""
    import socket
    cfg  = get_config()
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
