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
    return templates.TemplateResponse(
        request,
        "settings.html",
        ctx(request, settings=settings, yaml_config=cfg, gpio_pins=GPIO_PINS,
            admins=admins, themes=THEMES,
            server_ip=server_ip, server_port=server_port,
            ssl_enabled=ssl_enabled, ssl_certfile=ssl_certfile, ssl_keyfile=ssl_keyfile,
            log_levels=LEVEL_LABELS, current_log_level=current_level,
            app_version=_read_version(), app_git_hash=_read_git_hash(),
            update_channel=_read_channel()),
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
    temp_sensor_power_pin: int = Form(17),
    temp_sensor_dht_pin:   int = Form(22),
):
    cfg = _read_yaml()
    cfg.setdefault("hardware", {})
    cfg["hardware"]["temp_sensor_power_pin"] = temp_sensor_power_pin
    cfg["hardware"]["temp_sensor_dht_pin"]   = temp_sensor_dht_pin
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


@router.get("/logs/{which}", response_class=HTMLResponse)
async def view_log(which: str):
    """Return the last 300 lines of a log file as pre-formatted HTML (HTMX target)."""
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
async def download_log(which: str):
    """Download the full log file."""
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
    if _CHANNEL_FILE.exists():
        v = _CHANNEL_FILE.read_text().strip()
        if v in ("master", "dev"):
            return v
    return "master"


def _write_channel(channel: str) -> None:
    try:
        _CHANNEL_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CHANNEL_FILE.write_text(channel + "\n")
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
    """HTMX endpoint — compares local commit to GitHub latest on the selected branch."""
    local_hash = _read_git_hash()
    channel    = _read_channel()
    branch     = "master" if channel == "master" else "dev"
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                f"https://api.github.com/repos/{_GITHUB_OWNER}/{_GITHUB_REPO}/commits/{branch}",
                headers={"Accept": "application/vnd.github.v3+json"},
            )
        resp.raise_for_status()
        remote_sha = resp.json().get("sha", "")[:7]
    except Exception as exc:
        return HTMLResponse(
            f'<span class="text-warning"><i class="bi bi-exclamation-triangle me-1"></i>'
            f'Could not reach GitHub: {exc}</span>'
        )

    # Fetch remote VERSION file so we can show the version number, not a commit hash
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            ver_resp = await client.get(
                f"https://raw.githubusercontent.com/{_GITHUB_OWNER}/{_GITHUB_REPO}/{branch}/src/VERSION"
            )
        remote_version = ver_resp.text.strip() if ver_resp.status_code == 200 else remote_sha
    except Exception:
        remote_version = remote_sha

    if remote_sha and local_hash != "unknown" and remote_sha == local_hash:
        return HTMLResponse(
            '<span class="text-success"><i class="bi bi-check-circle me-1"></i>Up to date.</span>'
        )
    return HTMLResponse(
        f'<span class="text-info"><i class="bi bi-arrow-down-circle me-1"></i>'
        f'Version <strong>{remote_version}</strong> available on <strong>{branch}</strong>. '
        f'Click <strong>Update Now</strong> to apply.</span>'
    )


@router.post("/update-now", response_class=HTMLResponse)
async def update_now(request: Request):
    """Run update.sh in the background and report immediately."""
    admin = request.session.get("admin_username", "unknown")
    log.warning("System update requested by admin=%s from %s", admin, request.client.host if request.client else "unknown")

    if not _UPDATE_SCRIPT.exists():
        return HTMLResponse(
            '<span class="text-danger"><i class="bi bi-x-circle me-1"></i>'
            f'Update script not found at {_UPDATE_SCRIPT}.</span>'
        )

    async def _run_update():
        await asyncio.sleep(1)
        subprocess.run(
            ["sudo", "bash", str(_UPDATE_SCRIPT)],
            check=False, env=_wayland_env(),
        )

    asyncio.create_task(_run_update())
    return HTMLResponse(
        '<span class="text-warning"><i class="bi bi-arrow-clockwise me-1"></i>'
        'Update started — services will restart automatically when complete. '
        'This page may become temporarily unreachable.</span>'
    )
