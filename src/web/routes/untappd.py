from __future__ import annotations

import httpx
from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from web.server import get_db, templates, ctx

router = APIRouter(prefix="/untappd")

_API_BASE = "https://api.untappd.com/v4"


def _credentials(db) -> tuple[str, str]:
    return db.get_setting("untappd_client_id"), db.get_setting("untappd_client_secret")


@router.get("/search", response_class=HTMLResponse)
async def search(request: Request, q: str = Query("")):
    q = q.strip()
    if len(q) < 2:
        return HTMLResponse("")

    db = get_db()
    client_id, client_secret = _credentials(db)

    if not client_id or not client_secret:
        return HTMLResponse(
            '<p class="text-warning small mt-2">'
            'Untappd credentials not configured — go to '
            '<a href="/settings/">Settings</a> to add them.'
            "</p>"
        )

    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(
                f"{_API_BASE}/search/beer",
                params={
                    "q": q,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "limit": 8,
                },
            )
        resp.raise_for_status()
        items = resp.json().get("response", {}).get("beers", {}).get("items", [])
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            return HTMLResponse(
                '<p class="text-danger small mt-2">Invalid Untappd credentials — check Settings.</p>'
            )
        return HTMLResponse(
            f'<p class="text-danger small mt-2">Untappd error: {e.response.status_code}</p>'
        )
    except Exception:
        return HTMLResponse(
            '<p class="text-danger small mt-2">Could not reach Untappd — check network.</p>'
        )

    return templates.TemplateResponse(
        request,
        "partials/untappd_results.html",
        ctx(request, results=items, query=q),
    )


@router.get("/test", response_class=HTMLResponse)
async def test_connection(request: Request):
    """HTMX endpoint — called by the Settings page test button."""
    db = get_db()
    client_id, client_secret = _credentials(db)

    if not client_id or not client_secret:
        return HTMLResponse('<span class="text-warning">No credentials saved yet.</span>')

    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(
                f"{_API_BASE}/search/beer",
                params={"q": "IPA", "client_id": client_id, "client_secret": client_secret, "limit": 1},
            )
        resp.raise_for_status()
        count = resp.json().get("response", {}).get("beers", {}).get("found", 0)
        return HTMLResponse(
            f'<span class="text-success">&#10003; Connected — Untappd returned {count:,} results for "IPA"</span>'
        )
    except httpx.HTTPStatusError as e:
        return HTMLResponse(
            f'<span class="text-danger">&#10007; HTTP {e.response.status_code} — check credentials</span>'
        )
    except Exception as e:
        return HTMLResponse(f'<span class="text-danger">&#10007; {e}</span>')
