from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from web.server import get_db

router = APIRouter()


class StatusResponse(BaseModel):
    liquid_temp_f:  Optional[float]
    ambient_temp_f: Optional[float]
    humidity_pct:   Optional[float]
    temp_ts:        Optional[float]   # unix timestamp of last reading


@router.get("/status", response_model=StatusResponse)
async def get_status():
    """Current sensor readings — temperature and humidity."""
    db = get_db()

    def _f(key: str) -> Optional[float]:
        v = db.get_setting(key, "")
        try:
            return float(v) if v else None
        except ValueError:
            return None

    return StatusResponse(
        liquid_temp_f  = _f("latest_liquid_temp_f"),
        ambient_temp_f = _f("latest_ambient_temp_f"),
        humidity_pct   = _f("latest_humidity_pct"),
        temp_ts        = _f("latest_temp_ts"),
    )
