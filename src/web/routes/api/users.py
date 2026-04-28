from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from data.models import UNKNOWN_USER_ID, User
from web.api_auth import require_admin
from web.server import get_db

router = APIRouter()


class UserResponse(BaseModel):
    id:          int
    name:        str
    photo_count: int
    balance:     float


class UserRequest(BaseModel):
    name: str


@router.get("/users", response_model=list[UserResponse])
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
