from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from web.server import get_db, templates, ctx

router = APIRouter()
log = logging.getLogger(__name__)

_API_BASE = "https://api.catalog.beer"


def _api_key(db) -> str:
    return db.get_setting("catalog_beer_api_key", "")


def _extract_items(data) -> list:
    """Pull the beer list out of whatever envelope catalog.beer returns."""
    if isinstance(data, list):
        return data
    for key in ("result", "results", "beers", "data", "items"):
        val = data.get(key)
        if isinstance(val, list):
            return val
    return []


@router.get("/beers/search", response_class=HTMLResponse)
async def search(request: Request, catalog_q: str = Query("")):
    q = catalog_q.strip()
    if len(q) < 2:
        return HTMLResponse("")

    db      = get_db()
    api_key = _api_key(db)

    if not api_key:
        resp = HTMLResponse("")
        resp.headers["HX-Trigger"] = '{"beerSearchWarning": "catalog.beer API key not configured. Go to Settings → Beer DB to add it."}'
        return resp

    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(
                f"{_API_BASE}/beer/search",
                params={"q": q, "count": 15},
                auth=httpx.BasicAuth(api_key, ""),
            )
        resp.raise_for_status()
        data  = resp.json()
        items = _extract_items(data)
        log.info("catalog.beer search q=%r → status=%s keys=%s items=%d",
                 q, resp.status_code,
                 list(data.keys()) if isinstance(data, dict) else type(data).__name__,
                 len(items))
        if not items:
            log.debug("catalog.beer raw response: %s", str(data)[:500])
    except httpx.HTTPStatusError as e:
        log.warning("catalog.beer HTTP error %s for q=%r", e.response.status_code, q)
        if e.response.status_code == 401:
            return HTMLResponse(
                '<p class="text-danger small mt-2">Invalid catalog.beer API key — check Settings.</p>'
            )
        return HTMLResponse(
            f'<p class="text-danger small mt-2">catalog.beer error: {e.response.status_code}</p>'
        )
    except Exception as e:
        log.exception("catalog.beer search failed for q=%r", q)
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
                params={"q": "sam adams boston lager", "count": 3},
                auth=httpx.BasicAuth(api_key, ""),
            )
        resp.raise_for_status()
        data  = resp.json()
        items = _extract_items(data)
        log.info("catalog.beer test connection → status=%s keys=%s items=%d",
                 resp.status_code,
                 list(data.keys()) if isinstance(data, dict) else type(data).__name__,
                 len(items))
        log.debug("catalog.beer test raw: %s", str(data)[:500])
        if items:
            return HTMLResponse(
                f'<span class="text-success">&#10003; Connected — catalog.beer returned {len(items)} result(s).</span>'
            )
        return HTMLResponse(
            '<span class="text-warning">&#9888; Connected but search returned 0 results — '
            'API key may be invalid or rate limited.</span>'
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
