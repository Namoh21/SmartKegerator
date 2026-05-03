from __future__ import annotations

import time

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from data.models import get_configured_taps
from web.server import get_db, get_config, templates, ctx
from web.helpers import keg_stats

router = APIRouter()


def _build_tap_stats(db, taps, config):
    """Return (tap_stats, tap_display_names) based on configured tap count."""
    configured = get_configured_taps(config)
    stats = []
    names = []
    for tap_id, display_name in configured:
        keg_id = taps.get_keg_id(tap_id)
        keg    = db.get_keg(keg_id) if keg_id else None
        stats.append(keg_stats(db, keg, tap=tap_id) if keg else None)
        names.append(display_name.upper())
    return stats, names


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, expired: str = None):
    db     = get_db()
    config = get_config()
    taps   = db.get_tap_assignments()

    tap_stats, tap_names = _build_tap_stats(db, taps, config)

    now         = time.time()
    from datetime import datetime as _dt
    today_start = _dt.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

    all_pours   = db.get_pours_since(now - 30 * 86400)
    today_pours = [p for p in all_pours if p.time >= today_start]
    recent      = sorted(all_pours, key=lambda p: p.time, reverse=True)[:20]

    users          = {u.id: u.name for u in db.get_all_users()}
    keg_beer_cache: dict[int, str] = {}

    def beer_for_keg(keg_id: int) -> str:
        if keg_id not in keg_beer_cache:
            keg  = db.get_keg(keg_id)
            beer = db.get_beer(keg.beer_id) if keg else None
            keg_beer_cache[keg_id] = beer.name if beer else "Unknown"
        return keg_beer_cache[keg_id]

    enriched_pours = [
        {"pour": p, "user_name": users.get(p.user_id, "Unknown"), "beer_name": beer_for_keg(p.keg_id)}
        for p in recent
    ]

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        ctx(request, tap_stats=tap_stats, tap_names=tap_names, enriched_pours=enriched_pours,
            today_count=len(today_pours),
            today_oz=round(sum(p.ounces for p in today_pours), 1),
            today_revenue=sum(p.price for p in today_pours),
            session_expired=bool(expired)),
    )


@router.get("/api/tap-levels", response_class=HTMLResponse)
async def tap_levels_partial(request: Request):
    """HTMX polling endpoint — returns just the tap level bars."""
    db     = get_db()
    config = get_config()
    taps   = db.get_tap_assignments()

    tap_stats, tap_names = _build_tap_stats(db, taps, config)

    return templates.TemplateResponse(
        request,
        "partials/tap_levels.html",
        ctx(request, tap_stats=tap_stats, tap_names=tap_names),
    )
