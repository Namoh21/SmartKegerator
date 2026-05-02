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
            payments=pays, photo_items=photo_items,
            is_unknown_user=(user_id == UNKNOWN_USER_ID)),
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
# User thumbnail — server-side center-cropped square JPEG
# ---------------------------------------------------------------------------

@router.get("/{user_id}/thumbnail")
async def user_thumbnail(user_id: int):
    """Return an 80×80 center-cropped JPEG thumbnail for the user's first photo.
    Generated on the fly from the original training photo using OpenCV."""
    import io
    import cv2
    import numpy as np

    db   = get_db()
    user = db.get_user(user_id)
    if not user or not user.image_paths:
        return Response(status_code=204)

    # Use the most recent photo
    img_path = user.image_paths[-1]
    if not Path(img_path).exists():
        return Response(status_code=204)

    try:
        img = cv2.imread(img_path)
        if img is None:
            return Response(status_code=204)

        h, w = img.shape[:2]
        # Crop to a center square
        side = min(h, w)
        x = (w - side) // 2
        y = (h - side) // 2
        cropped = img[y:y + side, x:x + side]

        # Resize to 80×80
        thumb = cv2.resize(cropped, (80, 80), interpolation=cv2.INTER_AREA)

        # Encode as JPEG
        ok, buf = cv2.imencode(".jpg", thumb, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            return Response(status_code=204)

        return Response(
            content=bytes(buf),
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=3600"},
        )
    except Exception:
        return Response(status_code=204)


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
    """
    Start training in a background thread and return immediately with a
    polling div.  On Pi 3, encoding each photo takes 5-15 s, so holding
    the HTTP connection open for the full duration causes the browser to
    time out and the HTMX spinner never resolves.
    """
    import threading
    import logging
    from recognition.face_recognizer import train_user_sync
    log = logging.getLogger(__name__)
    db  = get_db()

    # Guard: reject if a training run is already in progress for this user.
    # Without this, rapid clicks or duplicate requests spawn multiple dlib
    # threads simultaneously — each one uses ~400 MB, which OOM-kills the
    # Pi 3 and leaves the status key in an unpredictable state.
    current = db.get_setting(f"train_status_{user_id}", "")
    if current == "pending":
        log.warning("train: already in progress for user %d — ignoring duplicate request", user_id)
        return HTMLResponse(_train_polling_html(user_id))

    db.set_setting(f"train_status_{user_id}", "pending")

    def _run():
        try:
            config = get_config()
            num, err = train_user_sync(db, config, user_id)
            if err:
                db.set_setting(f"train_status_{user_id}", f"error:{err}")
            else:
                db.set_setting(f"train_status_{user_id}", f"done:{num}")
        except Exception as exc:
            log.error("Training thread crashed for user %d: %s", user_id, exc, exc_info=True)
            db.set_setting(f"train_status_{user_id}", f"error:{exc}")

    threading.Thread(target=_run, name=f"train-web-{user_id}", daemon=True).start()
    return HTMLResponse(_train_section_pending(user_id))


@router.get("/{user_id}/photos/train/poll", response_class=HTMLResponse)
async def photo_train_poll(user_id: int):
    """HTMX polling endpoint — returns the full #train-section HTML each time."""
    db     = get_db()
    status = db.get_setting(f"train_status_{user_id}", "")

    if not status or status == "pending":
        return HTMLResponse(_train_section_pending(user_id))

    db.set_setting(f"train_status_{user_id}", "")

    if status.startswith("done:"):
        n = status[5:]
        return HTMLResponse(_train_section_done(user_id, f"{n} encoding(s) stored — recognition updates within 60 s."))
    msg = status[6:] if status.startswith("error:") else status
    return HTMLResponse(_train_section_error(user_id, msg))


def _train_btn(user_id: int, *, disabled: bool = False) -> str:
    dis = 'disabled' if disabled else (
        f'hx-post="/users/{user_id}/photos/train" '
        f'hx-target="#train-section" hx-swap="innerHTML"'
    )
    return (
        f'<button type="button" class="btn btn-accent btn-sm" {dis}>'
        f'<i class="bi bi-cpu me-1"></i>Train Recognition'
        f'</button>'
    )


def _train_section_pending(user_id: int) -> str:
    """Disabled button + spinner + live status — polls itself every 3 s."""
    return (
        f'<button type="button" class="btn btn-accent btn-sm" disabled>'
        f'<span class="spinner-border spinner-border-sm me-1" role="status"></span>'
        f'Training…'
        f'</button>'
        f'<span class="text-muted small"'
        f' hx-get="/users/{user_id}/photos/train/poll"'
        f' hx-trigger="every 3s"'
        f' hx-target="#train-section"'
        f' hx-swap="innerHTML">'
        f'Processing photos — this may take several minutes on Pi 3…'
        f'</span>'
    )


def _train_section_done(user_id: int, msg: str) -> str:
    return (
        f'{_train_btn(user_id)}'
        f'<span class="text-success small">'
        f'<i class="bi bi-check-circle me-1"></i>{msg}'
        f'</span>'
    )


def _train_section_error(user_id: int, msg: str) -> str:
    return (
        f'{_train_btn(user_id)}'
        f'<span class="text-danger small">'
        f'<i class="bi bi-x-circle me-1"></i>{msg}'
        f'</span>'
    )


def _train_polling_html(user_id: int) -> str:
    # kept for backward compat — now delegates to _train_section_pending
    return _train_section_pending(user_id)


def _unused_old_polling(user_id: int) -> str:
    return (
        f'<span id="train-result-inner"'
        f' hx-get="/users/{user_id}/photos/train/poll"'
        f' hx-trigger="every 3s"'
        f' hx-target="#train-result-inner"'
        f' hx-swap="outerHTML">'
        f'<span class="spinner-border spinner-border-sm text-accent me-1"></span>'
        f'Training… (may take 1–3 min on Pi 3)'
        f'</span>'
    )
