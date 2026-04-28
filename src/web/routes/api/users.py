from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from data.models import UNKNOWN_USER_ID
from web.server import get_db

router = APIRouter()


class UserResponse(BaseModel):
    id:          int
    name:        str
    photo_count: int
    balance:     float


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
