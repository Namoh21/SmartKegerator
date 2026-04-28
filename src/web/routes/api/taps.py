from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from data.models import get_configured_taps
from web.api_auth import require_admin
from web.server import get_config, get_db

router = APIRouter()


class TapResponse(BaseModel):
    tap_id:           str
    name:             str
    keg_id:           Optional[int]
    beer_name:        Optional[str]
    brewery:          Optional[str]
    style:            Optional[str]
    abv:              Optional[float]
    ibu:              Optional[int]
    label_url:        Optional[str]
    pct_remaining:    float
    liters_remaining: float
    liters_capacity:  float
    price_per_pint:   Optional[float]


class AssignRequest(BaseModel):
    tap_id: str
    keg_id: Optional[int]


@router.get("/taps", response_model=list[TapResponse])
async def list_taps():
    """Current status of every configured tap."""
    db     = get_db()
    config = get_config()
    taps   = db.get_tap_assignments()
    result = []
    for tap_id, display_name in get_configured_taps(config):
        keg_id = taps.get_keg_id(tap_id)
        keg    = db.get_keg(keg_id) if keg_id else None
        beer   = db.get_beer(keg.beer_id) if keg else None
        result.append(TapResponse(
            tap_id           = tap_id,
            name             = display_name,
            keg_id           = keg_id,
            beer_name        = beer.name      if beer else None,
            brewery          = beer.company   if beer else None,
            style            = beer.style     if beer else None,
            abv              = beer.abv       if beer else None,
            ibu              = beer.ibu       if beer else None,
            label_url        = beer.label_url if beer else None,
            pct_remaining    = keg.percent_remaining  if keg else 0.0,
            liters_remaining = keg.liters_remaining   if keg else 0.0,
            liters_capacity  = keg.liters_capacity    if keg else 0.0,
            price_per_pint   = keg.price_for_ounces(16.0) if keg else None,
        ))
    return result


@router.post("/taps/assign", dependencies=[Depends(require_admin)])
async def assign_tap(body: AssignRequest):
    """Assign (or un-assign) a keg to a tap.  Admin only."""
    get_db().set_tap(body.tap_id, body.keg_id)
    return {"ok": True}
