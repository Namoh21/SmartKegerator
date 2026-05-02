from __future__ import annotations

import threading
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from data.models import UNKNOWN_USER_ID, User
from web.api_auth import require_admin
from web.server import get_config, get_db

log = logging.getLogger(__name__)

router = APIRouter()


class UserResponse(BaseModel):
    id:          int
    name:        str
    photo_count: int
    balance:     float


class UserRequest(BaseModel):
    name: str


class PaymentRequest(BaseModel):
    amount: float


class TrainStatusResponse(BaseModel):
    status:   str           # "pending" | "done" | "error" | "idle"
    encodings: int | None = None
    error:    str | None  = None


@router.get("/users", response_model=list[UserResponse], dependencies=[Depends(require_admin)])
async def list_users():
    """All registered users with their current balance."""
    db = get_db()
    return [
        UserResponse(
            id          = u.id,
            name        = u.name,
            photo_count = len(u.image_paths),
            balance     = db.balance_for_user(u.id),
        )
        for u in db.get_all_users()
        if u.id != UNKNOWN_USER_ID
    ]


@router.post("/users", response_model=UserResponse, dependencies=[Depends(require_admin)])
async def add_user(body: UserRequest):
    """Register a new drinking user by name.  Admin only."""
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Name is required")
    db   = get_db()
    user = User(id=None, name=name)
    db.save_user(user)
    return UserResponse(id=user.id, name=user.name, photo_count=0, balance=0.0)


@router.delete("/users/{user_id}", dependencies=[Depends(require_admin)])
async def delete_user(user_id: int):
    """Delete a user and all their face encodings.  Admin only."""
    db = get_db()
    if not db.get_user(user_id):
        raise HTTPException(404, "User not found")
    if user_id == UNKNOWN_USER_ID:
        raise HTTPException(400, "Cannot delete the unknown-user placeholder")
    db.delete_face_encodings_for_user(user_id)
    db.delete_user(user_id)
    return {"ok": True}


@router.post("/users/{user_id}/payment", dependencies=[Depends(require_admin)])
async def record_payment(user_id: int, body: PaymentRequest):
    """Record a payment that reduces the user's outstanding balance.  Admin only."""
    db = get_db()
    if not db.get_user(user_id):
        raise HTTPException(404, "User not found")
    if body.amount <= 0:
        raise HTTPException(400, "Amount must be positive")
    db.add_payment(user_id, body.amount)
    return {"ok": True, "balance": db.balance_for_user(user_id)}


@router.post("/users/{user_id}/train", dependencies=[Depends(require_admin)])
async def trigger_training(user_id: int):
    """Start face recognition training for this user in a background thread.  Admin only.
    Poll GET /users/{user_id}/train/status for the result."""
    db   = get_db()
    user = db.get_user(user_id)
    if not user:
        raise HTTPException(404, "User not found")
    if not user.image_paths:
        raise HTTPException(400, "User has no training photos — capture photos first")

    # Guard: reject if already training — prevents simultaneous dlib threads
    # that would OOM-kill the Pi 3 (~400 MB each).
    if db.get_setting(f"train_status_{user_id}", "") == "pending":
        log.warning("train: already in progress for user %d — ignoring duplicate API request", user_id)
        return {"ok": True, "status": "pending"}

    db.set_setting(f"train_status_{user_id}", "pending")

    def _run():
        try:
            from recognition.face_recognizer import train_user_sync
            config = get_config()
            num, err = train_user_sync(db, config, user_id)
            if err:
                db.set_setting(f"train_status_{user_id}", f"error:{err}")
            else:
                db.set_setting(f"train_status_{user_id}", f"done:{num}")
        except Exception as exc:
            log.error("Training thread crashed for user %d: %s", user_id, exc, exc_info=True)
            db.set_setting(f"train_status_{user_id}", f"error:{exc}")

    threading.Thread(target=_run, name=f"train-api-{user_id}", daemon=True).start()
    return {"ok": True, "status": "pending"}


@router.get("/users/{user_id}/train/status", response_model=TrainStatusResponse,
            dependencies=[Depends(require_admin)])
async def training_status(user_id: int):
    """Poll the training status started by POST /users/{user_id}/train."""
    db     = get_db()
    if not db.get_user(user_id):
        raise HTTPException(404, "User not found")
    raw = db.get_setting(f"train_status_{user_id}", "")

    if not raw:
        return TrainStatusResponse(status="idle")
    if raw == "pending":
        return TrainStatusResponse(status="pending")
    if raw.startswith("done:"):
        n = int(raw[5:]) if raw[5:].isdigit() else 0
        db.set_setting(f"train_status_{user_id}", "")
        return TrainStatusResponse(status="done", encodings=n)
    msg = raw[6:] if raw.startswith("error:") else raw
    db.set_setting(f"train_status_{user_id}", "")
    return TrainStatusResponse(status="error", error=msg)
