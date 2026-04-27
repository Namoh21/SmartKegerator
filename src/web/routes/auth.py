from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from web.server import get_db, templates

router = APIRouter()

_ERRORS = {
    "empty":  "A display name is required.",
    "taken":  "That name is already taken — choose a different one.",
}


# ---------------------------------------------------------------------------
# Self-registration — creates a user profile (no password required).
# Identity on the touchscreen is handled by facial recognition.
# ---------------------------------------------------------------------------

@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    error = _ERRORS.get(request.query_params.get("error", ""))
    return templates.TemplateResponse(
        request, "register.html", {"request": request, "error": error}
    )


@router.post("/register", response_class=RedirectResponse)
async def register_submit(
    request: Request,
    name:    str = Form(...),
):
    name = name.strip()
    if not name:
        return RedirectResponse("/register?error=empty", status_code=303)

    db   = get_db()
    user = db.register_user(name)
    if user is None:
        return RedirectResponse("/register?error=taken", status_code=303)

    return RedirectResponse("/users/", status_code=303)


# ---------------------------------------------------------------------------
# Shared logout (admins)
# ---------------------------------------------------------------------------

@router.post("/logout", response_class=RedirectResponse)
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)
