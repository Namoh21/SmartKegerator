from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from web.server import get_db

router = APIRouter()


# ---------------------------------------------------------------------------
# /register — previously public self-registration.
# Redirected to admin login; user creation is now admin-only on the web.
# Touchscreen self-registration is handled in the Qt UsersWindow.
# ---------------------------------------------------------------------------

@router.get("/register", response_class=RedirectResponse)
async def register_page(request: Request):
    return RedirectResponse("/admin/login?next=/users/", status_code=303)


@router.post("/register", response_class=RedirectResponse)
async def register_submit(request: Request, name: str = Form(...)):
    return RedirectResponse("/admin/login?next=/users/", status_code=303)


# ---------------------------------------------------------------------------
# Shared logout (admins)
# ---------------------------------------------------------------------------

@router.post("/logout", response_class=RedirectResponse)
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)
