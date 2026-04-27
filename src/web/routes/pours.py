from __future__ import annotations

import time
from datetime import datetime

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from web.server import get_db, templates, ctx

router = APIRouter(prefix="/pours")

_PERIODS = {"7d": 7, "30d": 30, "90d": 90, "all": None}


@router.get("/", response_class=HTMLResponse)
async def pour_history(
    request:   Request,
    user_id:   int = Query(default=0),   # 0 = all users
    period:    str = Query(default="30d"),
    keg_id:    int = Query(default=0),   # 0 = all kegs
):
    db    = get_db()
    days  = _PERIODS.get(period, 30)
    since = (time.time() - days * 86400) if days else 0.0

    pours = db.get_pours_since(since)

    if user_id:
        pours = [p for p in pours if p.user_id == user_id]
    if keg_id:
        pours = [p for p in pours if p.keg_id == keg_id]

    pours = sorted(pours, key=lambda p: p.time, reverse=True)

    # Build lookup caches
    users = {u.id: u.name for u in db.get_all_users()}
    keg_beer: dict[int, str] = {}
    def beer_for_keg(kid: int) -> str:
        if kid not in keg_beer:
            keg  = db.get_keg(kid)
            beer = db.get_beer(keg.beer_id) if keg else None
            keg_beer[kid] = beer.name if beer else "Unknown"
        return keg_beer[kid]

    enriched = [
        {
            "pour":      p,
            "user_name": users.get(p.user_id, "Unknown"),
            "beer_name": beer_for_keg(p.keg_id),
        }
        for p in pours
    ]

    # Summary stats
    total_oz    = sum(p.ounces for p in pours)
    total_price = sum(p.price  for p in pours)

    # Chart data: oz poured per day (last 30 days max)
    chart_days   = min(days or 30, 30)
    now_dt       = datetime.now()
    day_labels   = [(now_dt - __import__("datetime").timedelta(days=i)).strftime("%b %d")
                    for i in range(chart_days - 1, -1, -1)]
    day_buckets: dict[int, float] = {}
    for p in pours:
        age = int((time.time() - p.time) / 86400)
        if age < chart_days:
            idx = chart_days - 1 - age
            day_buckets[idx] = day_buckets.get(idx, 0.0) + p.ounces
    day_oz = [round(day_buckets.get(i, 0.0), 1) for i in range(chart_days)]

    return templates.TemplateResponse(
        request,
        "pours.html",
        ctx(
            request,
            enriched_pours=enriched,
            all_users=db.get_all_users(),
            all_kegs=db.get_all_kegs(),
            selected_user=user_id,
            selected_keg=keg_id,
            selected_period=period,
            total_oz=total_oz,
            total_price=total_price,
            pour_count=len(pours),
            chart_labels=day_labels,
            chart_oz=day_oz,
            show_user_filter=True,
        ),
    )
