"""
SmartKegerator web interface — FastAPI + Jinja2 + HTMX + Bootstrap 5.

Runs as a separate process alongside the Qt touchscreen app.
Both share the same SQLite database (WAL mode handles concurrent access).

Start manually:
    cd src/
    python -m web.server [config.yaml]

Or via systemd (see scripts/smartkegerator-web.service):
    systemctl --user start smartkegerator-web

Accessible at:  http://<pi-ip>:8080
"""

from __future__ import annotations

import secrets
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import quote, urlparse

import uvicorn
import yaml
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from data.database import Database

# ---------------------------------------------------------------------------
# Session secret — persisted in a file so sessions survive service restarts.
# Regenerated automatically if the file is deleted.
# ---------------------------------------------------------------------------

_SECRET_FILE = Path(__file__).parent / ".session_secret"


def _load_session_secret() -> str:
    if _SECRET_FILE.exists():
        s = _SECRET_FILE.read_text().strip()
        if len(s) >= 32:
            return s
    s = secrets.token_hex(32)
    _SECRET_FILE.write_text(s)
    try:
        _SECRET_FILE.chmod(0o600)
    except OSError:
        pass
    return s


_SESSION_SECRET = _load_session_secret()

# ---------------------------------------------------------------------------
# App-level shared state
# ---------------------------------------------------------------------------

_db:          Optional[Database] = None
_config:      dict               = {}
_config_path: str                = ""


def get_db() -> Database:
    assert _db is not None, "Database not initialised"
    return _db


def get_config() -> dict:
    return _config


def get_config_path() -> str:
    return _config_path


def reload_config() -> None:
    """Re-read config.yaml into the in-memory dict (used after web-UI edits)."""
    global _config
    if _config_path:
        with open(_config_path, "r") as f:
            _config = yaml.safe_load(f) or {}


# ---------------------------------------------------------------------------
# Jinja2 template filters and globals
# ---------------------------------------------------------------------------

def _setup_templates(templates: Jinja2Templates) -> None:
    env = templates.env

    env.filters["datetime"]    = lambda ts: datetime.fromtimestamp(ts).strftime("%b %d %Y %H:%M")
    env.filters["date"]        = lambda ts: datetime.fromtimestamp(ts).strftime("%b %d, %Y")
    env.filters["usd"]         = lambda v: f"${v:.2f}"
    env.filters["oz"]          = lambda v: f"{v:.1f} oz"
    env.filters["pct"]         = lambda v: f"{v:.0f}%"
    env.filters["abv"]         = lambda v: f"{v:.1f}%"

    env.globals["now"]          = datetime.now
    env.globals["current_year"] = datetime.now().year


# ---------------------------------------------------------------------------
# Lifespan — open DB, register routes, mount static
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _db, _config, _config_path

    _default_config = Path(__file__).parent.parent / "config.yaml"
    _config_path = (
        sys.argv[1]
        if len(sys.argv) > 1 and Path(sys.argv[1]).suffix in (".yaml", ".yml")
        else str(_default_config)
    )
    with open(_config_path, "r") as f:
        _config = yaml.safe_load(f)

    _db = Database(_config["data"]["database_path"])

    # Serve user photos as static files
    photos_dir = Path(_config["data"]["user_photos_dir"])
    photos_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/photos", StaticFiles(directory=str(photos_dir)), name="photos")

    yield

    _db = None


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="SmartKegerator",
    lifespan=lifespan,
    docs_url=None,       # disable Swagger UI
    redoc_url=None,      # disable ReDoc
    openapi_url=None,    # disable /openapi.json
)


# ── Middleware (last added = outermost = first to process requests) ─────────

class _SecurityHeaders(BaseHTTPMiddleware):
    """Attach security response headers to every reply."""
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Frame-Options"]        = "SAMEORIGIN"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"]        = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"]     = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://unpkg.com https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "font-src 'self' https://cdn.jsdelivr.net; "
            "img-src 'self' data: https:; "
            "connect-src 'self'; "
            "frame-ancestors 'none';"
        )
        response.headers.pop("server", None)
        return response


class _AdminAuthMiddleware(BaseHTTPMiddleware):
    """
    First-run redirect + mutation protection.

    - If no admins exist: redirect everything to /admin/setup.
    - POST/PUT/DELETE/PATCH: require an active admin session.
    - GET requests and static files: always public.
    """
    _SKIP_PREFIXES = ("/photos/",)
    _PUBLIC_POSTS  = {"/admin/login", "/admin/setup", "/admin/logout"}

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        # Pass static files straight through
        if any(path.startswith(p) for p in self._SKIP_PREFIXES):
            return await call_next(request)

        # First-run check: redirect to setup when no admins exist
        try:
            db = get_db()
            if not db.has_any_admin() and path != "/admin/setup":
                return RedirectResponse("/admin/setup", status_code=303)
        except Exception:
            pass  # DB not ready yet during startup

        # Protect all mutation requests
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            if path not in self._PUBLIC_POSTS:
                if not request.session.get("admin_username"):
                    # Redirect to login, then come back to the page the form was on
                    referer = request.headers.get("referer", "/")
                    try:
                        next_path = urlparse(referer).path or "/"
                    except Exception:
                        next_path = "/"
                    return RedirectResponse(
                        f"/admin/login?next={quote(next_path, safe='/')}",
                        status_code=303,
                    )

        return await call_next(request)


# Order matters: last add_middleware = outermost = runs first on requests
app.add_middleware(_SecurityHeaders)
app.add_middleware(_AdminAuthMiddleware)
app.add_middleware(SessionMiddleware, secret_key=_SESSION_SECRET, https_only=False)

# ---------------------------------------------------------------------------
# Templates + context helper
# ---------------------------------------------------------------------------

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
_setup_templates(templates)


def ctx(request: Request, **kwargs) -> dict:
    """Build a base template context dict (always includes is_admin)."""
    try:
        is_admin       = bool(request.session.get("admin_username"))
        admin_username = request.session.get("admin_username")
    except Exception:
        # SessionMiddleware not yet available (startup edge-case)
        is_admin       = False
        admin_username = None
    return {
        "request":        request,
        "config":         _config,
        "is_admin":       is_admin,
        "admin_username": admin_username,
        **kwargs,
    }


# Register routers — imported after ctx/templates are defined to avoid circular import
from web.routes import dashboard, beers, kegs, users, pours, settings, untappd  # noqa: E402
from web.routes import admin                                                      # noqa: E402

app.include_router(dashboard.router)
app.include_router(beers.router)
app.include_router(kegs.router)
app.include_router(users.router)
app.include_router(pours.router)
app.include_router(settings.router)
app.include_router(untappd.router)
app.include_router(admin.router)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(_config.get("web", {}).get("port", 8080)) if _config else 8080
    uvicorn.run(
        "web.server:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        log_level="info",
        server_header=False,
    )
