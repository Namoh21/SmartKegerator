from __future__ import annotations

import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

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
# Camera preview (served from the JPEG the Qt app writes periodically)
# ---------------------------------------------------------------------------

@router.get("/camera/preview")
async def camera_preview_image():
    config = get_config()
    path   = Path(config["data"]["user_photos_dir"]).parent / "camera_preview.jpg"
    if not path.exists():
        return Response(status_code=204)   # no content yet — browser shows nothing
    return FileResponse(str(path), media_type="image/jpeg",
                        headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------------------
# Face recognition photos — camera capture only (no file upload)
# ---------------------------------------------------------------------------

_CAPTURE_TIMEOUT = 20  # seconds before giving up on the Qt app


@router.post("/{user_id}/photos/capture", response_class=HTMLResponse)
async def capture_start(user_id: int):
    """Ask the Qt touchscreen app to snap a photo from its camera."""
    db     = get_db()
    req_id = uuid.uuid4().hex[:12]
    db.set_setting("capture_request", f"{user_id}:{req_id}")
    db.set_setting("capture_result",  "")
    db.set_setting("capture_ts",      str(time.time()))
    return HTMLResponse(_capture_waiting_html(user_id, req_id))


@router.get("/{user_id}/photos/capture/{req_id}", response_class=HTMLResponse)
async def capture_poll(user_id: int, req_id: str, response: Response):
    """HTMX polling endpoint — returns success (triggers page refresh) or keeps polling."""
    db     = get_db()
    result = db.get_setting("capture_result", "")
    ts     = float(db.get_setting("capture_ts", "0") or 0)

    if result.startswith(f"{req_id}:"):
        db.set_setting("capture_result", "")
        db.set_setting("capture_ts",     "")
        payload = result[len(req_id) + 1:]
        if payload.startswith("ERROR"):
            detail = payload[6:].lstrip(":") or "Camera not ready — is the touchscreen app running?"
            return HTMLResponse(
                f'<span class="text-danger">'
                f'<i class="bi bi-x-circle me-1"></i>{detail}'
                f'</span>'
            )
        # Success — tell HTMX to do a full page refresh so the new photo appears
        response.headers["HX-Refresh"] = "true"
        return HTMLResponse('<span class="text-success">Captured!</span>')

    if time.time() - ts > _CAPTURE_TIMEOUT:
        db.set_setting("capture_request", "")
        return HTMLResponse(
            '<span class="text-warning">'
            '<i class="bi bi-clock me-1"></i>'
            'Timed out — make sure the kegerator touchscreen app is running.'
            '</span>'
        )

    return HTMLResponse(_capture_waiting_html(user_id, req_id))


def _capture_waiting_html(user_id: int, req_id: str) -> str:
    return (
        f'<div id="capture-status" class="d-inline-flex align-items-center gap-2"'
        f' hx-get="/users/{user_id}/photos/capture/{req_id}"'
        f' hx-trigger="every 1s"'
        f' hx-target="#capture-status"'
        f' hx-swap="outerHTML">'
        f'<span class="spinner-border spinner-border-sm text-accent"></span>'
        f'Waiting for camera…'
        f'</div>'
    )


@router.post("/{user_id}/photos/delete", response_class=RedirectResponse)
async def photo_delete(user_id: int, photo_path: str = Form(...)):
    db   = get_db()
    user = db.get_user(user_id)
    if user:
        photos_root = Path(get_config()["data"]["user_photos_dir"]).resolve()
        try:
            target = Path(photo_path).resolve()
            # Ensure the path is inside the user photos directory
            target.relative_to(photos_root)
        except (ValueError, Exception):
            return RedirectResponse(f"/users/{user_id}", status_code=303)
        user.image_paths = [p for p in user.image_paths if p != photo_path]
        db.save_user(user)
        try:
            target.unlink(missing_ok=True)
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
