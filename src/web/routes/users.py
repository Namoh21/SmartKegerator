from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from data.models import User, UNKNOWN_USER_ID
from web.server import get_config, get_db, templates, ctx
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
        ctx(request, stats=stats, admin_user_ids=db.get_admin_user_ids()),
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

    # Build (path, url) pairs for the template
    photos_dir = Path(get_config()["data"]["user_photos_dir"])
    photo_items = [
        (p, f"/photos/{user_id}/{Path(p).name}")
        for p in user.image_paths
    ]

    return templates.TemplateResponse(
        request,
        "user_detail.html",
        ctx(request, user=user, stats=stats, enriched_pours=enriched,
            payments=pays, photo_items=photo_items),
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


# ---------------------------------------------------------------------------
# Face recognition photos
# ---------------------------------------------------------------------------

@router.post("/{user_id}/photos/upload", response_class=RedirectResponse)
async def photo_upload(user_id: int, photos: list[UploadFile] = File(...)):
    db     = get_db()
    config = get_config()
    user   = db.get_user(user_id)
    if not user or user_id == UNKNOWN_USER_ID:
        return RedirectResponse(f"/users/{user_id}", status_code=303)

    user_dir = Path(config["data"]["user_photos_dir"]) / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)

    existing = len(list(user_dir.glob("*.jpg"))) + len(list(user_dir.glob("*.png")))
    for i, upload in enumerate(photos):
        suffix = Path(upload.filename or "").suffix.lower() or ".jpg"
        dest   = user_dir / f"pic{existing + i}{suffix}"
        with open(dest, "wb") as f:
            shutil.copyfileobj(upload.file, f)
        db.add_user_image(user_id, str(dest))

    return RedirectResponse(f"/users/{user_id}", status_code=303)


@router.post("/{user_id}/photos/delete", response_class=RedirectResponse)
async def photo_delete(user_id: int, photo_path: str = Form(...)):
    db   = get_db()
    user = db.get_user(user_id)
    if user:
        user.image_paths = [p for p in user.image_paths if p != photo_path]
        db.save_user(user)
        try:
            Path(photo_path).unlink(missing_ok=True)
        except Exception:
            pass
    return RedirectResponse(f"/users/{user_id}", status_code=303)


@router.post("/{user_id}/photos/train", response_class=HTMLResponse)
async def photo_train(user_id: int):
    import asyncio
    from recognition.face_recognizer import train_user_sync
    db     = get_db()
    config = get_config()
    num, err = await asyncio.get_event_loop().run_in_executor(
        None, train_user_sync, db, config, user_id
    )
    if err:
        return HTMLResponse(
            f'<span class="text-danger"><i class="bi bi-x-circle me-1"></i>{err}</span>'
        )
    return HTMLResponse(
        f'<span class="text-success"><i class="bi bi-check-circle me-1"></i>'
        f'Trained on {num} encoding(s). Live recognition updates within 60 s.</span>'
    )
