from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from data.models import User, UNKNOWN_USER_ID
from web.server import get_db, templates, ctx
from web.helpers import user_stats

router = APIRouter(prefix="/users")


@router.get("/", response_class=HTMLResponse)
async def user_list(request: Request):
    db    = get_db()
    users = db.get_all_users()

    stats = [
        user_stats(db, u.id)
        for u in users
        if u.id != UNKNOWN_USER_ID
    ]
    # Sort by balance descending (highest tab first)
    stats.sort(key=lambda s: s.balance, reverse=True)

    return templates.TemplateResponse(
        request,
        "users.html",
        ctx(request, stats=stats),
    )


@router.get("/{user_id}", response_class=HTMLResponse)
async def user_detail(user_id: int, request: Request):
    db   = get_db()
    user = db.get_user(user_id)
    if not user:
        return RedirectResponse("/users/", status_code=302)

    stats  = user_stats(db, user_id)
    pours  = sorted(db.get_pours_for_user(user_id), key=lambda p: p.time, reverse=True)
    pays   = sorted(db.get_payments_for_user(user_id), key=lambda p: p.time, reverse=True)

    # Enrich pours with beer names
    keg_beer_cache: dict[int, str] = {}
    def beer_for_keg(keg_id: int) -> str:
        if keg_id not in keg_beer_cache:
            keg  = db.get_keg(keg_id)
            beer = db.get_beer(keg.beer_id) if keg else None
            keg_beer_cache[keg_id] = beer.name if beer else "Unknown"
        return keg_beer_cache[keg_id]

    enriched = [{"pour": p, "beer_name": beer_for_keg(p.keg_id)} for p in pours]

    return templates.TemplateResponse(
        request,
        "user_detail.html",
        ctx(request, user=user, stats=stats, enriched_pours=enriched, payments=pays),
    )


@router.post("/add", response_class=RedirectResponse)
async def user_add(name: str = Form(...)):
    db   = get_db()
    user = User(id=None, name=name.strip())
    db.save_user(user)
    return RedirectResponse("/users/", status_code=303)


@router.post("/{user_id}/rename", response_class=RedirectResponse)
async def user_rename(user_id: int, name: str = Form(...)):
    db   = get_db()
    user = db.get_user(user_id)
    if user and user_id != UNKNOWN_USER_ID:
        user.name = name.strip()
        db.save_user(user)
    return RedirectResponse(f"/users/{user_id}", status_code=303)


@router.post("/{user_id}/delete", response_class=RedirectResponse)
async def user_delete(user_id: int):
    db = get_db()
    if user_id != UNKNOWN_USER_ID:
        db.delete_face_encodings_for_user(user_id)
        db.delete_user(user_id)
    return RedirectResponse("/users/", status_code=303)


@router.post("/{user_id}/payment", response_class=RedirectResponse)
async def add_payment(user_id: int, amount: float = Form(...)):
    db = get_db()
    if db.get_user(user_id):
        db.add_payment(user_id, amount)
    return RedirectResponse(f"/users/{user_id}", status_code=303)
