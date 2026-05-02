#!/usr/bin/env bash
# =============================================================================
# SmartKegerator installer — Raspberry Pi OS Bookworm / Trixie (64-bit)
#
# Tested on:
#   • Raspberry Pi 5  (4 GB / 8 GB)  — Pi OS Bookworm or Trixie
#   • Raspberry Pi 4  (2 GB / 4 GB)  — Pi OS Bookworm or Trixie
#   • Raspberry Pi 3B / 3B+  (1 GB)  — Pi OS Bookworm or Trixie  ← low-mem path
#
# Run once on a fresh Pi:
#   chmod +x install.sh && sudo ./install.sh
#
# What this does:
#   1. Detects available RAM and creates a temporary swap file if < 1.5 GB
#      (required to compile dlib without OOM on Pi 3 / 1 GB models)
#   2. Installs system packages via apt (OpenCV, PyQt6, gpiod, etc.)
#   3. Creates a Python venv and installs pip packages into it
#   4. Creates the data/photo/video directory tree
#   5. Installs systemd user services and compositor autostart entry
#   6. Runs hardware setup (1-Wire, GPIO, screen blanking, rotation)
#
# Supports both Wayfire (Bookworm default) and labwc (Trixie default).
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }
section() { echo -e "\n${GREEN}── $* ──${NC}"; }

# ---------------------------------------------------------------------------
# Must run as root (apt requires it); detect the real user
# ---------------------------------------------------------------------------
[[ $EUID -eq 0 ]] || error "Run with sudo:  sudo ./install.sh"
REAL_USER="${SUDO_USER:-pi}"
REAL_HOME=$(getent passwd "${REAL_USER}" | cut -d: -f6)
info "Installing for user: ${REAL_USER}  (home: ${REAL_HOME})"

# ---------------------------------------------------------------------------
# Detect available RAM — drives swap and build parallelism decisions
# ---------------------------------------------------------------------------
MEM_MB=$(awk '/MemTotal/ { printf "%d", $2/1024 }' /proc/meminfo)
PI_MODEL=$(tr -d '\0' < /proc/device-tree/model 2>/dev/null || echo "Unknown")
info "Hardware: ${PI_MODEL}"
info "RAM: ${MEM_MB} MB"

# Threshold: anything ≤ 1.5 GB (covers Pi 3 / 1 GB and Pi Zero 2 W / 512 MB)
if [[ ${MEM_MB} -lt 1536 ]]; then
    LOW_MEM=true
    warn "Low-memory system detected (${MEM_MB} MB)."
    warn "A temporary swap file will be created for the dlib build and removed afterwards."
    warn "Face recognition will work but will be slower than on Pi 4/5."
else
    LOW_MEM=false
fi

# ---------------------------------------------------------------------------
# Configurable paths — edit these if you put things elsewhere
# ---------------------------------------------------------------------------
INSTALL_DIR="/opt/smartkegerator"
SRC_DIR="${INSTALL_DIR}/src"
VENV_DIR="${INSTALL_DIR}/venv"
DATA_DIR="${INSTALL_DIR}/data"
PHOTOS_DIR="${INSTALL_DIR}/photos"
VIDEOS_DIR="${INSTALL_DIR}/videos"
LOGOS_DIR="${INSTALL_DIR}/logos"
DB_PATH="${DATA_DIR}/smartkegerator.db"
PYTHON="${VENV_DIR}/bin/python3"

# ---------------------------------------------------------------------------
# 1. Desktop environment (Pi OS Lite only)
#    Full Pi OS already has Wayfire or labwc.  Lite has neither — install
#    the matching minimal compositor and wire up TTY autologin so the
#    kiosk display comes up on boot without a full desktop environment.
# ---------------------------------------------------------------------------
section "Desktop environment check"

OS_CODENAME=$(. /etc/os-release 2>/dev/null && echo "${VERSION_CODENAME:-bookworm}")

if command -v wayfire &>/dev/null || command -v labwc &>/dev/null; then
    info "Wayland compositor already present — full Pi OS detected, skipping Lite setup."
else
    warn "No Wayland compositor found — Pi OS Lite detected."
    info "OS: ${OS_CODENAME} — installing minimal kiosk compositor..."

    # Choose compositor to match the OS generation
    case "${OS_CODENAME}" in
        trixie|forky) KIOSK_COMPOSITOR="labwc" ;;
        *)            KIOSK_COMPOSITOR="wayfire" ;;
    esac

    apt-get install -y \
        "${KIOSK_COMPOSITOR}" \
        seatd \
        fonts-dejavu-core \
        libinput-tools \
        xdg-user-dirs \
        dbus-user-session

    # Grant the user access to display hardware
    usermod -aG video,input "${REAL_USER}"
    getent group seat &>/dev/null && usermod -aG seat "${REAL_USER}" || true

    # seatd provides unprivileged Wayland seat access (replaces suid wrappers)
    systemctl enable seatd 2>/dev/null || true

    # TTY1 autologin — no display manager needed
    AUTOLOGIN_DIR="/etc/systemd/system/getty@tty1.service.d"
    mkdir -p "${AUTOLOGIN_DIR}"
    cat > "${AUTOLOGIN_DIR}/autologin.conf" << EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin ${REAL_USER} --noclear %I \$TERM
Type=idle
EOF
    systemctl daemon-reload
    info "TTY1 autologin configured for ${REAL_USER}."

    # Start compositor from .bash_profile when logging in on TTY1.
    # The compositor will pick up its autostart entry (added in section 7).
    PROFILE="${REAL_HOME}/.bash_profile"
    if ! grep -q "WAYLAND_DISPLAY" "${PROFILE}" 2>/dev/null; then
        cat >> "${PROFILE}" << PROFILE_EOF

# SmartKegerator kiosk — start Wayland compositor on TTY1
if [[ -z "\${WAYLAND_DISPLAY:-}" ]] && [[ "\$(tty)" == "/dev/tty1" ]]; then
    export XDG_RUNTIME_DIR="\${XDG_RUNTIME_DIR:-/run/user/\$(id -u)}"
    exec ${KIOSK_COMPOSITOR}
fi
PROFILE_EOF
        chown "${REAL_USER}:${REAL_USER}" "${PROFILE}"
        info "Added ${KIOSK_COMPOSITOR} launch to ${PROFILE}."
    fi

    info "Lite compositor setup complete. The GUI will appear on reboot."
fi

# ---------------------------------------------------------------------------
# 2. System packages
# ---------------------------------------------------------------------------
section "System packages"

apt-get update -qq

# Prerequisites (may be missing on Lite images)
apt-get install -y git curl ca-certificates

# Core Python + build tools
apt-get install -y \
    python3-pip \
    python3-venv \
    cmake \
    build-essential \
    libopenblas-dev \
    libhdf5-dev \
    liblapack-dev \
    gfortran \
    python3-dev

# OpenCV (system build — much faster than pip on Pi)
apt-get install -y \
    python3-opencv \
    libopencv-dev

# PyQt6 + Wayland platform plugin
apt-get install -y \
    python3-pyqt6 \
    python3-pyqt6.qtmultimedia \
    qt6-base-dev \
    qt6-wayland

# wlr-randr — output rotation for labwc (Trixie) and other wlroots compositors
apt-get install -y wlr-randr 2>/dev/null || \
    warn "wlr-randr not available — display rotation will be configured via compositor config"

# GPIO (modern chardev API — replaces unmaintained wiringPi)
apt-get install -y \
    gpiod \
    libgpiod-dev \
    python3-libgpiod

# YAML
apt-get install -y python3-yaml

# authbind — lets non-root user services bind to ports 80 and 443
apt-get install -y authbind

# picamera2 — Pi Camera Module support on Trixie / Bookworm
# (system package; the venv inherits it via --system-site-packages)
apt-get install -y python3-picamera2 2>/dev/null || \
    warn "python3-picamera2 not available — Pi Camera will fall back to OpenCV only"

info "System packages installed."

# ---------------------------------------------------------------------------
# Low-memory swap — created before the dlib build, removed afterwards.
# fallocate is fastest; fall back to dd on filesystems that don't support it.
# ---------------------------------------------------------------------------
# Ensure install dir exists before we try to write the swap file into it
mkdir -p "${INSTALL_DIR}"
BUILD_SWAP="${INSTALL_DIR}/build-swap"

if [[ "${LOW_MEM}" == "true" ]]; then
    section "Temporary swap file for low-memory build"
    if swapon --show | grep -qF "${BUILD_SWAP}"; then
        info "Build swap already active."
    else
        if [[ ! -f "${BUILD_SWAP}" ]]; then
            info "Allocating 2 GB swap file at ${BUILD_SWAP}..."
            fallocate -l 2G "${BUILD_SWAP}" 2>/dev/null || \
                dd if=/dev/zero of="${BUILD_SWAP}" bs=1M count=2048 status=progress
            chmod 600 "${BUILD_SWAP}"
            mkswap "${BUILD_SWAP}" -q
        fi
        swapon "${BUILD_SWAP}"
        info "Swap active: $(free -h | awk '/Swap/{print $2}') total."
    fi
fi

# ---------------------------------------------------------------------------
# 2. Python virtual environment
# ---------------------------------------------------------------------------
section "Python virtual environment"

# /opt is root-owned — create the install dir now so the real user can
# write into it (venv, wheel cache, etc.)
mkdir -p "${INSTALL_DIR}"
chown "${REAL_USER}:${REAL_USER}" "${INSTALL_DIR}"

# --system-site-packages lets the venv use apt-installed packages
# (python3-opencv, python3-pyqt6, python3-libgpiod, python3-yaml)
if [[ ! -d "${VENV_DIR}" ]]; then
    sudo -u "${REAL_USER}" python3 -m venv --system-site-packages "${VENV_DIR}"
    info "Virtual environment created at ${VENV_DIR}"
else
    info "Virtual environment already exists — skipping creation."
fi

PIP="${PYTHON} -m pip install --quiet --quiet --retries 5 --timeout 60"

# Upgrade pip inside the venv first
sudo -u "${REAL_USER}" ${PIP} --upgrade pip

# ---------------------------------------------------------------------------
# 3. Python pip packages (installed into venv)
# ---------------------------------------------------------------------------
section "Python pip packages"

# Wheel cache — persists compiled wheels across pip cache clears.
# Back this directory up before reimaging to skip the dlib build next time:
#   cp -r /opt/smartkegerator/wheel-cache /media/usb/
# Restore after git clone:
#   sudo cp -r /media/usb/wheel-cache /opt/smartkegerator/
WHEEL_CACHE="${INSTALL_DIR}/wheel-cache"
sudo -u "${REAL_USER}" mkdir -p "${WHEEL_CACHE}"

# dlib + face-recognition — only needed when recognition.enabled: true
# Check config (may not exist yet if this is a first install; default enabled)
RECOGNITION_ENABLED="true"
if [[ -f "${SRC_DIR}/config.yaml" ]]; then
    if grep -qE "^\s*enabled:\s*false" "${SRC_DIR}/config.yaml"; then
        RECOGNITION_ENABLED="false"
    fi
fi

if [[ "${RECOGNITION_ENABLED}" == "false" ]]; then
    warn "recognition.enabled is false — skipping dlib build."
    warn "Set recognition.enabled: true in config.yaml and re-run to enable later."
elif sudo -u "${REAL_USER}" ${PYTHON} -c "import dlib" 2>/dev/null; then
    info "dlib already installed — skipping build."
elif ls "${WHEEL_CACHE}"/dlib-*.whl &>/dev/null; then
    info "Installing dlib from wheel cache (fast)..."
    sudo -u "${REAL_USER}" ${PIP} --find-links "${WHEEL_CACHE}" dlib
    info "dlib installed from cache."
else
    # Attempt to download a pre-built wheel from GitHub Releases.
    # The wheel filename encodes the dlib version, Python ABI tag, and CPU
    # architecture — so the same URL works on any 64-bit Pi OS image without
    # any configuration.  Falls back to building from source if unavailable.
    DLIB_VERSION="20.0.1"
    PY_TAG=$(${PYTHON} -c "import sys; print(f'cp{sys.version_info.major}{sys.version_info.minor}')")
    ARCH=$(uname -m)   # aarch64 on 64-bit Pi OS
    WHEEL_NAME="dlib-${DLIB_VERSION}-${PY_TAG}-${PY_TAG}-linux_${ARCH}.whl"
    WHEEL_URL="https://github.com/Namoh21/SmartKegerator/releases/download/dlib-wheels/${WHEEL_NAME}"
    WHEEL_PATH="${WHEEL_CACHE}/${WHEEL_NAME}"

    info "Trying to download pre-built dlib wheel..."
    info "  ${WHEEL_URL}"
    if curl -fsSL --connect-timeout 10 -o "${WHEEL_PATH}" "${WHEEL_URL}" 2>/dev/null; then
        chown "${REAL_USER}:${REAL_USER}" "${WHEEL_PATH}"
        info "Downloaded ${WHEEL_NAME} — installing..."
        info "Unpacking and linking dlib wheel — this can take 5-10 minutes on Pi 3/4, please wait..."
        sudo -u "${REAL_USER}" ${PYTHON} -m pip install --find-links "${WHEEL_CACHE}" --no-index dlib
        info "dlib installed from pre-built wheel."
    else
        rm -f "${WHEEL_PATH}"   # remove partial download
        warn "Pre-built wheel not available — building dlib from source."
        if [[ "${LOW_MEM}" == "true" ]]; then
            info "Low-memory mode: single-threaded build (~60-90 min on Pi 3)."
            BUILD_JOBS=1
        else
            info "This takes ~10-15 min on Pi 5, ~25-30 min on Pi 4."
            BUILD_JOBS=$(nproc)
        fi
        info "The wheel will be cached at ${WHEEL_CACHE} — back it up to skip next time."
        sudo -u "${REAL_USER}" \
            CMAKE_BUILD_PARALLEL_LEVEL=${BUILD_JOBS} \
            ${PYTHON} -m pip wheel --no-deps --quiet \
            -w "${WHEEL_CACHE}" dlib
        chown -R "${REAL_USER}:${REAL_USER}" "${WHEEL_CACHE}"
        sudo -u "${REAL_USER}" ${PIP} --find-links "${WHEEL_CACHE}" dlib
        info "dlib built and cached at ${WHEEL_CACHE}/${WHEEL_NAME}"
        info "Upload it to GitHub Releases to skip this build for everyone:"
        info "  gh release upload dlib-wheels '${WHEEL_CACHE}/${WHEEL_NAME}'"
    fi
fi

# Remove the temporary build swap now that dlib is compiled
if [[ "${LOW_MEM}" == "true" ]] && swapon --show | grep -qF "${BUILD_SWAP}"; then
    swapoff "${BUILD_SWAP}"
    rm -f "${BUILD_SWAP}"
    info "Build swap removed."
fi

# ---------------------------------------------------------------------------
# pip_install_retry <label> <packages...>
#   Runs pip install and retries up to 3 times on network failure.
#   pip --retries only retries the initial connection; IncompleteRead
#   (connection dropped mid-download) requires a full command retry.
# ---------------------------------------------------------------------------
pip_install_retry() {
    local label="$1"; shift
    local attempt
    for attempt in 1 2 3; do
        if sudo -u "${REAL_USER}" ${PIP} "$@"; then
            return 0
        fi
        if [[ ${attempt} -lt 3 ]]; then
            warn "${label}: download failed (attempt ${attempt}/3) — retrying in 10 s..."
            sleep 10
        fi
    done
    error "${label}: failed after 3 attempts. Check your network and re-run install.sh."
}

# ---------------------------------------------------------------------------
# wget_resume <url> <dest>
#   Downloads a file with HTTP resume support (-c flag).
#   Far more robust than pip on flaky Wi-Fi — retries up to 10 times
#   and continues from the byte it stopped at rather than restarting.
# ---------------------------------------------------------------------------
wget_resume() {
    local url="$1" dest="$2"
    wget -c --tries=10 --waitretry=30 --timeout=60 \
         --progress=dot:mega -O "${dest}" "${url}"
}

# ---------------------------------------------------------------------------
# face-recognition
#   face_recognition_models (~100 MB of neural-net model data) is the large
#   dependency.  On Pi 3 Wi-Fi the connection reliably drops mid-download.
#   Strategy: download face_recognition_models via wget (resume-capable)
#   into the wheel cache first, then pip install face-recognition pointing
#   at the local cache so it never needs to re-download the model data.
# ---------------------------------------------------------------------------
if [[ "${RECOGNITION_ENABLED}" != "false" ]]; then
    if sudo -u "${REAL_USER}" ${PYTHON} -c "import face_recognition" 2>/dev/null; then
        info "face-recognition already installed — skipping."
    else
        info "Downloading face_recognition_models with resume support..."

        # Ask PyPI for the current source-dist URL
        MODELS_URL=$(curl -sf "https://pypi.org/pypi/face_recognition_models/json" | \
            python3 -c "
import sys, json
data = json.load(sys.stdin)
for u in data.get('urls', []):
    if u['packagetype'] == 'sdist':
        print(u['url'])
        break
" 2>/dev/null)

        MODELS_DEST=""
        if [[ -n "${MODELS_URL}" ]]; then
            MODELS_DEST="${WHEEL_CACHE}/${MODELS_URL##*/}"
            if [[ -f "${MODELS_DEST}" ]]; then
                info "face_recognition_models already cached — skipping download."
            else
                wget_resume "${MODELS_URL}" "${MODELS_DEST}" || {
                    warn "wget failed — pip will download face_recognition_models directly."
                    MODELS_DEST=""
                }
                [[ -n "${MODELS_DEST}" ]] && \
                    chown "${REAL_USER}:${REAL_USER}" "${MODELS_DEST}"
            fi
        else
            warn "Could not get face_recognition_models URL from PyPI — pip will download directly."
        fi

        info "Installing face-recognition..."
        if [[ -n "${MODELS_DEST}" ]]; then
            pip_install_retry "face-recognition" \
                --find-links "${WHEEL_CACHE}" face-recognition
        else
            pip_install_retry "face-recognition" face-recognition
        fi
        info "face-recognition installed."
    fi
fi

# Remaining packages installed one-at-a-time with a progress counter
# so the terminal doesn't appear frozen during a slow connection.
REMAINING_PKGS=(
    "numpy<2"
    "pyqtgraph"
    "rpi-lgpio"
    "adafruit-circuitpython-dht"
    "fastapi>=0.110"
    "uvicorn[standard]>=0.27"
    "jinja2>=3.1"
    "python-multipart>=0.0.9"
    "httpx>=0.27"
    "itsdangerous>=2.1"
    "PyYAML"
)
TOTAL_REMAINING=${#REMAINING_PKGS[@]}

for i in "${!REMAINING_PKGS[@]}"; do
    PKG="${REMAINING_PKGS[$i]}"
    NUM=$((i + 1))
    # Strip version specifier for display
    PKG_DISPLAY="${PKG%%[\[>=<]*}"
    info "  [${NUM}/${TOTAL_REMAINING}]  ${PKG_DISPLAY}"
    pip_install_retry "${PKG_DISPLAY}" "${PKG}"
done

info "Pip packages installed."
info "(Any 'dependency conflict' warnings above are from system packages like types-seaborn and are harmless.)"

# ---------------------------------------------------------------------------
# 4. Directory tree + database preservation
#    Back up the database before install resets anything, then restore it
#    after.  Photos and videos are left in place — only config is reset.
# ---------------------------------------------------------------------------
section "Creating directories"

for dir in "${INSTALL_DIR}" "${SRC_DIR}" "${DATA_DIR}" "${PHOTOS_DIR}" \
           "${VIDEOS_DIR}" "${LOGOS_DIR}"; do
    mkdir -p "${dir}"
    chown "${REAL_USER}:${REAL_USER}" "${dir}"
done

# Preserve existing database across reinstalls
DB_BACKUP=""
if [[ -f "${DB_PATH}" ]]; then
    DB_BACKUP="${INSTALL_DIR}/smartkegerator.db.install-backup"
    cp "${DB_PATH}" "${DB_BACKUP}"
    info "Database backed up to ${DB_BACKUP}"
fi

info "Directories ready."

# ---------------------------------------------------------------------------
# 5. Copy source files — always overwrite so re-running install picks up
#    the latest scripts and code.  config.yaml is gitignored so it is never
#    in REPO_SRC and will not be touched here.
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_SRC="$(dirname "${SCRIPT_DIR}")"   # parent of scripts/ = src/

if [[ "${REPO_SRC}" != "${SRC_DIR}" ]]; then
    section "Copying source files to ${SRC_DIR}"
    cp -r "${REPO_SRC}/." "${SRC_DIR}/"
    chown -R "${REAL_USER}:${REAL_USER}" "${SRC_DIR}"
    info "Source files copied."
fi

# config.yaml — always recreate from template on install so settings are reset.
# The database is preserved (backed up and restored below).
CONFIG="${SRC_DIR}/config.yaml"
CONFIG_EXAMPLE="${SRC_DIR}/config.yaml.example"

if [[ -f "${CONFIG_EXAMPLE}" ]]; then
    sudo -u "${REAL_USER}" cp "${CONFIG_EXAMPLE}" "${CONFIG}"
    info "config.yaml reset from template."
else
    error "config.yaml.example not found — cannot create configuration."
fi

sed -i \
    -e "s|database_path:.*|database_path: ${DB_PATH}|" \
    -e "s|user_photos_dir:.*|user_photos_dir: ${PHOTOS_DIR}|" \
    -e "s|pour_videos_dir:.*|pour_videos_dir: ${VIDEOS_DIR}|" \
    -e "s|beer_logos_dir:.*|beer_logos_dir: ${LOGOS_DIR}|" \
    -e "s|css_file:.*|css_file: ${INSTALL_DIR}/style.css|" \
    -e "s|^\(\s*fullscreen:\s*\).*|\1true|" \
    "${CONFIG}"
chown "${REAL_USER}:${REAL_USER}" "${CONFIG}"
info "config.yaml paths set for user ${REAL_USER}."

# ---------------------------------------------------------------------------
# 6. systemd user services
# ---------------------------------------------------------------------------
section "systemd user services"

SERVICE_DIR="${REAL_HOME}/.config/systemd/user"
mkdir -p "${SERVICE_DIR}"
chown -R "${REAL_USER}:${REAL_USER}" "${REAL_HOME}/.config"

cat > "${SERVICE_DIR}/smartkegerator.service" << EOF
[Unit]
Description=SmartKegerator GUI
# The GUI needs Wayland, which is started by the desktop session after autologin.
# Restart=always with no rate limit means systemd keeps retrying silently until
# the Wayland socket appears — it never marks the service as "failed", which
# prevents the "Press Enter to read the journal" prompt at the console.
After=network.target

[Service]
Type=simple
WorkingDirectory=${SRC_DIR}
ExecStart=${SRC_DIR}/scripts/launch_gui.sh
Restart=always
RestartSec=5
StartLimitIntervalSec=0
# Kill the entire process group on stop so Qt/picamera2 children don't linger
KillMode=control-group
# Don't block reboot — force-kill after 10 s if still running
TimeoutStopSec=10
Environment=XDG_RUNTIME_DIR=/run/user/%U
Environment=WAYLAND_DISPLAY=wayland-0
Environment=QT_QPA_PLATFORM=wayland
Environment=QT_WAYLAND_DISABLE_WINDOWDECORATION=1

[Install]
WantedBy=default.target
EOF

cat > "${SERVICE_DIR}/smartkegerator-web.service" << EOF
[Unit]
Description=SmartKegerator Web Interface
After=network.target

[Service]
Type=simple
WorkingDirectory=${SRC_DIR}
ExecStart=${SRC_DIR}/scripts/launch_web.sh
Restart=always
RestartSec=5
StartLimitIntervalSec=0
KillMode=control-group
TimeoutStopSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
EOF

chown "${REAL_USER}:${REAL_USER}" \
    "${SERVICE_DIR}/smartkegerator.service" \
    "${SERVICE_DIR}/smartkegerator-web.service"

# authbind — grant the real user permission to bind to port 80 (HTTP) and
# port 443 (HTTPS) so the web service can use them without running as root.
for _port in 80 443; do
    touch "/etc/authbind/byport/${_port}"
    chmod 500 "/etc/authbind/byport/${_port}"
    chown "${REAL_USER}:${REAL_USER}" "/etc/authbind/byport/${_port}"
done
info "authbind configured for ports 80 and 443."

# Enable lingering so user services start at boot without login
loginctl enable-linger "${REAL_USER}" 2>/dev/null || true

# systemctl --user requires XDG_RUNTIME_DIR to reach the user's D-Bus session
REAL_UID=$(id -u "${REAL_USER}")
SYSTEMCTL="sudo -u ${REAL_USER} XDG_RUNTIME_DIR=/run/user/${REAL_UID} systemctl --user"

${SYSTEMCTL} daemon-reload 2>/dev/null || true
${SYSTEMCTL} enable smartkegerator.service 2>/dev/null || \
    warn "Could not enable service — run manually: systemctl --user enable smartkegerator.service"
${SYSTEMCTL} enable smartkegerator-web.service 2>/dev/null || \
    warn "Could not enable web service — run manually: systemctl --user enable smartkegerator-web.service"

info "systemd services installed."

# ---------------------------------------------------------------------------
# 7. Compositor autostart — supports Wayfire (Bookworm) and labwc (Trixie)
# ---------------------------------------------------------------------------
section "Desktop autostart"

# Detect which compositor is installed
if command -v labwc &>/dev/null; then
    COMPOSITOR="labwc"
elif command -v wayfire &>/dev/null; then
    COMPOSITOR="wayfire"
else
    COMPOSITOR="unknown"
    warn "Could not detect Wayland compositor — add autostart entry manually."
fi
info "Compositor detected: ${COMPOSITOR}"

LAUNCH_SCRIPT="${SRC_DIR}/scripts/launch_gui.sh"
chmod +x "${LAUNCH_SCRIPT}"
chmod +x "${SRC_DIR}/scripts/launch_web.sh"
chmod +x "${SRC_DIR}/scripts/reset_db.sh"
chmod +x "${SRC_DIR}/scripts/update.sh"

case "${COMPOSITOR}" in
    labwc)
        LABWC_AUTOSTART="${REAL_HOME}/.config/labwc/autostart"
        mkdir -p "$(dirname "${LABWC_AUTOSTART}")"
        chown "${REAL_USER}:${REAL_USER}" "$(dirname "${LABWC_AUTOSTART}")"
        # Kill the desktop panel so only the kiosk app is visible
        if ! grep -q "wf-panel-pi" "${LABWC_AUTOSTART}" 2>/dev/null; then
            printf '# Kiosk mode — hide desktop panel\npkill -x wf-panel-pi 2>/dev/null || true\n' \
                >> "${LABWC_AUTOSTART}"
        fi
        if ! grep -q "launch_gui" "${LABWC_AUTOSTART}" 2>/dev/null; then
            echo "${LAUNCH_SCRIPT} &" >> "${LABWC_AUTOSTART}"
            chown "${REAL_USER}:${REAL_USER}" "${LABWC_AUTOSTART}"
            info "Added kiosk launch to labwc autostart."
        else
            info "labwc autostart already has SmartKegerator entry."
        fi
        ;;
    wayfire)
        # Wayfire reads autostart from the [autostart] section of wayfire.ini
        WAYFIRE_INI="${REAL_HOME}/.config/wayfire.ini"
        mkdir -p "$(dirname "${WAYFIRE_INI}")"
        chown "${REAL_USER}:${REAL_USER}" "$(dirname "${WAYFIRE_INI}")"

        # Build a block: kill the desktop panel, then launch the kiosk
        WAYFIRE_BLOCK="autostart_kill_panel = pkill -x wf-panel-pi 2>/dev/null || true
smartkegerator = ${LAUNCH_SCRIPT}"

        if ! grep -q "smartkegerator" "${WAYFIRE_INI}" 2>/dev/null; then
            if grep -q "^\[autostart\]" "${WAYFIRE_INI}" 2>/dev/null; then
                # Insert both lines right after [autostart]
                sed -i "/^\[autostart\]/a ${WAYFIRE_BLOCK}" "${WAYFIRE_INI}"
            else
                printf '\n[autostart]\n%s\n' "${WAYFIRE_BLOCK}" >> "${WAYFIRE_INI}"
            fi
            chown "${REAL_USER}:${REAL_USER}" "${WAYFIRE_INI}"
            info "Added kiosk launch (+ panel kill) to Wayfire [autostart]."
        else
            # Ensure the panel-kill line is also present
            if ! grep -q "autostart_kill_panel" "${WAYFIRE_INI}" 2>/dev/null; then
                sed -i "/^\[autostart\]/a autostart_kill_panel = pkill -x wf-panel-pi 2>/dev/null || true" \
                    "${WAYFIRE_INI}"
                info "Added panel-kill entry to Wayfire [autostart]."
            else
                info "wayfire.ini already has SmartKegerator autostart entry."
            fi
        fi
        # Autohide the desktop panel for kiosk mode (belt-and-suspenders)
        WFSHELL="${REAL_HOME}/.config/wf-shell.ini"
        if [[ -f "${WFSHELL}" ]]; then
            sed -i 's/autohide\s*=\s*false/autohide = true/' "${WFSHELL}" 2>/dev/null || true
            info "Set wf-panel to autohide."
        fi
        ;;
esac

# LXDE fallback (older Pi OS images)
LXDE_AUTOSTART="${REAL_HOME}/.config/lxsession/LXDE-pi/autostart"
if [[ -d "$(dirname "${LXDE_AUTOSTART}")" ]]; then
    if ! grep -q "launch_gui" "${LXDE_AUTOSTART}" 2>/dev/null; then
        echo "@${LAUNCH_SCRIPT}" >> "${LXDE_AUTOSTART}"
        chown "${REAL_USER}:${REAL_USER}" "${LXDE_AUTOSTART}"
        info "Added to LXDE autostart."
    fi
fi

# ---------------------------------------------------------------------------
# 8. Display rotation
#    No default rotation is applied. Configure via the web UI:
#    Settings → Appearance → Display rotation.
#    Remove any legacy display_rotate from config.txt (breaks KMS driver).
# ---------------------------------------------------------------------------
section "Display rotation"

CONFIG_TXT="/boot/firmware/config.txt"
[[ -f "${CONFIG_TXT}" ]] || CONFIG_TXT="/boot/config.txt"
if grep -q "^display_rotate=" "${CONFIG_TXT}" 2>/dev/null; then
    sed -i '/^display_rotate=/d' "${CONFIG_TXT}"
    info "Removed legacy display_rotate from ${CONFIG_TXT} (use web UI to set rotation)."
fi

# Remove any wlr-randr rotation line written by older versions of this script
if [[ -f "${REAL_HOME}/.config/labwc/autostart" ]]; then
    if grep -q "wlr-randr.*DSI-1.*transform" "${REAL_HOME}/.config/labwc/autostart"; then
        sed -i '/wlr-randr --output DSI-1 --transform/d' "${REAL_HOME}/.config/labwc/autostart"
        info "Removed stale wlr-randr rotation from labwc autostart."
    fi
fi

info "Display rotation is managed via Settings → Appearance in the web UI."

# ---------------------------------------------------------------------------
# 9. Hardware setup (1-Wire, camera, GPIO, screen blanking)
# ---------------------------------------------------------------------------
section "Hardware setup"

SETUP_SCRIPT="${SRC_DIR}/scripts/setup_hardware.sh"
if [[ -f "${SETUP_SCRIPT}" ]]; then
    bash "${SETUP_SCRIPT}" || warn "Hardware setup encountered errors — review output above."
else
    warn "setup_hardware.sh not found at ${SETUP_SCRIPT} — run it manually after install."
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Sudoers rule — allow the web service to reboot the Pi without a password.
# The rule is scoped to exactly /sbin/reboot so no broader privilege is granted.
# ---------------------------------------------------------------------------
section "Sudoers rule for web-initiated reboot"

SUDOERS_FILE="/etc/sudoers.d/smartkegerator-reboot"
SUDOERS_LINE="${REAL_USER} ALL=(ALL) NOPASSWD: /sbin/reboot"
if [[ -f "${SUDOERS_FILE}" ]] && grep -qF "${SUDOERS_LINE}" "${SUDOERS_FILE}"; then
    info "Sudoers rule already present."
else
    echo "${SUDOERS_LINE}" > "${SUDOERS_FILE}"
    chmod 440 "${SUDOERS_FILE}"
    info "Sudoers rule written: ${REAL_USER} may run sudo reboot without password."
fi

# ---------------------------------------------------------------------------
# Restore database backup (preserved from before install)
# ---------------------------------------------------------------------------
if [[ -n "${DB_BACKUP:-}" && -f "${DB_BACKUP}" ]]; then
    cp "${DB_BACKUP}" "${DB_PATH}"
    chown "${REAL_USER}:${REAL_USER}" "${DB_PATH}"
    rm -f "${DB_BACKUP}"
    info "Database restored."
fi

section "Installation complete"

echo ""
echo "  Source:   ${SRC_DIR}"
echo "  Venv:     ${VENV_DIR}"
echo "  Config:   ${CONFIG}"
echo "  Database: ${DB_PATH}"
echo "  Photos:   ${PHOTOS_DIR}"
echo ""
echo "  Next steps:"
echo ""
echo "  1. Migrate existing data (if upgrading from the old C++ version):"
echo "     cd ${SRC_DIR}"
echo "     ${PYTHON} -m scripts.migrate_data --db ${DB_PATH} \\"
echo "         --beers /path/to/old/logs/beers.txt \\"
echo "         --kegs  /path/to/old/logs/kegs.txt  \\"
echo "         --users /path/to/old/logs/users.txt  \\"
echo "         --pours /path/to/old/logs/pours.txt"
echo ""
echo "  2. Add beers and kegs via the CLI:"
echo "     cd ${SRC_DIR}"
echo "     ${PYTHON} -m scripts.manage beer add --name 'IPA' --company 'Brewery' --abv 6.5"
echo "     ${PYTHON} -m scripts.manage keg add --beer-id 1 --capacity 19.5 --price 120"
echo "     ${PYTHON} -m scripts.manage tap set left --keg-id 1"
echo ""
echo "  3. Reboot — both services and the GUI start automatically:"
echo "     sudo reboot"
echo ""
echo "  4. Open the web interface from any device on the same network:"
echo "     http://$(hostname -I | awk '{print $1}'):8080"
echo ""

if [[ "${LOW_MEM}" == "true" ]]; then
    echo -e "${YELLOW}Pi 3 / low-memory notes:${NC}"
    echo "  • Face recognition runs ~3-5× slower than on Pi 4/5 — identification"
    echo "    may take a few seconds per frame. This is normal."
    echo "  • If the GUI or web server become unresponsive under load, reduce the"
    echo "    camera resolution in config.yaml (camera_width / camera_height)."
    echo "  • To disable face recognition and free ~200 MB of RAM, set:"
    echo "        recognition:"
    echo "          enabled: false"
    echo "    in ${CONFIG}"
    echo ""
fi
