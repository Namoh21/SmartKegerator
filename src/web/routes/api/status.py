from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from web.server import get_db

router = APIRouter()


class StatusResponse(BaseModel):
    ambient_temp_f:   Optional[float]
    humidity_pct:     Optional[float]
    temp_ts:          Optional[float]   # unix timestamp of last reading
    current_user_id:  Optional[int]     # user currently at the keg (None if none/unknown)
    current_user_name: Optional[str]


@router.get("/status", response_model=StatusResponse)
async def get_status():
    """Current sensor readings, temperature, humidity, and who is at the keg."""
    db = get_db()

    def _f(key: str) -> Optional[float]:
        v = db.get_setting(key, "")
        try:
            return float(v) if v else None
        except ValueError:
            return None

    # The Qt app writes the currently-recognised user id into the DB
    from data.models import UNKNOWN_USER_ID
    current_user_id   = None
    current_user_name = None
    raw_uid = db.get_setting("current_user_id", "")
    if raw_uid:
        try:
            uid = int(raw_uid)
            if uid != UNKNOWN_USER_ID:
                user = db.get_user(uid)
                if user:
                    current_user_id   = uid
                    current_user_name = user.name
        except ValueError:
            pass

    return StatusResponse(
        ambient_temp_f    = _f("latest_ambient_temp_f"),
        humidity_pct      = _f("latest_humidity_pct"),
        temp_ts           = _f("latest_temp_ts"),
        current_user_id   = current_user_id,
        current_user_name = current_user_name,
    )
