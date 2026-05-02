from __future__ import annotations

import httpx
from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from web.server import get_db, templates, ctx

router = APIRouter()

_API_BASE = "https://api.catalog.beer"


def _api_key(db) -> str:
    return db.get_setting("catalog_beer_api_key", "")


@router.get("/beers/search", response_class=HTMLResponse)
async def search(request: Request, q: str = Query("")):
    q = q.strip()
    if len(q) < 2:
        return HTMLResponse("")

    db      = get_db()
    api_key = _api_key(db)

    if not api_key:
        return HTMLResponse(
            '<p class="text-warning small mt-2">'
            'catalog.beer API key not configured — go to '
            '<a href="/settings/?tab=beer-db">Settings</a> to add it.'
            "</p>"
        )

    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(
                f"{_API_BASE}/beer/search",
                params={"q": q, "count": 15},
                auth=httpx.BasicAuth(api_key, ""),
            )
        resp.raise_for_status()
        items = resp.json().get("result", [])
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            return HTMLResponse(
                '<p class="text-danger small mt-2">Invalid catalog.beer API key — check Settings.</p>'
            )
        return HTMLResponse(
            f'<p class="text-danger small mt-2">catalog.beer error: {e.response.status_code}</p>'
        )
    except Exception:
        return HTMLResponse(
            '<p class="text-danger small mt-2">Could not reach catalog.beer — check network.</p>'
        )

    return templates.TemplateResponse(
        request,
        "partials/catalog_beer_results.html",
        ctx(request, results=items, query=q),
    )


@router.get("/untappd/test", response_class=HTMLResponse)
async def test_connection(request: Request):
    """HTMX endpoint — called by the Settings page test button."""
    db      = get_db()
    api_key = _api_key(db)

    if not api_key:
        return HTMLResponse('<span class="text-warning">No API key saved yet.</span>')

    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(
                f"{_API_BASE}/beer/search",
                params={"q": "sam adams boston lager", "count": 1},
                auth=httpx.BasicAuth(api_key, ""),
            )
        resp.raise_for_status()
        count = len(resp.json().get("result", []))
        return HTMLResponse(
            f'<span class="text-success">&#10003; Connected — catalog.beer returned {count} result(s) for "IPA"</span>'
        )
    except httpx.HTTPStatusError as e:
        return HTMLResponse(
            f'<span class="text-danger">&#10007; HTTP {e.response.status_code} — check API key</span>'
        )
    except Exception as e:
        return HTMLResponse(f'<span class="text-danger">&#10007; {e}</span>')


@router.get("/beers/catalog-lookup", response_class=JSONResponse)
async def catalog_lookup(catalog_id: str = Query(...)):
    """Fetch full beer details from catalog.beer by ID."""
    db      = get_db()
    api_key = _api_key(db)

    if not api_key:
        return JSONResponse({"error": "No API key configured"}, status_code=400)

    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(
                f"{_API_BASE}/beer/{catalog_id}",
                auth=httpx.BasicAuth(api_key, ""),
            )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as e:
        return JSONResponse({"error": f"HTTP {e.response.status_code}"}, status_code=e.response.status_code)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    return JSONResponse({
        "id":          data.get("id"),
        "name":        data.get("name", ""),
        "brewery":     data.get("brewer", {}).get("name", ""),
        "style":       data.get("style", ""),
        "abv":         data.get("abv"),
        "ibu":         data.get("ibu"),
        "description": data.get("description", ""),
    })
