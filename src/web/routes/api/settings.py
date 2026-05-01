from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from log_config import apply_level, LEVELS
from web.api_auth import require_admin
from web.server import get_config, get_config_path, get_db, reload_config

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_yaml() -> dict:
    path = get_config_path()
    if not path:
        return {}
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}


def _write_yaml(data: dict) -> None:
    path = get_config_path()
    if not path:
        raise HTTPException(500, "Config path not available")
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    reload_config()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class SettingsResponse(BaseModel):
    # Identity
    site_name:             str
    # Taps
    tap_count:             int
    ticks_per_liter:       int
    tick_threshold:        int
    end_pour_seconds:      float
    log_pours:             bool
    # Recognition
    recognition_enabled:   bool
    confidence_threshold:  float
    detection_model:       str
    # Logging
    log_level:             str


class SettingsPatch(BaseModel):
    site_name:             Optional[str]   = None
    tap_count:             Optional[int]   = None
    ticks_per_liter:       Optional[int]   = None
    tick_threshold:        Optional[int]   = None
    end_pour_seconds:      Optional[float] = None
    log_pours:             Optional[bool]  = None
    recognition_enabled:   Optional[bool]  = None
    confidence_threshold:  Optional[float] = None
    detection_model:       Optional[str]   = None
    log_level:             Optional[str]   = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/settings", response_model=SettingsResponse,
            dependencies=[Depends(require_admin)])
async def get_settings():
    """Return all user-configurable settings.  Admin only."""
    cfg = _read_yaml()
    db  = get_db()
    hw  = cfg.get("hardware",    {})
    ui  = cfg.get("ui",          {})
    rec = cfg.get("recognition", {})
    taps = cfg.get("taps",       {})

    return SettingsResponse(
        site_name            = ui.get("name",                   "SmartKegerator"),
        tap_count            = int(taps.get("count",            3)),
        ticks_per_liter      = int(hw.get("ticks_per_liter",   500)),
        tick_threshold       = int(hw.get("tick_threshold",     3)),
        end_pour_seconds     = float(hw.get("end_pour_seconds", 5.0)),
        log_pours            = bool(ui.get("log_pours",         True)),
        recognition_enabled  = bool(rec.get("enabled",          True)),
        confidence_threshold = float(rec.get("confidence_threshold", 0.55)),
        detection_model      = rec.get("detection_model",       "hog"),
        log_level            = db.get_setting("log_level",      "high"),
    )


@router.patch("/settings", response_model=SettingsResponse,
              dependencies=[Depends(require_admin)])
async def update_settings(body: SettingsPatch):
    """Update one or more settings.  Only fields included in the request are changed.  Admin only."""
    cfg = _read_yaml()
    db  = get_db()

    cfg.setdefault("ui",          {})
    cfg.setdefault("hardware",    {})
    cfg.setdefault("recognition", {})
    cfg.setdefault("taps",        {})

    if body.site_name is not None:
        cfg["ui"]["name"] = body.site_name.strip() or "SmartKegerator"

    if body.tap_count is not None:
        cfg["taps"]["count"] = max(1, min(4, body.tap_count))

    if body.ticks_per_liter is not None:
        cfg["hardware"]["ticks_per_liter"] = max(1, body.ticks_per_liter)

    if body.tick_threshold is not None:
        cfg["hardware"]["tick_threshold"] = max(1, body.tick_threshold)

    if body.end_pour_seconds is not None:
        cfg["hardware"]["end_pour_seconds"] = max(1.0, body.end_pour_seconds)

    if body.log_pours is not None:
        cfg["ui"]["log_pours"] = body.log_pours

    if body.recognition_enabled is not None:
        cfg["recognition"]["enabled"] = body.recognition_enabled

    if body.confidence_threshold is not None:
        cfg["recognition"]["confidence_threshold"] = max(0.1, min(1.0, body.confidence_threshold))

    if body.detection_model is not None:
        if body.detection_model not in ("hog", "cnn"):
            raise HTTPException(400, "detection_model must be 'hog' or 'cnn'")
        cfg["recognition"]["detection_model"] = body.detection_model

    if body.log_level is not None:
        if body.log_level not in LEVELS:
            raise HTTPException(400, f"log_level must be one of: {list(LEVELS)}")
        db.set_setting("log_level", body.log_level)
        apply_level(body.log_level)

    _write_yaml(cfg)
    return await get_settings()
