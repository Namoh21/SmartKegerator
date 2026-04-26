from __future__ import annotations

import time
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from web.server import get_db, get_config, templates, ctx
from web.helpers import keg_stats

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    db     = get_db()
    taps   = db.get_tap_assignments()
    config = get_config()

    tap_map = {
        "left":   taps.left_keg_id,
        "center": taps.center_keg_id,
        "right":  taps.right_keg_id,
    }

    tap_stats = []
    for tap_name, keg_id in tap_map.items():
        if keg_id is not None:
            keg = db.get_keg(keg_id)
            if keg:
                tap_stats.append(keg_stats(db, keg, tap=tap_name))
            else:
                tap_stats.append(None)
        else:
            tap_stats.append(None)

    # Recent pours (last 20)
    all_pours = db.get_pours_since(time.time() - 30 * 86400)
    recent    = sorted(all_pours, key=lambda p: p.time, reverse=True)[:20]

    # Enrich pours with names
    users = {u.id: u.name for u in db.get_all_users()}
    keg_beer_cache: dict[int, str] = {}
    def beer_for_keg(keg_id: int) -> str:
        if keg_id not in keg_beer_cache:
            keg = db.get_keg(keg_id)
            beer = db.get_beer(keg.beer_id) if keg else None
            keg_beer_cache[keg_id] = beer.name if beer else "Unknown"
        return keg_beer_cache[keg_id]

    enriched_pours = [
        {
            "pour":      p,
            "user_name": users.get(p.user_id, "Unknown"),
            "beer_name": beer_for_keg(p.keg_id),
        }
        for p in recent
    ]

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        ctx(
            request,
            tap_stats=tap_stats,
            tap_names=["LEFT", "CENTER", "RIGHT"],
            enriched_pours=enriched_pours,
        ),
    )


@router.get("/api/tap-levels", response_class=HTMLResponse)
async def tap_levels_partial(request: Request):
    """HTMX polling endpoint — returns just the 3 level bars."""
    db   = get_db()
    taps = db.get_tap_assignments()
    tap_map = {
        "left":   taps.left_keg_id,
        "center": taps.center_keg_id,
        "right":  taps.right_keg_id,
    }
    stats = []
    for tap_name, keg_id in tap_map.items():
        keg = db.get_keg(keg_id) if keg_id else None
        stats.append(keg_stats(db, keg, tap=tap_name) if keg else None)

    return templates.TemplateResponse(
        request,
        "partials/tap_levels.html",
        ctx(request, tap_stats=stats, tap_names=["LEFT", "CENTER", "RIGHT"]),
    )
