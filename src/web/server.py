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
import threading
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import quote, urlparse

import uvicorn
import yaml
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from fastapi.middleware.cors import CORSMiddleware

from data.database import Database
from ui.theme import site_name as _site_name, css_vars as _css_vars

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

    from log_config import configure as _configure_logging, apply_level as _apply_level
    _configure_logging(_config, "web")
    _apply_level(_db.get_setting("log_level", "high"))

    # User photos are served via authenticated routes (see web/routes/users.py).
    photos_dir = Path(_config["data"]["user_photos_dir"])
    photos_dir.mkdir(parents=True, exist_ok=True)

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

class _RateLimitMiddleware(BaseHTTPMiddleware):
    """
    In-memory rate limiter for all /api/ routes.

    Login endpoint  — 5 attempts per minute per IP.
                      After 10 cumulative failures the IP is locked out for
                      15 minutes.  A successful login resets the failure count.

    All other /api/ routes — 120 requests per minute per IP (generous; only
                      catches runaway scripts or denial-of-service attempts).

    Uses a sliding-window counter so limits are per *rolling* minute, not
    per calendar minute.  No external dependencies — pure in-memory state.
    Memory is bounded: stale entries are pruned on every check, and we only
    track IPs that are actively making requests.
    """

    _LOGIN_PATH     = "/api/v1/auth/login"
    _WEB_LOGIN_PATH = "/admin/login"
    _LOGIN_RPM      = 5     # max login attempts per 60-second window
    _LOGIN_FAILURES = 10    # cumulative failures before lockout
    _LOCKOUT_SECS   = 900   # 15 minutes
    _API_RPM        = 120   # max general API requests per 60-second window
    _WINDOW         = 60    # sliding window in seconds

    def __init__(self, app) -> None:
        super().__init__(app)
        self._lock            = threading.Lock()
        self._login_window:   dict[str, list[float]] = defaultdict(list)
        self._login_failures: dict[str, int]         = defaultdict(int)
        self._login_lockout:  dict[str, float]        = {}
        self._api_window:     dict[str, list[float]]  = defaultdict(list)
        self._last_cleanup:   float                   = time.time()

    def _maybe_cleanup(self, now: float) -> None:
        """Purge stale entries every 5 minutes to keep memory bounded on Pi 3."""
        if now - self._last_cleanup < 300:
            return
        self._last_cleanup = now
        cutoff = now - self._WINDOW
        for ip in list(self._login_window):
            self._login_window[ip] = [t for t in self._login_window[ip] if t > cutoff]
            if not self._login_window[ip]:
                del self._login_window[ip]
        for ip in list(self._api_window):
            self._api_window[ip] = [t for t in self._api_window[ip] if t > cutoff]
            if not self._api_window[ip]:
                del self._api_window[ip]
        expired = [ip for ip, until in self._login_lockout.items() if until < now]
        for ip in expired:
            del self._login_lockout[ip]
            self._login_failures.pop(ip, None)

    @staticmethod
    def _client_ip(request: Request) -> str:
        fwd = request.headers.get("X-Forwarded-For", "")
        if fwd:
            return fwd.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _prune(self, window: list[float], now: float) -> list[float]:
        return [t for t in window if now - t < self._WINDOW]

    def _reject_api(self, message: str, retry_after: int) -> Response:
        import json
        return Response(
            content=json.dumps({"detail": message}),
            status_code=429,
            media_type="application/json",
            headers={"Retry-After": str(retry_after)},
        )

    def _reject_web(self, minutes: int) -> Response:
        return RedirectResponse(
            f"/admin/login?error=locked&minutes={minutes}",
            status_code=303,
        )

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        # Rate-limit the web admin login form
        if path == self._WEB_LOGIN_PATH and request.method == "POST":
            ip  = self._client_ip(request)
            now = time.time()
            with self._lock:
                self._maybe_cleanup(now)
                until = self._login_lockout.get(ip, 0)
                if now < until:
                    mins = max(1, int((until - now) / 60) + 1)
                    return self._reject_web(mins)
                self._login_window[ip] = self._prune(self._login_window[ip], now)
                if len(self._login_window[ip]) >= self._LOGIN_RPM:
                    return self._reject_web(1)
                self._login_window[ip].append(now)

            response = await call_next(request)

            # Track failures — web login redirects to ?error=1 on failure
            with self._lock:
                if response.status_code in (302, 303):
                    loc = response.headers.get("location", "")
                    if "error=1" in loc:
                        self._login_failures[ip] += 1
                        if self._login_failures[ip] >= self._LOGIN_FAILURES:
                            self._login_lockout[ip] = now + self._LOCKOUT_SECS
                            self._login_failures[ip] = 0
                            import logging as _log
                            _log.getLogger(__name__).warning(
                                "Web login: IP %s locked out after %d failures", ip, self._LOGIN_FAILURES
                            )
                    elif "error" not in loc:
                        self._login_failures[ip] = 0
                        self._login_lockout.pop(ip, None)
            return response

        if not path.startswith("/api/"):
            return await call_next(request)

        ip  = self._client_ip(request)
        now = time.time()

        with self._lock:
            self._maybe_cleanup(now)
            is_login = (path == self._LOGIN_PATH and request.method == "POST")

            if is_login:
                # Lockout check
                until = self._login_lockout.get(ip, 0)
                if now < until:
                    secs = int(until - now)
                    return self._reject_api(
                        f"Too many failed login attempts — locked out for "
                        f"{secs // 60 + 1} more minute(s).",
                        retry_after=secs,
                    )
                # Rate limit
                self._login_window[ip] = self._prune(self._login_window[ip], now)
                if len(self._login_window[ip]) >= self._LOGIN_RPM:
                    return self._reject_api(
                        "Too many login attempts — wait 1 minute and try again.",
                        retry_after=self._WINDOW,
                    )
                self._login_window[ip].append(now)

            else:
                self._api_window[ip] = self._prune(self._api_window[ip], now)
                if len(self._api_window[ip]) >= self._API_RPM:
                    return self._reject_api(
                        "API rate limit exceeded — slow down and try again.",
                        retry_after=self._WINDOW,
                    )
                self._api_window[ip].append(now)

        response = await call_next(request)

        # Track login outcomes for lockout logic
        if path == self._LOGIN_PATH and request.method == "POST":
            with self._lock:
                if response.status_code == 401:
                    self._login_failures[ip] += 1
                    if self._login_failures[ip] >= self._LOGIN_FAILURES:
                        self._login_lockout[ip] = now + self._LOCKOUT_SECS
                        self._login_failures[ip] = 0
                        import logging
                        logging.getLogger(__name__).warning(
                            "IP %s locked out after %d failed login attempts",
                            ip, self._LOGIN_FAILURES,
                        )
                elif response.status_code == 200:
                    self._login_failures[ip] = 0
                    self._login_lockout.pop(ip, None)

        return response


class _SecurityHeaders(BaseHTTPMiddleware):
    """Attach security response headers to every reply.

    A fresh CSP nonce is generated per request and stored on request.state so
    templates can stamp it onto every <script> and <style> tag.  The same nonce
    is then embedded in the Content-Security-Policy header so the browser only
    executes scripts/styles that carry the matching value.
    """
    async def dispatch(self, request: Request, call_next) -> Response:
        nonce = secrets.token_urlsafe(16)
        request.state.csp_nonce = nonce        # available to route handlers / templates
        response = await call_next(request)
        response.headers["X-Frame-Options"]        = "SAMEORIGIN"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"]        = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"]     = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            f"script-src 'self' 'nonce-{nonce}' https://unpkg.com https://cdn.jsdelivr.net; "
            f"style-src 'self' 'nonce-{nonce}' https://cdn.jsdelivr.net; "
            "font-src 'self' https://cdn.jsdelivr.net; "
            "img-src 'self' data: https:; "
            "connect-src 'self'; "
            "frame-ancestors 'none';"
        )
        try:
            del response.headers["server"]
        except (KeyError, AttributeError):
            pass
        return response


class _AdminAuthMiddleware(BaseHTTPMiddleware):
    """
    First-run redirect + auth for reads and mutations.

    - If no admins exist: redirect everything to /admin/setup.
    - POST/PUT/DELETE/PATCH: require an active admin session (except login/setup).
    - GET: public by default; when web.require_login_for_read is true, admin required.
    - REST API (/api/) uses JWT and is handled separately.
    """
    _SKIP_PREFIXES = ("/api/",)
    _PUBLIC_GET    = {"/admin/login", "/admin/setup"}
    _PUBLIC_POSTS  = {"/admin/login", "/admin/setup", "/admin/logout",
                      "/register", "/logout"}

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        # REST API — JWT auth on each endpoint
        if any(path.startswith(p) for p in self._SKIP_PREFIXES):
            return await call_next(request)

        # First-run check: redirect to setup when no admins exist
        try:
            db = get_db()
            if not db.has_any_admin() and path != "/admin/setup":
                return RedirectResponse("/admin/setup", status_code=303)
        except Exception:
            pass  # DB not ready yet during startup

        is_admin = bool(request.session.get("admin_username"))

        # Admin session timeout — sliding window
        if is_admin:
            timeout_mins = _config.get("web", {}).get("admin_timeout_minutes")
            if timeout_mins:
                login_time = request.session.get("login_time", 0)
                if time.time() - login_time > timeout_mins * 60:
                    request.session.clear()
                    return RedirectResponse("/?expired=1", status_code=303)
                request.session["login_time"] = time.time()
                is_admin = True

        # Optional: require admin login to view any page (balances, pour history, etc.)
        if (
            request.method == "GET"
            and _config.get("web", {}).get("require_login_for_read")
            and path not in self._PUBLIC_GET
            and not is_admin
        ):
            return RedirectResponse(
                f"/admin/login?next={quote(path, safe='/')}",
                status_code=303,
            )

        # Protect all mutation requests
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            if path not in self._PUBLIC_POSTS and not is_admin:
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


# CORS — allows the Android app to reach /api/v1/* from any origin.
# All /api/v1/* endpoints require a Bearer token so wildcard origin is
# acceptable; the token is the actual security boundary.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    allow_credentials=False,   # no cookies over CORS — token auth only
)

# Order matters: last add_middleware = outermost = runs first on requests
app.add_middleware(_RateLimitMiddleware)
app.add_middleware(_SecurityHeaders)
app.add_middleware(_AdminAuthMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=_SESSION_SECRET,
    https_only=False,   # set True in prod when SSL is enabled
    same_site="lax",    # blocks CSRF from cross-site POSTs; lax allows top-level nav
)

# ---------------------------------------------------------------------------
# Templates + context helper
# ---------------------------------------------------------------------------

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
_setup_templates(templates)


def _app_version() -> str:
    try:
        return (Path(__file__).parent.parent / "VERSION").read_text().strip()
    except Exception:
        return ""


def ctx(request: Request, **kwargs) -> dict:
    """Build a base template context dict (always includes is_admin)."""
    try:
        admin_username = request.session.get("admin_username")
        is_admin       = bool(admin_username)
    except Exception:
        admin_username = None
        is_admin       = False
    nonce = getattr(request.state, "csp_nonce", "")
    return {
        "request":        request,
        "config":         _config,
        "is_admin":       is_admin,
        "admin_username": admin_username,
        "site_name":      _site_name(_config),
        "theme_vars":     _css_vars(_config),
        "csp_nonce":      nonce,
        "app_version":    _app_version(),
        **kwargs,
    }


# Register routers — imported after ctx/templates are defined to avoid circular import
from web.routes import dashboard, beers, kegs, users, pours, settings, catalog_beer  # noqa: E402
from web.routes import admin, auth                                                     # noqa: E402
from web.routes.api import router as api_router                                        # noqa: E402

from starlette.exceptions import HTTPException as StarletteHTTPException   # noqa: E402

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        return templates.TemplateResponse(
            request, "404.html", ctx(request), status_code=404
        )
    if exc.status_code == 500:
        return templates.TemplateResponse(
            request, "500.html", ctx(request), status_code=500
        )
    return Response(str(exc.detail), status_code=exc.status_code)

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    import logging as _log
    _log.getLogger(__name__).exception("Unhandled exception on %s", request.url.path)
    return templates.TemplateResponse(
        request, "500.html", ctx(request), status_code=500
    )

app.include_router(dashboard.router)
app.include_router(beers.router)
app.include_router(kegs.router)
app.include_router(users.router)
app.include_router(pours.router)
app.include_router(settings.router)
app.include_router(catalog_beer.router)
app.include_router(admin.router)
app.include_router(auth.router)
app.include_router(api_router)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _make_redirect_app(https_port: int):
    """Minimal ASGI app that redirects all HTTP traffic to HTTPS."""
    async def redirect_app(scope, receive, send):
        if scope["type"] == "http":
            host = dict(scope.get("headers", [])).get(b"host", b"").decode().split(":")[0]
            path = scope.get("path", "/")
            qs   = scope.get("query_string", b"").decode()
            url  = f"https://{host}:{https_port}{path}"
            if qs:
                url += f"?{qs}"
            await send({
                "type": "http.response.start",
                "status": 301,
                "headers": [[b"location", url.encode()], [b"content-length", b"0"]],
            })
            await send({"type": "http.response.body", "body": b""})
    return redirect_app


if __name__ == "__main__":
    import threading as _threading

    web_cfg     = _config.get("web", {}) if _config else {}
    port        = int(web_cfg.get("port", 8080))
    ssl_cfg     = web_cfg.get("ssl", {})
    ssl_enabled = bool(ssl_cfg.get("enabled", False))
    certfile    = ssl_cfg.get("certfile", "") if ssl_enabled else None
    keyfile     = ssl_cfg.get("keyfile",  "") if ssl_enabled else None

    # When HTTPS is active, spin up a lightweight HTTP→HTTPS redirect on port 80
    if ssl_enabled and certfile and keyfile:
        def _run_redirect():
            import uvicorn as _uv
            _uv.run(
                _make_redirect_app(port),
                host="0.0.0.0",
                port=80,
                log_level="warning",
                server_header=False,
            )
        t = _threading.Thread(target=_run_redirect, daemon=True)
        t.start()

    uvicorn.run(
        "web.server:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        log_level="info",
        server_header=False,
        ssl_certfile=certfile or None,
        ssl_keyfile=keyfile or None,
    )
