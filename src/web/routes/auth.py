from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from web.auth import hash_password, verify_password
from web.server import get_db, templates

router = APIRouter()

_MIN_PASSWORD_LEN = 8

_ERRORS = {
    "empty":    "Display name and password are required.",
    "short":    f"Password must be at least {_MIN_PASSWORD_LEN} characters.",
    "mismatch": "Passwords do not match.",
    "taken":    "That name is already taken — choose a different display name.",
    "invalid":  "Invalid name or password.",
}


# ---------------------------------------------------------------------------
# Self-registration (creates a standard user account)
# ---------------------------------------------------------------------------

@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    try:
        if request.session.get("user_id"):
            return RedirectResponse("/", status_code=302)
    except Exception:
        pass
    error = _ERRORS.get(request.query_params.get("error", ""))
    return templates.TemplateResponse(
        request, "register.html", {"request": request, "error": error}
    )


@router.post("/register", response_class=RedirectResponse)
async def register_submit(
    request:  Request,
    name:     str = Form(...),
    password: str = Form(...),
    password2: str = Form(...),
):
    name = name.strip()

    if not name or not password:
        return RedirectResponse("/register?error=empty", status_code=303)
    if len(password) < _MIN_PASSWORD_LEN:
        return RedirectResponse("/register?error=short", status_code=303)
    if password != password2:
        return RedirectResponse("/register?error=mismatch", status_code=303)

    db   = get_db()
    user = db.register_user(name, hash_password(password))
    if user is None:
        return RedirectResponse("/register?error=taken", status_code=303)

    request.session["user_id"]   = user.id
    request.session["user_name"] = user.name
    return RedirectResponse("/", status_code=303)


# ---------------------------------------------------------------------------
# Shared logout (works for both standard users and admins)
# ---------------------------------------------------------------------------

@router.post("/logout", response_class=RedirectResponse)
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)
