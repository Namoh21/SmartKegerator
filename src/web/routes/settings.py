from __future__ import annotations

import asyncio
import glob
import subprocess
from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ui.theme import THEMES
from web.auth import hash_password
from web.server import get_db, get_config_path, reload_config, templates, ctx

router = APIRouter(prefix="/settings")

# BCM GPIO pins available on Raspberry Pi 4/5
GPIO_PINS: list[tuple[int, str]] = [
    (2,  "GPIO 2  — I2C SDA"),
    (3,  "GPIO 3  — I2C SCL"),
    (4,  "GPIO 4  — 1-Wire default"),
    (5,  "GPIO 5"),
    (6,  "GPIO 6"),
    (7,  "GPIO 7  — SPI CE1"),
    (8,  "GPIO 8  — SPI CE0"),
    (9,  "GPIO 9  — SPI MISO"),
    (10, "GPIO 10 — SPI MOSI"),
    (11, "GPIO 11 — SPI SCLK"),
    (12, "GPIO 12 — PWM0"),
    (13, "GPIO 13 — PWM1"),
    (14, "GPIO 14 — UART TX"),
    (15, "GPIO 15 — UART RX"),
    (16, "GPIO 16"),
    (17, "GPIO 17"),
    (18, "GPIO 18 — PWM0"),
    (19, "GPIO 19 — SPI / I2S"),
    (20, "GPIO 20 — SPI / I2S"),
    (21, "GPIO 21 — SPI / I2S"),
    (22, "GPIO 22"),
    (23, "GPIO 23"),
    (24, "GPIO 24"),
    (25, "GPIO 25"),
    (26, "GPIO 26"),
    (27, "GPIO 27"),
]


def _get_local_ip() -> str:
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"


def _apply_display_rotation(degrees: int) -> None:
    """Write the new rotation into the active compositor config (live update)."""
    import os, re
    home = Path(os.path.expanduser("~"))
    t    = str(degrees)

    labwc = home / ".config/labwc/autostart"
    if labwc.exists():
        text = labwc.read_text()
        new  = re.sub(r'wlr-randr --output DSI-1 --transform \S+',
                      f'wlr-randr --output DSI-1 --transform {t}', text)
        if new == text:  # entry missing — append it
            new = new.rstrip("\n") + f'\nwlr-randr --output DSI-1 --transform {t} &\n'
        labwc.write_text(new)
        return

    wayfire = home / ".config/wayfire.ini"
    if wayfire.exists():
        text = wayfire.read_text()
        new  = re.sub(r'(?m)(^\[output:DSI-1\][^\[]*?transform\s*=\s*)\S+',
                      rf'\g<1>{t}', text)
        if new == text:
            new = new.rstrip("\n") + f'\n[output:DSI-1]\ntransform = {t}\n'
        wayfire.write_text(new)


def _read_yaml() -> dict:
    path = get_config_path()
    if not path:
        return {}
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}


def _write_yaml(data: dict) -> None:
    path = get_config_path()
    if not path:
        return
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    reload_config()


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
async def settings_page(request: Request):
    db       = get_db()
    settings = db.get_all_settings()
    cfg      = _read_yaml()
    admins   = db.get_all_admins() if request.session.get("admin_username") else []
    server_ip   = _get_local_ip()
    server_port = int(cfg.get("web", {}).get("port", 8080))
    return templates.TemplateResponse(
        request,
        "settings.html",
        ctx(request, settings=settings, yaml_config=cfg, gpio_pins=GPIO_PINS,
            admins=admins, themes=THEMES,
            server_ip=server_ip, server_port=server_port),
    )


# ---------------------------------------------------------------------------
# Appearance (name + theme)
# ---------------------------------------------------------------------------

@router.post("/appearance", response_class=RedirectResponse)
async def settings_save_appearance(
    site_name: str = Form("SmartKegerator"),
    theme:     str = Form("dark_blue"),
):
    from ui.theme import THEMES as _THEMES
    cfg = _read_yaml()
    cfg.setdefault("ui", {})
    cfg["ui"]["name"]  = site_name.strip() or "SmartKegerator"
    cfg["ui"]["theme"] = theme if theme in _THEMES else "dark_blue"
    _write_yaml(cfg)
    return RedirectResponse("/settings/?saved=1&tab=appearance", status_code=303)


@router.post("/display-rotation", response_class=RedirectResponse)
async def settings_save_display_rotation(rotation: int = Form(90)):
    if rotation not in (0, 90, 180, 270):
        rotation = 90
    cfg = _read_yaml()
    cfg.setdefault("display", {})
    cfg["display"]["rotation"] = rotation
    _write_yaml(cfg)
    _apply_display_rotation(rotation)
    return RedirectResponse("/settings/?saved=1&tab=appearance", status_code=303)


# ---------------------------------------------------------------------------
# Taps
# ---------------------------------------------------------------------------

@router.post("/taps", response_class=RedirectResponse)
async def settings_save_taps(
    tap_count: int = Form(...),
    tap1_name: str = Form("Left"),
    tap1_pin:  int = Form(23),
    tap2_name: str = Form("Center"),
    tap2_pin:  int = Form(24),
    tap3_name: str = Form("Right"),
    tap3_pin:  int = Form(25),
    tap4_name: str = Form("Tap 4"),
    tap4_pin:  int = Form(26),
):
    cfg = _read_yaml()
    cfg.setdefault("taps", {})
    cfg["taps"]["count"] = tap_count
    cfg["taps"]["tap1"]  = {"name": tap1_name, "pin": tap1_pin}
    cfg["taps"]["tap2"]  = {"name": tap2_name, "pin": tap2_pin}
    cfg["taps"]["tap3"]  = {"name": tap3_name, "pin": tap3_pin}
    cfg["taps"]["tap4"]  = {"name": tap4_name, "pin": tap4_pin}
    _write_yaml(cfg)
    return RedirectResponse("/settings/?saved=1&tab=taps", status_code=303)


# ---------------------------------------------------------------------------
# Camera
# ---------------------------------------------------------------------------

@router.post("/camera", response_class=RedirectResponse)
async def settings_save_camera(
    camera_index:     int           = Form(0),
    camera_width:     int           = Form(640),
    camera_height:    int           = Form(480),
    camera_use_color: Optional[str] = Form(None),
    camera_leds_pin:  int           = Form(18),
):
    cfg = _read_yaml()
    cfg.setdefault("hardware", {})
    cfg["hardware"]["camera_index"]     = camera_index
    cfg["hardware"]["camera_width"]     = camera_width
    cfg["hardware"]["camera_height"]    = camera_height
    cfg["hardware"]["camera_use_color"] = camera_use_color is not None
    cfg["hardware"]["camera_leds_pin"]  = camera_leds_pin
    _write_yaml(cfg)
    return RedirectResponse("/settings/?saved=1&tab=camera", status_code=303)


# ---------------------------------------------------------------------------
# Temperature sensors
# ---------------------------------------------------------------------------

@router.post("/sensors", response_class=RedirectResponse)
async def settings_save_sensors(
    temp_sensor_power_pin: int = Form(17),
    temp_sensor_dht_pin:   int = Form(22),
    liquid_temp_sensor_id: str = Form(""),
):
    cfg = _read_yaml()
    cfg.setdefault("hardware", {})
    cfg["hardware"]["temp_sensor_power_pin"] = temp_sensor_power_pin
    cfg["hardware"]["temp_sensor_dht_pin"]   = temp_sensor_dht_pin
    cfg["hardware"]["liquid_temp_sensor_id"] = liquid_temp_sensor_id.strip()
    _write_yaml(cfg)
    return RedirectResponse("/settings/?saved=1&tab=sensors", status_code=303)


# ---------------------------------------------------------------------------
# Untappd credentials (stored in DB, not YAML)
# ---------------------------------------------------------------------------

@router.post("/untappd", response_class=RedirectResponse)
async def settings_save_untappd(
    untappd_client_id:     str = Form(""),
    untappd_client_secret: str = Form(""),
):
    db = get_db()
    db.set_setting("untappd_client_id", untappd_client_id.strip())
    # Only overwrite secret when user typed a new value; blank = keep existing
    secret = untappd_client_secret.strip()
    if secret:
        db.set_setting("untappd_client_secret", secret)
    return RedirectResponse("/settings/?saved=1&tab=untappd", status_code=303)


# ---------------------------------------------------------------------------
# Hardware detection (HTMX endpoints)
# ---------------------------------------------------------------------------

@router.get("/detect/cameras", response_class=HTMLResponse)
async def detect_cameras():
    """Scan /dev/video* and return <option> elements for the camera select."""
    devices = sorted(glob.glob("/dev/video*"))
    if not devices:
        return HTMLResponse('<option value="0">No cameras found — defaulting to index 0</option>')
    return HTMLResponse("\n".join(
        f'<option value="{i}">{d} (index {i})</option>'
        for i, d in enumerate(devices)
    ))


@router.get("/detect/sensors", response_class=HTMLResponse)
async def detect_sensors():
    """Scan DS18B20 1-Wire devices and return clickable buttons."""
    devices = sorted(glob.glob("/sys/bus/w1/devices/28-*"))
    if not devices:
        return HTMLResponse(
            '<p class="text-warning small mb-0">'
            '<i class="bi bi-exclamation-triangle me-1"></i>'
            'No DS18B20 sensors found. Enable 1-Wire in raspi-config → Interface Options, then reboot.</p>'
        )
    buttons = "".join(
        f'<button type="button" class="btn btn-sm btn-outline-secondary me-1 mb-1 sensor-id-btn"'
        f' data-id="{Path(d).name}">{Path(d).name}</button>'
        for d in devices
    )
    return HTMLResponse(
        f'<div class="mb-1">{buttons}</div>'
        '<p class="text-muted small mb-0">Click a sensor ID to copy it to the field above.</p>'
    )


# ---------------------------------------------------------------------------
# Service restart
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Admin session timeout
# ---------------------------------------------------------------------------

@router.post("/admin-timeout", response_class=RedirectResponse)
async def settings_save_admin_timeout(
    admin_timeout_minutes: str = Form(""),
):
    cfg = _read_yaml()
    cfg.setdefault("web", {})
    if admin_timeout_minutes.strip():
        try:
            cfg["web"]["admin_timeout_minutes"] = int(admin_timeout_minutes)
        except ValueError:
            cfg["web"]["admin_timeout_minutes"] = None
    else:
        cfg["web"]["admin_timeout_minutes"] = None
    _write_yaml(cfg)
    return RedirectResponse("/settings/?saved=1&tab=admins", status_code=303)


# ---------------------------------------------------------------------------
# Web server port
# ---------------------------------------------------------------------------

@router.post("/server-port", response_class=RedirectResponse)
async def settings_save_server_port(
    port: int = Form(8080),
):
    cfg = _read_yaml()
    cfg.setdefault("web", {})
    cfg["web"]["port"] = max(1024, min(65535, port))
    _write_yaml(cfg)
    return RedirectResponse("/settings/?saved=1&tab=admins", status_code=303)


# ---------------------------------------------------------------------------
# Admin account management (admin-only; middleware enforces POST auth)
# ---------------------------------------------------------------------------

@router.post("/admins/add", response_class=RedirectResponse)
async def admin_add(
    username:     str = Form(...),
    display_name: str = Form(""),
    password:     str = Form(...),
):
    db       = get_db()
    username = username.strip()
    if not username or not password:
        return RedirectResponse("/settings/?error=empty&tab=admins", status_code=303)
    if len(password) < 8:
        return RedirectResponse("/settings/?error=short&tab=admins", status_code=303)
    if db.get_admin_by_username(username):
        return RedirectResponse("/settings/?error=taken&tab=admins", status_code=303)
    db.add_admin(username, hash_password(password), display_name=display_name)
    return RedirectResponse("/settings/?saved=1&tab=admins", status_code=303)


@router.post("/admins/{admin_id}/delete", response_class=RedirectResponse)
async def admin_delete(admin_id: int, request: Request):
    db = get_db()
    if db.admin_count() <= 1:
        return RedirectResponse("/settings/?error=last&tab=admins", status_code=303)
    if request.session.get("admin_id") == admin_id:
        return RedirectResponse("/settings/?error=self&tab=admins", status_code=303)
    db.delete_admin(admin_id)
    return RedirectResponse("/settings/?saved=1&tab=admins", status_code=303)


@router.post("/admins/{admin_id}/password", response_class=RedirectResponse)
async def admin_change_password(
    admin_id:  int,
    password:  str = Form(...),
    password2: str = Form(...),
):
    if password != password2:
        return RedirectResponse("/settings/?error=mismatch&tab=admins", status_code=303)
    if len(password) < 8:
        return RedirectResponse("/settings/?error=short&tab=admins", status_code=303)
    get_db().change_admin_password(admin_id, hash_password(password))
    return RedirectResponse("/settings/?saved=1&tab=admins", status_code=303)


@router.post("/admins/{admin_id}/pin", response_class=RedirectResponse)
async def admin_set_pin(
    admin_id: int,
    pin:      str = Form(...),
):
    pin = pin.strip()
    if not pin.isdigit() or not (4 <= len(pin) <= 6):
        return RedirectResponse("/settings/?error=badpin&tab=admins", status_code=303)
    get_db().set_admin_pin(admin_id, hash_password(pin))
    return RedirectResponse("/settings/?saved=1&tab=admins", status_code=303)


# ---------------------------------------------------------------------------
# Service restart
# ---------------------------------------------------------------------------

@router.post("/restart", response_class=HTMLResponse)
async def restart_services():
    """Schedule a service restart 2 seconds after responding."""
    async def _delayed_restart():
        await asyncio.sleep(2)
        subprocess.run(["systemctl", "--user", "restart", "smartkegerator"],     check=False)
        subprocess.run(["systemctl", "--user", "restart", "smartkegerator-web"], check=False)

    asyncio.create_task(_delayed_restart())
    return HTMLResponse(
        '<span class="text-success"><i class="bi bi-check-circle me-1"></i>Restarting in 2 s…</span>'
    )


@router.post("/reboot", response_class=HTMLResponse)
async def reboot_system():
    """Schedule a full system reboot 3 seconds after responding."""
    async def _delayed_reboot():
        await asyncio.sleep(3)
        subprocess.run(["sudo", "reboot"], check=False)

    asyncio.create_task(_delayed_reboot())
    return HTMLResponse(
        '<span class="text-warning"><i class="bi bi-power me-1"></i>Rebooting in 3 s…</span>'
    )
