from __future__ import annotations

import time as _time

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from web.api_auth import require_admin
from web.server import get_db

router = APIRouter()

_PERIODS = {"7d": 7, "30d": 30, "90d": 90, "all": None}


class PourResponse(BaseModel):
    id:        int
    time:      float
    keg_id:    int
    user_id:   int
    user_name: str
    beer_name: str
    ounces:    float
    price:     float


class SummaryResponse(BaseModel):
    count:      int
    total_oz:   float
    total_price: float
    pours:      list[PourResponse]


@router.get("/pours", response_model=SummaryResponse)
async def list_pours(
    period:  str = Query(default="30d"),
    user_id: int = Query(default=0),
    keg_id:  int = Query(default=0),
):
    """Pour history with optional filters. period: 7d | 30d | 90d | all."""
    db    = get_db()
    days  = _PERIODS.get(period, 30)
    since = (_time.time() - days * 86400) if days else 0.0

    pours = db.get_pours_since(since)
    if user_id:
        pours = [p for p in pours if p.user_id == user_id]
    if keg_id:
        pours = [p for p in pours if p.keg_id == keg_id]
    pours = sorted(pours, key=lambda p: p.time, reverse=True)

    users: dict[int, str] = {u.id: u.name for u in db.get_all_users()}
    keg_beer: dict[int, str] = {}

    def beer_for(kid: int) -> str:
        if kid not in keg_beer:
            k = db.get_keg(kid)
            b = db.get_beer(k.beer_id) if k else None
            keg_beer[kid] = b.name if b else "Unknown"
        return keg_beer[kid]

    rows = [
        PourResponse(
            id        = p.id,
            time      = p.time,
            keg_id    = p.keg_id,
            user_id   = p.user_id,
            user_name = users.get(p.user_id, "Unknown"),
            beer_name = beer_for(p.keg_id),
            ounces    = p.ounces,
            price     = p.price,
        )
        for p in pours
    ]

    return SummaryResponse(
        count       = len(rows),
        total_oz    = sum(p.ounces for p in pours),
        total_price = sum(p.price  for p in pours),
        pours       = rows,
    )


@router.delete("/pours/{pour_id}", dependencies=[Depends(require_admin)])
async def delete_pour(pour_id: int):
    """Delete a single pour entry.  Admin only."""
    get_db().delete_pour(pour_id)
    return {"ok": True}
