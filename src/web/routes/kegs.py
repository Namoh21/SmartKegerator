from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from data.models import Keg, get_configured_taps
from web.server import get_db, get_config, templates, ctx
from web.helpers import keg_stats

router = APIRouter(prefix="/kegs")


@router.get("/", response_class=HTMLResponse)
async def keg_list(request: Request):
    db     = get_db()
    config = get_config()
    kegs   = db.get_all_kegs()
    taps   = db.get_tap_assignments()

    # Build keg_id → tap display name for the keg cards
    keg_tap_map: dict[int, str] = {}
    for tap_id, display_name in get_configured_taps(config):
        keg_id = taps.get_keg_id(tap_id)
        if keg_id is not None:
            keg_tap_map[keg_id] = display_name

    stats    = [keg_stats(db, k, tap=keg_tap_map.get(k.id)) for k in kegs]
    beers    = db.get_all_beers()
    all_kegs = db.get_all_kegs()

    return templates.TemplateResponse(
        request,
        "kegs.html",
        ctx(
            request,
            stats=stats,
            beers=beers,
            all_kegs=all_kegs,
            taps=taps,
            configured_taps=get_configured_taps(config),
        ),
    )


@router.post("/add", response_class=RedirectResponse)
async def keg_add(
    beer_id:      int   = Form(...),
    capacity:     float = Form(...),
    price:        float = Form(...),
    date_bought:  str   = Form(""),
    warmest_temp: float = Form(0.0),
):
    db = get_db()
    try:
        date = datetime.strptime(date_bought, "%Y-%m-%d") if date_bought else datetime.today()
    except ValueError:
        date = datetime.today()

    keg = Keg(
        id=None, beer_id=beer_id, date_bought=date,
        liters_capacity=capacity, price=price, warmest_temp=warmest_temp,
    )
    db.save_keg(keg)
    return RedirectResponse("/kegs/", status_code=303)


@router.post("/{keg_id}/edit", response_class=RedirectResponse)
async def keg_edit(
    keg_id:       int,
    beer_id:      int   = Form(...),
    capacity:     float = Form(...),
    price:        float = Form(...),
    date_bought:  str   = Form(""),
    warmest_temp: float = Form(0.0),
):
    db  = get_db()
    keg = db.get_keg(keg_id)
    if keg:
        try:
            keg.date_bought = datetime.strptime(date_bought, "%Y-%m-%d") if date_bought else keg.date_bought
        except ValueError:
            pass
        keg.beer_id        = beer_id
        keg.liters_capacity = capacity
        keg.price          = price
        keg.warmest_temp   = warmest_temp
        db.save_keg(keg)
    return RedirectResponse("/kegs/", status_code=303)


@router.post("/{keg_id}/delete", response_class=RedirectResponse)
async def keg_delete(keg_id: int):
    db = get_db()
    db.delete_keg(keg_id)
    return RedirectResponse("/kegs/", status_code=303)


@router.post("/assign-tap", response_class=HTMLResponse)
async def assign_tap(
    request: Request,
    tap:     str = Form(...),
    keg_id:  str = Form(...),
):
    db         = get_db()
    config     = get_config()
    keg_id_int = int(keg_id) if keg_id and keg_id != "none" else None
    db.set_tap(tap, keg_id_int)

    if request.headers.get("HX-Request"):
        taps     = db.get_tap_assignments()
        all_kegs = db.get_all_kegs()
        keg_tap_map: dict[int, str] = {}
        for tap_id, display_name in get_configured_taps(config):
            kid = taps.get_keg_id(tap_id)
            if kid is not None:
                keg_tap_map[kid] = display_name
        stats = [keg_stats(db, k, tap=keg_tap_map.get(k.id)) for k in all_kegs]
        return templates.TemplateResponse(
            request, "partials/tap_assignment_panel.html",
            ctx(request, taps=taps, all_kegs=all_kegs, stats=stats,
                configured_taps=get_configured_taps(config)),
        )
    return RedirectResponse("/kegs/", status_code=303)
