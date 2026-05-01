from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from data.models import Keg
from web.api_auth import require_admin
from web.server import get_db

router = APIRouter()


class KegResponse(BaseModel):
    id:               int
    beer_id:          int
    beer_name:        str
    date_bought:      str
    liters_capacity:  float
    liters_remaining: float
    pct_remaining:    float
    price:            float
    price_per_pint:   Optional[float]


class KegRequest(BaseModel):
    beer_id:      int
    capacity:     float
    price:        float
    date_bought:  str   = ""
    warmest_temp: float = 0.0


def _out(db, keg: Keg) -> KegResponse:
    beer = db.get_beer(keg.beer_id)
    return KegResponse(
        id               = keg.id,
        beer_id          = keg.beer_id,
        beer_name        = beer.name if beer else "Unknown",
        date_bought      = keg.date_bought.strftime("%Y-%m-%d"),
        liters_capacity  = keg.liters_capacity,
        liters_remaining = keg.liters_remaining,
        pct_remaining    = keg.percent_remaining,
        price            = keg.price,
        price_per_pint   = keg.price_for_ounces(16.0),
    )


def _parse_date(s: str) -> datetime:
    try:
        return datetime.strptime(s, "%Y-%m-%d") if s else datetime.today()
    except ValueError:
        return datetime.today()


@router.get("/kegs", response_model=list[KegResponse], dependencies=[Depends(require_admin)])
async def list_kegs():
    db = get_db()
    return [_out(db, k) for k in db.get_all_kegs()]


@router.post("/kegs", response_model=KegResponse, dependencies=[Depends(require_admin)])
async def add_keg(body: KegRequest):
    db  = get_db()
    keg = Keg(
        id=None, beer_id=body.beer_id, date_bought=_parse_date(body.date_bought),
        liters_capacity=body.capacity, price=body.price, warmest_temp=body.warmest_temp,
    )
    db.save_keg(keg)
    return _out(db, keg)


@router.put("/kegs/{keg_id}", response_model=KegResponse, dependencies=[Depends(require_admin)])
async def update_keg(keg_id: int, body: KegRequest):
    db  = get_db()
    keg = db.get_keg(keg_id)
    if not keg:
        raise HTTPException(404, "Keg not found")
    keg.beer_id         = body.beer_id
    keg.liters_capacity = body.capacity
    keg.price           = body.price
    keg.warmest_temp    = body.warmest_temp
    keg.date_bought     = _parse_date(body.date_bought) if body.date_bought else keg.date_bought
    db.save_keg(keg)
    return _out(db, keg)


@router.delete("/kegs/{keg_id}", dependencies=[Depends(require_admin)])
async def delete_keg(keg_id: int):
    db = get_db()
    if not db.get_keg(keg_id):
        raise HTTPException(404, "Keg not found")
    db.delete_keg(keg_id)
    return {"ok": True}
