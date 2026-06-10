from __future__ import annotations

import asyncio
import glob
import subprocess
from pathlib import Path
from typing import Optional

import httpx
import yaml
from fastapi import APIRouter, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from ui.theme import THEMES
from web.auth import hash_password
import logging

from log_config import log_dir_for, tail_log, apply_level, LEVELS, LEVEL_LABELS
from web.server import get_db, get_config, get_config_path, reload_config, templates, ctx

log = logging.getLogger(__name__)

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


def _wayland_env() -> dict:
    """Build a subprocess environment that can reach the Wayland compositor."""
    import os
    env = os.environ.copy()
    env.setdefault("WAYLAND_DISPLAY", "wayland-0")
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return env


def _detect_display_output() -> str:
    """
    Ask wlr-randr which outputs are connected and return the first one found.
    Falls back to 'DSI-1' (official touchscreen) if wlr-randr isn't available
    or the compositor isn't running.
    """
    try:
        result = subprocess.run(
            ["wlr-randr"], env=_wayland_env(),
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            # Output names are the first token on non-indented lines
            if line and not line[0].isspace():
                name = line.split()[0]
                if name:
                    return name
    except Exception:
        pass
    return "DSI-1"


def _apply_display_rotation(degrees: int) -> None:
    """
    Apply a display rotation immediately via wlr-randr and persist it to the
    active compositor config so it survives a reboot.
    """
    import os, re
    home   = Path(os.path.expanduser("~"))
    t      = str(degrees)
    output = _detect_display_output()
    env    = _wayland_env()

    # Apply live — wlr-randr works for both labwc and wayfire
    try:
        subprocess.run(
            ["wlr-randr", "--output", output, "--transform", t],
            env=env, timeout=5, check=False
        )
        log.info("Applied display rotation %s° on output %s", degrees, output)
    except Exception as exc:
        log.warning("wlr-randr live rotation failed: %s", exc)

    # Persist to labwc autostart
    labwc = home / ".config/labwc/autostart"
    if labwc.exists():
        text = labwc.read_text()
        new  = re.sub(r'wlr-randr --output \S+ --transform \S+',
                      f'wlr-randr --output {output} --transform {t}', text)
        if new == text:  # entry missing — append it
            new = new.rstrip("\n") + f'\nwlr-randr --output {output} --transform {t} &\n'
        labwc.write_text(new)
        return

    # Persist to wayfire.ini
    wayfire = home / ".config/wayfire.ini"
    if wayfire.exists():
        text = wayfire.read_text()
        # Update existing [output:*] transform line regardless of output name
        new  = re.sub(r'(?m)(^\[output:[^\]]+\][^\[]*?transform\s*=\s*)\S+',
                      rf'\g<1>{t}', text)
        if new == text:
            new = new.rstrip("\n") + f'\n[output:{output}]\ntransform = {t}\n'
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
    web_cfg     = cfg.get("web", {})
    server_port = int(web_cfg.get("port", 8080))
    ssl_cfg     = web_cfg.get("ssl", {})
    ssl_enabled  = bool(ssl_cfg.get("enabled", False))
    ssl_certfile = ssl_cfg.get("certfile", "")
    ssl_keyfile  = ssl_cfg.get("keyfile", "")
    current_level = db.get_setting("log_level", "high")
    from hardware.pi_model import pi_generation
    from notifications.email_sender import PRESETS as EMAIL_PRESETS
    # Notification settings (read from DB)
    notif = {k: db.get_setting(k, v) for k, v in {
        "notif_email_enabled":       "0",
        "notif_email_preset":        "custom",
        "notif_email_smtp_host":     "",
        "notif_email_smtp_port":     "587",
        "notif_email_smtp_security": "starttls",
        "notif_email_smtp_user":     "",
        "notif_email_from":          "",
        "notif_email_to":            "",
        "notif_email_on_pour":       "0",
        "notif_email_on_keg_low":    "0",
        "notif_email_keg_low_pct":   "15",
        "notif_email_on_keg_empty":  "0",
        "notif_email_on_temp_alert":  "0",
        "notif_email_temp_alert_f":   "55",
        "notif_email_on_new_user":    "0",
        "notif_push_on_pour":        "0",
        "notif_push_on_keg_low":     "0",
        "notif_push_on_keg_empty":   "0",
        "notif_push_on_temp_alert":  "0",
    }.items()}
    return templates.TemplateResponse(
        request,
        "settings.html",
        ctx(request, settings=settings, yaml_config=cfg, gpio_pins=GPIO_PINS,
            admins=admins, themes=THEMES,
            server_ip=server_ip, server_port=server_port,
            ssl_enabled=ssl_enabled, ssl_certfile=ssl_certfile, ssl_keyfile=ssl_keyfile,
            log_levels=LEVEL_LABELS, current_log_level=current_level,
            app_version=_read_version(), app_git_hash=_read_git_hash(),
            update_channel=_read_channel(),
            notif=notif, email_presets=EMAIL_PRESETS,
            pi_gen=pi_generation()),
    )


# ---------------------------------------------------------------------------
# Appearance (name + theme)
# ---------------------------------------------------------------------------

@router.post("/appearance", response_class=RedirectResponse)
async def settings_save_appearance(
    site_name:  str           = Form("SmartKegerator"),
    theme:      str           = Form("dark_blue"),
    fullscreen: Optional[str] = Form(None),
):
    from ui.theme import THEMES as _THEMES
    cfg = _read_yaml()
    cfg.setdefault("ui", {})
    cfg["ui"]["name"]       = site_name.strip() or "SmartKegerator"
    cfg["ui"]["theme"]      = theme if theme in _THEMES else "dark_blue"
    cfg["ui"]["fullscreen"] = fullscreen is not None
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
    tap_count:        int           = Form(...),
    tap1_name:        str           = Form("Left"),
    tap1_pin:         int           = Form(23),
    tap2_name:        str           = Form("Center"),
    tap2_pin:         int           = Form(24),
    tap3_name:        str           = Form("Right"),
    tap3_pin:         int           = Form(25),
    tap4_name:        str           = Form("Tap 4"),
    tap4_pin:         int           = Form(26),
    ticks_per_liter:  int           = Form(700),
    tick_threshold:   int           = Form(3),
    end_pour_seconds: float         = Form(5.0),
    log_pours:        Optional[str] = Form(None),
):
    cfg = _read_yaml()
    cfg.setdefault("taps", {})
    cfg["taps"]["count"] = tap_count
    cfg["taps"]["tap1"]  = {"name": tap1_name, "pin": tap1_pin}
    cfg["taps"]["tap2"]  = {"name": tap2_name, "pin": tap2_pin}
    cfg["taps"]["tap3"]  = {"name": tap3_name, "pin": tap3_pin}
    cfg["taps"]["tap4"]  = {"name": tap4_name, "pin": tap4_pin}
    cfg.setdefault("hardware", {})
    cfg["hardware"]["ticks_per_liter"]  = max(1, ticks_per_liter)
    cfg["hardware"]["tick_threshold"]   = max(1, tick_threshold)
    cfg["hardware"]["end_pour_seconds"] = max(1.0, end_pour_seconds)
    cfg.setdefault("ui", {})
    cfg["ui"]["log_pours"] = log_pours is not None
    _write_yaml(cfg)
    return RedirectResponse("/settings/?saved=1&tab=taps", status_code=303)


# ---------------------------------------------------------------------------
# Camera
# ---------------------------------------------------------------------------

@router.post("/camera", response_class=RedirectResponse)
async def settings_save_camera(
    camera_index:         int           = Form(0),
    camera_width:         int           = Form(640),
    camera_height:        int           = Form(480),
    camera_use_color:     Optional[str] = Form(None),
    camera_swap_red_blue: Optional[str] = Form(None),
    camera_mirror:        Optional[str] = Form(None),
    camera_leds_pin:      int           = Form(18),
):
    cfg = _read_yaml()
    cfg.setdefault("hardware", {})
    cfg["hardware"]["camera_index"]         = camera_index
    cfg["hardware"]["camera_width"]         = camera_width
    cfg["hardware"]["camera_height"]        = camera_height
    cfg["hardware"]["camera_use_color"]     = camera_use_color is not None
    cfg["hardware"]["camera_swap_red_blue"] = camera_swap_red_blue is not None
    cfg["hardware"]["camera_mirror"]        = camera_mirror is not None
    cfg["hardware"]["camera_leds_pin"]      = camera_leds_pin
    _write_yaml(cfg)
    return RedirectResponse("/settings/?saved=1&tab=camera", status_code=303)


# ---------------------------------------------------------------------------
# Facial recognition
# ---------------------------------------------------------------------------

@router.post("/recognition", response_class=RedirectResponse)
async def settings_save_recognition(
    enabled:              Optional[str] = Form(None),
    confidence_threshold: float         = Form(0.55),
    detection_model:      str           = Form("hog"),
):
    cfg = _read_yaml()
    cfg.setdefault("recognition", {})
    cfg["recognition"]["enabled"]              = enabled is not None
    cfg["recognition"]["confidence_threshold"] = max(0.1, min(1.0, confidence_threshold))
    cfg["recognition"]["detection_model"]      = detection_model if detection_model in ("hog", "cnn") else "hog"
    _write_yaml(cfg)
    return RedirectResponse("/settings/?saved=1&tab=camera", status_code=303)


# ---------------------------------------------------------------------------
# Temperature sensors
# ---------------------------------------------------------------------------

@router.post("/sensors", response_class=RedirectResponse)
async def settings_save_sensors(
    temp_sensor_dht_pin: int = Form(22),
):
    from hardware.pi_model import pi_generation
    cfg = _read_yaml()
    cfg.setdefault("hardware", {})
    # Only save DHT22 pin on Pi 3/4 — Pi 5 uses fixed I²C, no GPIO config needed
    if pi_generation() != 5:
        cfg["hardware"]["temp_sensor_dht_pin"] = temp_sensor_dht_pin
    _write_yaml(cfg)
    return RedirectResponse("/settings/?saved=1&tab=sensors", status_code=303)


# ---------------------------------------------------------------------------
# catalog.beer API key (stored in DB, not YAML)
# ---------------------------------------------------------------------------

@router.post("/catalog-beer", response_class=RedirectResponse)
async def settings_save_catalog_beer(
    catalog_beer_api_key: str = Form(""),
):
    db = get_db()
    key = catalog_beer_api_key.strip()
    if key:
        db.set_setting("catalog_beer_api_key", key)
    return RedirectResponse("/settings/?saved=1&tab=beer-db", status_code=303)


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


@router.post("/privacy", response_class=RedirectResponse)
async def settings_save_privacy(
    require_login_for_read: Optional[str] = Form(None),
):
    """Persist web privacy options (require login to view pages)."""
    cfg = _read_yaml()
    cfg.setdefault("web", {})
    cfg["web"]["require_login_for_read"] = require_login_for_read is not None
    _write_yaml(cfg)
    return RedirectResponse("/settings/?saved=1&tab=admins", status_code=303)


# ---------------------------------------------------------------------------
# SSL certificate upload
# ---------------------------------------------------------------------------

_SSL_DIR = Path("/opt/smartkegerator/ssl")


@router.post("/upload-ssl", response_class=RedirectResponse)
async def upload_ssl(
    request:  Request,
    certfile: Optional[object] = None,
    keyfile:  Optional[object] = None,
):
    from fastapi import UploadFile
    import shutil

    _SSL_DIR.mkdir(parents=True, exist_ok=True)

    cfg = _read_yaml()
    cfg.setdefault("web", {})
    cfg["web"].setdefault("ssl", {})

    # Accept UploadFile objects from the form
    form   = await request.form()
    cert   = form.get("certfile")
    key    = form.get("keyfile")

    if cert and hasattr(cert, "filename") and cert.filename:
        dest = _SSL_DIR / "server.crt"
        with open(dest, "wb") as f:
            shutil.copyfileobj(cert.file, f)
        cfg["web"]["ssl"]["certfile"] = str(dest)
        log.info("SSL certificate uploaded to %s", dest)

    if key and hasattr(key, "filename") and key.filename:
        dest = _SSL_DIR / "server.key"
        dest.chmod(0o600) if dest.exists() else None
        with open(dest, "wb") as f:
            shutil.copyfileobj(key.file, f)
        try:
            dest.chmod(0o600)
        except Exception:
            pass
        cfg["web"]["ssl"]["keyfile"] = str(dest)
        log.info("SSL key uploaded to %s", dest)

    _write_yaml(cfg)
    return RedirectResponse("/settings/?saved=1&tab=admins", status_code=303)


@router.get("/ssl-info", response_class=HTMLResponse)
async def ssl_info(request: Request):
    """HTMX endpoint — returns installed certificate details."""
    cfg      = _read_yaml()
    certfile = cfg.get("web", {}).get("ssl", {}).get("certfile", "")
    if not certfile or not Path(certfile).exists():
        return HTMLResponse(
            '<div class="text-muted small py-1">'
            '<i class="bi bi-shield-slash me-1"></i>No certificate installed.</div>'
        )
    try:
        result = subprocess.run(
            ["openssl", "x509", "-in", certfile, "-noout",
             "-subject", "-issuer", "-startdate", "-enddate"],
            capture_output=True, text=True, timeout=10,
        )
        # Parse: each line is "key=value" where value may contain "="
        parsed: dict[str, str] = {}
        for line in result.stdout.splitlines():
            if "=" in line:
                key, _, val = line.partition("=")
                parsed[key.strip()] = val.strip()

        subject    = parsed.get("subject",   "—")
        issuer     = parsed.get("issuer",    "—")
        not_before = parsed.get("notBefore", "—")
        not_after  = parsed.get("notAfter",  "—")

        # Extract CN for a friendly "issued to" name
        def _cn(field: str) -> str:
            for part in field.split(","):
                part = part.strip()
                if part.upper().startswith("CN"):
                    return part.split("=", 1)[-1].strip()
            return field

        issued_to  = _cn(subject)
        issued_by  = _cn(issuer)
        self_signed = issued_to == issued_by or "Internet Widgits" in issuer
        cert_type  = "Self-signed" if self_signed else "CA-signed (Let's Encrypt / CA)"

        # Days remaining
        from datetime import datetime as _dt
        days_html = ""
        try:
            expiry = _dt.strptime(not_after, "%b %d %H:%M:%S %Y %Z")
            days   = (expiry - _dt.utcnow()).days
            if days < 0:
                days_html = f'<span class="badge bg-danger ms-2">EXPIRED {abs(days)}d ago</span>'
            elif days <= 14:
                days_html = f'<span class="badge bg-warning text-dark ms-2">{days}d remaining</span>'
            elif days <= 30:
                days_html = f'<span class="badge bg-info text-dark ms-2">{days}d remaining</span>'
            else:
                days_html = f'<span class="badge bg-success ms-2">{days}d remaining</span>'
        except Exception:
            pass

        icon  = "shield-check" if not self_signed else "shield-exclamation"
        color = "success" if not self_signed else "warning"

        return HTMLResponse(f"""
<div class="border rounded p-3" style="background:var(--sk-bg);">
  <div class="d-flex align-items-center gap-2 mb-2">
    <i class="bi bi-{icon} text-{color} fs-5"></i>
    <strong>Installed Certificate</strong>
    <span class="badge bg-secondary">{cert_type}</span>
  </div>
  <div class="row g-1 small">
    <div class="col-sm-3 text-muted">Issued to</div>
    <div class="col-sm-9 font-monospace">{issued_to}</div>
    <div class="col-sm-3 text-muted">Issued by</div>
    <div class="col-sm-9 font-monospace">{issued_by}</div>
    <div class="col-sm-3 text-muted">Valid from</div>
    <div class="col-sm-9">{not_before}</div>
    <div class="col-sm-3 text-muted">Expires</div>
    <div class="col-sm-9">{not_after}{days_html}</div>
  </div>
</div>""")
    except Exception as exc:
        return HTMLResponse(
            f'<div class="text-warning small"><i class="bi bi-exclamation-triangle me-1"></i>'
            f'Could not read certificate: {exc}</div>'
        )


# ---------------------------------------------------------------------------
# Web server port
# ---------------------------------------------------------------------------

@router.post("/server-port", response_class=RedirectResponse)
async def settings_save_server_port(
    port:         int           = Form(8080),
    ssl_enabled:  Optional[str] = Form(None),
    ssl_certfile: str           = Form(""),
    ssl_keyfile:  str           = Form(""),
):
    cfg = _read_yaml()
    cfg.setdefault("web", {})
    # Privileged ports: only 80 (HTTP) or 443 (HTTPS) are permitted below 1024
    if port < 1024:
        ssl_on = ssl_enabled is not None
        if port == 443 and ssl_on:
            pass  # allowed
        elif port == 80 and not ssl_on:
            pass  # allowed
        else:
            port = 8080  # reject other privileged ports
    cfg["web"]["port"] = max(1, min(65535, port))
    cfg["web"].setdefault("ssl", {})
    cfg["web"]["ssl"]["enabled"]  = ssl_enabled is not None
    cfg["web"]["ssl"]["certfile"] = ssl_certfile.strip()
    cfg["web"]["ssl"]["keyfile"]  = ssl_keyfile.strip()
    _write_yaml(cfg)

    # Restart web service so the new port/SSL takes effect immediately
    async def _restart():
        await asyncio.sleep(1)
        subprocess.run(["systemctl", "--user", "restart", "smartkegerator-web"], check=False, env=_wayland_env())

    asyncio.create_task(_restart())
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


@router.post("/admins/promote", response_class=RedirectResponse)
async def admin_promote(
    user_id:  int = Form(...),
    username: str = Form(...),
    password: str = Form(...),
):
    db       = get_db()
    username = username.strip()
    if not username or not password:
        return RedirectResponse("/settings/?error=empty&tab=admins", status_code=303)
    if len(password) < 8:
        return RedirectResponse("/settings/?error=short&tab=admins", status_code=303)
    if db.get_admin_by_username(username):
        return RedirectResponse("/settings/?error=taken&tab=admins", status_code=303)
    user = db.get_user(user_id)
    if not user:
        return RedirectResponse("/settings/?error=nouser&tab=admins", status_code=303)
    if db.is_user_admin(user_id):
        return RedirectResponse("/settings/?error=already&tab=admins", status_code=303)
    db.promote_user_to_admin(user_id, username, hash_password(password))
    return RedirectResponse("/settings/?saved=1&tab=admins", status_code=303)


@router.post("/admins/demote", response_class=RedirectResponse)
async def admin_demote(request: Request, admin_id: int = Form(...)):
    db = get_db()
    if db.admin_count() <= 1:
        return RedirectResponse("/settings/?error=last&tab=admins", status_code=303)
    if request.session.get("admin_id") == admin_id:
        return RedirectResponse("/settings/?error=self&tab=admins", status_code=303)
    db.delete_admin(admin_id)
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
    request:   Request,
    admin_id:  int,
    password:  str = Form(...),
    password2: str = Form(...),
):
    if password != password2:
        return RedirectResponse("/settings/?error=mismatch&tab=admins", status_code=303)
    if len(password) < 8:
        return RedirectResponse("/settings/?error=short&tab=admins", status_code=303)
    new_hash = hash_password(password)
    get_db().change_admin_password(admin_id, new_hash)
    # Changing the password revokes that admin's sessions and API tokens
    # (they carry a fingerprint of the old hash). When changing our own
    # password, refresh the fingerprint so we stay logged in here.
    if request.session.get("admin_id") == admin_id:
        from web.auth import credential_fingerprint
        request.session["pwd"] = credential_fingerprint(new_hash)
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

@router.post("/ping", response_class=HTMLResponse)
async def session_ping(request: Request):
    """Refresh the server-side session timestamp to prevent timeout."""
    import time as _t
    if request.session.get("admin_username"):
        request.session["login_time"] = _t.time()
    return HTMLResponse("", status_code=204)


@router.post("/restart", response_class=HTMLResponse)
async def restart_services(request: Request):
    """Schedule a service restart 2 seconds after responding."""
    admin = request.session.get("admin_username", "unknown")
    log.warning("Service restart requested by admin=%s from %s", admin, request.client.host if request.client else "unknown")

    async def _delayed_restart():
        await asyncio.sleep(2)
        env = _wayland_env()
        subprocess.run(["systemctl", "--user", "restart", "smartkegerator"],     check=False, env=env)
        subprocess.run(["systemctl", "--user", "restart", "smartkegerator-web"], check=False, env=env)

    asyncio.create_task(_delayed_restart())
    return HTMLResponse(
        '<span class="text-success"><i class="bi bi-check-circle me-1"></i>Restarting in 2 s…</span>'
    )


@router.post("/reboot", response_class=HTMLResponse)
async def reboot_system(request: Request):
    """Schedule a full system reboot 3 seconds after responding."""
    admin = request.session.get("admin_username", "unknown")
    log.warning("System reboot requested by admin=%s from %s", admin, request.client.host if request.client else "unknown")

    async def _delayed_reboot():
        await asyncio.sleep(3)
        subprocess.run(["sudo", "reboot"], check=False)

    asyncio.create_task(_delayed_reboot())
    return HTMLResponse(
        '<span class="text-warning"><i class="bi bi-power me-1"></i>Rebooting in 3 s…</span>'
    )


@router.post("/shutdown", response_class=HTMLResponse)
async def shutdown_services(request: Request):
    """Stop both services without restarting them — returns desktop."""
    admin = request.session.get("admin_username", "unknown")
    log.warning("Service shutdown requested by admin=%s from %s", admin, request.client.host if request.client else "unknown")

    async def _delayed_shutdown():
        await asyncio.sleep(2)
        env = _wayland_env()
        subprocess.run(["systemctl", "--user", "stop", "smartkegerator"],     check=False, env=env)
        subprocess.run(["systemctl", "--user", "stop", "smartkegerator-web"], check=False, env=env)

    asyncio.create_task(_delayed_shutdown())
    return HTMLResponse(
        '<span class="text-secondary"><i class="bi bi-stop-circle me-1"></i>'
        'Services stopping in 2 s — this page will become unreachable.</span>'
    )


# ---------------------------------------------------------------------------
# Log level
# ---------------------------------------------------------------------------

@router.post("/log-level", response_class=RedirectResponse)
async def settings_save_log_level(level: str = Form("high")):
    if level not in LEVELS:
        level = "high"
    get_db().set_setting("log_level", level)
    apply_level(level)   # apply to web server immediately
    return RedirectResponse("/settings/?saved=1&tab=admins", status_code=303)


# ---------------------------------------------------------------------------
# Application logs
# ---------------------------------------------------------------------------

_VALID_LOGS = {"gui", "web"}


def _require_admin(request: Request) -> bool:
    return bool(request.session.get("admin_username"))


@router.get("/logs/{which}", response_class=HTMLResponse)
async def view_log(which: str, request: Request):
    """Return the last 300 lines of a log file as pre-formatted HTML (HTMX target)."""
    if not _require_admin(request):
        return HTMLResponse("<span class='text-danger'>Admin login required.</span>", status_code=403)
    if which not in _VALID_LOGS:
        return HTMLResponse("<span class='text-danger'>Unknown log.</span>")
    log_file = log_dir_for(get_config()) / f"smartkegerator-{which}.log"
    content  = tail_log(log_file, lines=300)
    escaped  = content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return HTMLResponse(
        f'<pre class="mb-0 small" style="white-space:pre-wrap;word-break:break-all;">'
        f'{escaped}</pre>'
    )


@router.get("/logs/{which}/download")
async def download_log(which: str, request: Request):
    """Download the full log file — admin only."""
    if not _require_admin(request):
        from fastapi.responses import RedirectResponse as _RR
        return _RR(f"/admin/login?next=/settings/?tab=admins", status_code=303)
    if which not in _VALID_LOGS:
        return HTMLResponse("Unknown log.", status_code=404)
    log_file = log_dir_for(get_config()) / f"smartkegerator-{which}.log"
    if not log_file.exists():
        return HTMLResponse("Log file not found.", status_code=404)
    return FileResponse(
        str(log_file),
        media_type="text/plain",
        filename=log_file.name,
    )


# ---------------------------------------------------------------------------
# Version / Updates
# ---------------------------------------------------------------------------

_GITHUB_OWNER   = "Namoh21"
_GITHUB_REPO    = "SmartKegerator"
_UPDATE_SCRIPT  = Path("/opt/smartkegerator/src/scripts/update.sh")
_CHANNEL_FILE   = Path("/opt/smartkegerator/update_channel")


def _read_channel() -> str:
    # DB is the primary store; file is a fallback written for update.sh
    try:
        v = get_db().get_setting("update_channel", "")
        if v in ("master", "dev"):
            return v
    except Exception:
        pass
    if _CHANNEL_FILE.exists():
        v = _CHANNEL_FILE.read_text().strip()
        if v in ("master", "dev"):
            return v
    return "master"


def _write_channel(channel: str) -> None:
    # DB is the authoritative store — update.sh reads this first.
    try:
        get_db().set_setting("update_channel", channel)
        log.info("update_channel saved to DB: %s", channel)
    except Exception as exc:
        log.error("Could not save update_channel to DB: %s", exc)
    # Best-effort sync to file so update.sh has it even without sqlite3.
    # update.sh chowns this file to REAL_USER after each run so we can write it.
    try:
        _CHANNEL_FILE.write_text(channel + "\n")
        log.info("update_channel file updated: %s", _CHANNEL_FILE)
    except PermissionError:
        log.warning(
            "Cannot write %s (owned by root — update.sh will fix ownership on next run). "
            "DB value '%s' will be used by update.sh.", _CHANNEL_FILE, channel,
        )
    except Exception as exc:
        log.warning("Could not write channel file: %s", exc)


def _read_version() -> str:
    version_file = Path(__file__).parent.parent.parent / "VERSION"
    if version_file.exists():
        return version_file.read_text().strip()
    return "unknown"


def _read_git_hash() -> str:
    hash_file = Path("/opt/smartkegerator/GIT_HASH")
    if hash_file.exists():
        v = hash_file.read_text().strip()
        if v:
            return v
    return "unknown"


@router.get("/version", response_class=HTMLResponse)
async def version_info(request: Request):
    """HTMX endpoint — returns current version info snippet."""
    if not _require_admin(request):
        return HTMLResponse("", status_code=403)
    version = _read_version()
    git_hash = _read_git_hash()
    return HTMLResponse(
        f'<span class="fw-semibold text-accent">{version}</span>'
        f'<span class="text-muted small ms-2">({git_hash})</span>'
    )


@router.post("/update-channel", response_class=HTMLResponse)
async def save_update_channel(channel: str = Form("master")):
    """HTMX endpoint — saves the update channel preference."""
    if channel not in ("master", "dev"):
        channel = "master"
    _write_channel(channel)
    label = "Stable (master)" if channel == "master" else "Dev (unstable)"
    return HTMLResponse(
        f'<span class="text-success"><i class="bi bi-check-circle me-1"></i>Channel set to <strong>{label}</strong>.</span>'
    )


@router.get("/check-updates", response_class=HTMLResponse)
async def check_updates(request: Request):
    """HTMX endpoint — compares local VERSION file to remote branch on GitHub."""
    if not _require_admin(request):
        return HTMLResponse("", status_code=403)
    channel       = _read_channel()
    branch        = "master" if channel == "master" else "dev"
    local_version = _read_version()

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                f"https://raw.githubusercontent.com/{_GITHUB_OWNER}/{_GITHUB_REPO}/{branch}/src/VERSION",
                headers={"Cache-Control": "no-cache"},
            )
        resp.raise_for_status()
        remote_version = resp.text.strip()
    except Exception as exc:
        return HTMLResponse(
            f'<span class="text-warning"><i class="bi bi-exclamation-triangle me-1"></i>'
            f'Could not reach GitHub: {exc}</span>'
        )

    if remote_version == local_version:
        return HTMLResponse(
            f'<span class="text-success"><i class="bi bi-check-circle me-1"></i>'
            f'Up to date — v{local_version} on <strong>{branch}</strong>.</span>'
        )
    return HTMLResponse(
        f'<span class="text-info"><i class="bi bi-arrow-down-circle me-1"></i>'
        f'Version <strong>{remote_version}</strong> available on <strong>{branch}</strong> '
        f'(current: v{local_version}). Click <strong>Update Now</strong> to apply.</span>'
    )


_UPDATE_LOG  = Path("/tmp/sk-update.log")
_UPDATE_DONE = Path("/tmp/sk-update.done")


def _run_update_thread() -> None:
    """Run update.sh in a background thread, writing output to a log file."""
    import time as _t
    _t.sleep(0.5)
    try:
        with open(_UPDATE_LOG, "wb") as f:
            proc = subprocess.Popen(
                ["sudo", "/bin/bash", str(_UPDATE_SCRIPT)],
                stdout=f,
                stderr=subprocess.STDOUT,
                env=_wayland_env(),
            )
            proc.wait()
    except Exception as exc:
        try:
            with open(_UPDATE_LOG, "ab") as f:
                f.write(f"\n[ERROR] {exc}\n".encode())
        except Exception:
            pass
    # Write done marker — may not be read if service restarts first
    try:
        _UPDATE_DONE.write_text("done")
    except Exception:
        pass


@router.post("/update-now", response_class=HTMLResponse)
async def update_now(request: Request):
    """Start update.sh in a thread and return an SSE log panel."""
    import threading
    admin = request.session.get("admin_username", "unknown")
    log.warning("System update requested by admin=%s from %s", admin,
                request.client.host if request.client else "unknown")

    if not _UPDATE_SCRIPT.exists():
        return HTMLResponse(
            '<span class="text-danger"><i class="bi bi-x-circle me-1"></i>'
            f'Update script not found at {_UPDATE_SCRIPT}.</span>'
        )

    for p in (_UPDATE_LOG, _UPDATE_DONE):
        try:
            p.unlink()
        except FileNotFoundError:
            pass

    threading.Thread(target=_run_update_thread, daemon=True).start()

    return templates.TemplateResponse(
        request, "partials/update_log.html", ctx(request),
    )


@router.get("/update-log", response_class=HTMLResponse)
async def update_log_poll(request: Request):
    """HTMX polling endpoint — returns current update log content as escaped HTML."""
    if not _require_admin(request):
        return HTMLResponse("", status_code=403)

    content = ""
    if _UPDATE_LOG.exists():
        content = _UPDATE_LOG.read_bytes().decode(errors="replace")

    escaped = content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    done = _UPDATE_DONE.exists()
    if done:
        try:
            _UPDATE_DONE.unlink()
        except Exception:
            pass

    resp = HTMLResponse(escaped or "Starting update…")
    if done:
        resp.headers["HX-Trigger"] = "updateComplete"
    return resp


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

@router.post("/notifications", response_class=RedirectResponse)
async def settings_save_notifications(
    # Email master switch
    notif_email_enabled:      Optional[str] = Form(None),
    notif_email_preset:       str           = Form("custom"),
    notif_email_smtp_host:    str           = Form(""),
    notif_email_smtp_port:    str           = Form("587"),
    notif_email_smtp_security:str           = Form("starttls"),
    notif_email_smtp_user:    str           = Form(""),
    notif_email_smtp_password:str           = Form(""),
    notif_email_from:         str           = Form(""),
    notif_email_to:           str           = Form(""),
    # Email event toggles
    notif_email_on_pour:      Optional[str] = Form(None),
    notif_email_on_keg_low:   Optional[str] = Form(None),
    notif_email_keg_low_pct:  str           = Form("15"),
    notif_email_on_keg_empty: Optional[str] = Form(None),
    notif_email_on_temp_alert: Optional[str] = Form(None),
    notif_email_temp_alert_f:  str           = Form("55"),
    notif_email_on_new_user:   Optional[str] = Form(None),
    # Push event toggles (server-side preferences)
    notif_push_on_pour:       Optional[str] = Form(None),
    notif_push_on_keg_low:    Optional[str] = Form(None),
    notif_push_on_keg_empty:  Optional[str] = Form(None),
    notif_push_on_temp_alert: Optional[str] = Form(None),
):
    db = get_db()
    def _bool(v): return "1" if v is not None else "0"

    db.set_setting("notif_email_enabled",       _bool(notif_email_enabled))
    db.set_setting("notif_email_preset",         notif_email_preset.strip())
    db.set_setting("notif_email_smtp_host",      notif_email_smtp_host.strip())
    db.set_setting("notif_email_smtp_port",      notif_email_smtp_port.strip() or "587")
    db.set_setting("notif_email_smtp_security",  notif_email_smtp_security.strip())
    db.set_setting("notif_email_smtp_user",      notif_email_smtp_user.strip())
    db.set_setting("notif_email_from",           notif_email_from.strip())
    db.set_setting("notif_email_to",             notif_email_to.strip())
    db.set_setting("notif_email_on_pour",        _bool(notif_email_on_pour))
    db.set_setting("notif_email_on_keg_low",     _bool(notif_email_on_keg_low))
    db.set_setting("notif_email_keg_low_pct",    notif_email_keg_low_pct.strip() or "15")
    db.set_setting("notif_email_on_keg_empty",   _bool(notif_email_on_keg_empty))
    db.set_setting("notif_email_on_temp_alert",  _bool(notif_email_on_temp_alert))
    db.set_setting("notif_email_temp_alert_f",   notif_email_temp_alert_f.strip() or "55")
    db.set_setting("notif_email_on_new_user",    _bool(notif_email_on_new_user))
    db.set_setting("notif_push_on_pour",         _bool(notif_push_on_pour))
    db.set_setting("notif_push_on_keg_low",      _bool(notif_push_on_keg_low))
    db.set_setting("notif_push_on_keg_empty",    _bool(notif_push_on_keg_empty))
    db.set_setting("notif_push_on_temp_alert",   _bool(notif_push_on_temp_alert))
    # Only overwrite password if a new one was submitted
    if notif_email_smtp_password.strip():
        db.set_setting("notif_email_smtp_password", notif_email_smtp_password.strip())

    return RedirectResponse("/settings/?saved=1&tab=notifications", status_code=303)


@router.post("/notifications/test-email", response_class=HTMLResponse)
async def test_email(request: Request):
    """Send a test email with current SMTP settings — admin only."""
    if not _require_admin(request):
        return HTMLResponse('<span class="text-danger">Not authorised.</span>', status_code=403)

    from notifications.email_sender import send_email, _wrap

    db       = get_db()
    host     = db.get_setting("notif_email_smtp_host", "")
    port_str = db.get_setting("notif_email_smtp_port", "587")
    security = db.get_setting("notif_email_smtp_security", "starttls")
    user     = db.get_setting("notif_email_smtp_user", "")
    password = db.get_setting("notif_email_smtp_password", "")
    from_    = db.get_setting("notif_email_from", "") or user
    to       = db.get_setting("notif_email_to", "")

    if not host or not to:
        return HTMLResponse(
            '<span class="text-warning"><i class="bi bi-exclamation-triangle me-1"></i>'
            'SMTP host and recipient address are required. Save settings first.</span>'
        )

    try:
        port = int(port_str)
    except ValueError:
        port = 587

    html = _wrap(
        "<h2 style='margin-top:0;color:#1a1a3e;'>Test Notification</h2>"
        "<p>If you're reading this, your SmartKegerator email notifications are configured correctly.</p>"
    )
    text = "SmartKegerator test notification — email is configured correctly."

    ok, err = send_email(
        host=host, port=port, username=user, password=password,
        security=security, from_address=from_, to_address=to,
        subject="✅ SmartKegerator — Test Notification",
        body_html=html, body_text=text,
    )

    if ok:
        return HTMLResponse(
            f'<span class="text-success"><i class="bi bi-check-circle me-1"></i>'
            f'Test email sent to <strong>{to}</strong>.</span>'
        )
    return HTMLResponse(
        f'<span class="text-danger"><i class="bi bi-x-circle me-1"></i>'
        f'{err}</span>'
    )
