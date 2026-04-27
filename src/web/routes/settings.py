from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from web.server import get_db, templates, ctx

router = APIRouter(prefix="/settings")


@router.get("/", response_class=HTMLResponse)
async def settings_page(request: Request):
    db       = get_db()
    settings = db.get_all_settings()
    return templates.TemplateResponse(
        request,
        "settings.html",
        ctx(request, settings=settings),
    )


@router.post("/", response_class=RedirectResponse)
async def settings_save(
    request: Request,
    untappd_client_id:     str = Form(""),
    untappd_client_secret: str = Form(""),
):
    db = get_db()
    db.set_setting("untappd_client_id",     untappd_client_id.strip())
    db.set_setting("untappd_client_secret", untappd_client_secret.strip())
    return RedirectResponse("/settings/?saved=1", status_code=303)
