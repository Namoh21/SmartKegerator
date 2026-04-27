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

import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import uvicorn
import yaml
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from data.database import Database

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

    env.globals["now"]         = datetime.now
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

app = FastAPI(title="SmartKegerator", lifespan=lifespan)

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
_setup_templates(templates)


def ctx(request: Request, **kwargs) -> dict:
    """Build a base template context dict."""
    return {"request": request, "config": _config, **kwargs}


# Register routers — imported after ctx/templates are defined to avoid circular import
from web.routes import dashboard, beers, kegs, users, pours, settings, untappd  # noqa: E402

app.include_router(dashboard.router)
app.include_router(beers.router)
app.include_router(kegs.router)
app.include_router(users.router)
app.include_router(pours.router)
app.include_router(settings.router)
app.include_router(untappd.router)


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
    )
