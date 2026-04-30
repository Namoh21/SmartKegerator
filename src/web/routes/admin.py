from __future__ import annotations

import logging

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from web.auth import hash_password, verify_password
from web.server import get_db, templates, ctx

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin")

_MIN_PASSWORD_LEN = 8

_SETUP_ERRORS = {
    "empty":    "Username and password are required.",
    "mismatch": "Passwords do not match.",
    "short":    f"Password must be at least {_MIN_PASSWORD_LEN} characters.",
    "taken":    "That username is already taken.",
}

_LOGIN_ERRORS = {
    "1":       "Invalid username or password.",
    "expired": "Your session has timed out. Please log in again.",
}


# ---------------------------------------------------------------------------
# First-run setup
# ---------------------------------------------------------------------------

@router.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request):
    db = get_db()
    if db.has_any_admin():
        return RedirectResponse("/", status_code=302)
    error = _SETUP_ERRORS.get(request.query_params.get("error", ""))
    # Standalone page — doesn't extend base.html, skip ctx() to avoid session dependency
    return templates.TemplateResponse(
        request, "admin/setup.html", {"request": request, "error": error}
    )


@router.post("/setup", response_class=RedirectResponse)
async def setup_submit(
    username:     str = Form(...),
    display_name: str = Form(""),
    password:     str = Form(...),
    password2:    str = Form(...),
):
    db       = get_db()
    username = username.strip()

    if db.has_any_admin():
        return RedirectResponse("/", status_code=302)

    if not username or not password:
        return RedirectResponse("/admin/setup?error=empty", status_code=303)
    if password != password2:
        return RedirectResponse("/admin/setup?error=mismatch", status_code=303)
    if len(password) < _MIN_PASSWORD_LEN:
        return RedirectResponse("/admin/setup?error=short", status_code=303)
    if db.get_admin_by_username(username):
        return RedirectResponse("/admin/setup?error=taken", status_code=303)

    db.add_admin(username, hash_password(password), display_name=display_name)
    return RedirectResponse("/admin/login?created=1", status_code=303)


# ---------------------------------------------------------------------------
# Login / logout
# ---------------------------------------------------------------------------

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    try:
        if request.session.get("admin_username"):
            return RedirectResponse("/", status_code=302)
    except Exception:
        pass
    error   = _LOGIN_ERRORS.get(request.query_params.get("error", ""))
    created = request.query_params.get("created") == "1"
    next_   = request.query_params.get("next", "/")
    # Standalone page — doesn't extend base.html, skip ctx() to avoid session dependency
    return templates.TemplateResponse(
        request,
        "admin/login.html",
        {"request": request, "error": error, "created": created, "next": next_},
    )


@router.post("/login", response_class=RedirectResponse)
async def login_submit(
    request:  Request,
    username: str = Form(...),
    password: str = Form(...),
    next:     str = Form("/"),
):
    db       = get_db()
    username = username.strip()
    dest     = next if (next.startswith("/") and not next.startswith("//")) else "/"

    admin = db.get_admin_by_username(username)
    if admin and verify_password(password, admin["password_hash"]):
        import time as _time
        request.session["admin_username"] = admin["username"]
        request.session["admin_id"]       = admin["id"]
        request.session["login_time"]     = _time.time()
        if admin.get("user_id"):
            linked = db.get_user(admin["user_id"])
            if linked:
                request.session["user_id"]   = linked.id
                request.session["user_name"] = linked.name
        log.info("Admin login: %s from %s", username, request.client.host if request.client else "unknown")
        return RedirectResponse(dest, status_code=303)

    log.warning("Failed login attempt: username=%r from %s", username, request.client.host if request.client else "unknown")
    return RedirectResponse("/admin/login?error=1", status_code=303)


@router.post("/logout", response_class=RedirectResponse)
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)
