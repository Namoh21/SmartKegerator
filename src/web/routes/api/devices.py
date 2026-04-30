"""
Device token registration endpoints for the mobile app.

A registered token is stored in the device_tokens table and used to send
FCM push notifications when a pour is detected.  Tokens are scoped to
admin sessions — only authenticated admins can register devices.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from web.api_auth import require_admin
from web.server import get_db

router = APIRouter()


class RegisterRequest(BaseModel):
    token:    str
    platform: str = "android"
    label:    str = ""          # optional human-readable label (e.g. "Alice's phone")


@router.post("/devices/register", dependencies=[Depends(require_admin)])
async def register_device(body: RegisterRequest):
    """Store an FCM device token so the server can push pour notifications."""
    token = body.token.strip()
    if not token:
        return {"ok": False, "error": "token is required"}
    get_db().add_device_token(token, body.platform, body.label)
    return {"ok": True}


@router.delete("/devices/unregister", dependencies=[Depends(require_admin)])
async def unregister_device(body: RegisterRequest):
    """Remove a device token — disables push notifications for that device."""
    get_db().remove_device_token(body.token.strip())
    return {"ok": True}


@router.get("/devices", dependencies=[Depends(require_admin)])
async def list_devices():
    """Return all registered device tokens (admin only)."""
    return {"tokens": get_db().get_device_tokens()}
