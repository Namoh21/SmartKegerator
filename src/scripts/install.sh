#!/usr/bin/env bash
# =============================================================================
# SmartKegerator installer — Raspberry Pi OS Bookworm / Trixie (64-bit)
#
# Run once on a fresh Pi:
#   chmod +x install.sh && sudo ./install.sh
#
# What this does:
#   1. Installs system packages via apt (OpenCV, PyQt6, gpiod, etc.)
#   2. Creates a Python venv and installs pip packages into it
#   3. Creates the data/photo/video directory tree
#   4. Installs systemd user services and compositor autostart entry
#   5. Runs hardware setup (1-Wire, GPIO, screen blanking, rotation)
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
REAL_HOME=$(eval echo "~${REAL_USER}")
info "Installing for user: ${REAL_USER}  (home: ${REAL_HOME})"

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

info "System packages installed."

# ---------------------------------------------------------------------------
# 2. Python virtual environment
# ---------------------------------------------------------------------------
section "Python virtual environment"

# --system-site-packages lets the venv use apt-installed packages
# (python3-opencv, python3-pyqt6, python3-libgpiod, python3-yaml)
if [[ ! -d "${VENV_DIR}" ]]; then
    sudo -u "${REAL_USER}" python3 -m venv --system-site-packages "${VENV_DIR}"
    info "Virtual environment created at ${VENV_DIR}"
else
    info "Virtual environment already exists — skipping creation."
fi

PIP="${PYTHON} -m pip install --quiet"

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
    info "Building dlib from source (~10-15 min on Pi 5, ~25-30 min on Pi 4)..."
    info "The wheel will be saved to ${WHEEL_CACHE} — back it up to skip this next time."
    sudo -u "${REAL_USER}" ${PYTHON} -m pip wheel --no-deps --quiet \
        -w "${WHEEL_CACHE}" dlib
    chown -R "${REAL_USER}:${REAL_USER}" "${WHEEL_CACHE}"
    sudo -u "${REAL_USER}" ${PIP} --find-links "${WHEEL_CACHE}" dlib
    info "dlib built and cached."
fi

# face-recognition (pure Python wrapper — fast)
if [[ "${RECOGNITION_ENABLED}" != "false" ]]; then
    sudo -u "${REAL_USER}" ${PIP} face-recognition
fi

# Remaining packages — all pure Python, install in seconds
sudo -u "${REAL_USER}" ${PIP} \
    pyqtgraph \
    adafruit-circuitpython-dht \
    "fastapi>=0.110" \
    "uvicorn[standard]>=0.27" \
    "jinja2>=3.1" \
    "python-multipart>=0.0.9" \
    PyYAML

info "Pip packages installed."

# ---------------------------------------------------------------------------
# 4. Directory tree
# ---------------------------------------------------------------------------
section "Creating directories"

for dir in "${INSTALL_DIR}" "${SRC_DIR}" "${DATA_DIR}" "${PHOTOS_DIR}" \
           "${VIDEOS_DIR}" "${LOGOS_DIR}"; do
    mkdir -p "${dir}"
    chown "${REAL_USER}:${REAL_USER}" "${dir}"
done

info "Directories ready."

# ---------------------------------------------------------------------------
# 5. Copy source files (only if not already there — won't overwrite edits)
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_SRC="$(dirname "${SCRIPT_DIR}")"   # parent of scripts/ = src/

if [[ "${REPO_SRC}" != "${SRC_DIR}" ]]; then
    section "Copying source files to ${SRC_DIR}"
    cp -rn "${REPO_SRC}/." "${SRC_DIR}/"
    chown -R "${REAL_USER}:${REAL_USER}" "${SRC_DIR}"
    info "Source files copied (existing files not overwritten)."
fi

# config.yaml is gitignored — create it from the template if missing,
# then patch all paths to match this installation.
CONFIG="${SRC_DIR}/config.yaml"
CONFIG_EXAMPLE="${SRC_DIR}/config.yaml.example"

if [[ ! -f "${CONFIG}" ]]; then
    if [[ -f "${CONFIG_EXAMPLE}" ]]; then
        sudo -u "${REAL_USER}" cp "${CONFIG_EXAMPLE}" "${CONFIG}"
        info "Created config.yaml from template."
    else
        error "config.yaml.example not found — cannot create configuration."
    fi
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
Description=SmartKegerator
After=network.target

[Service]
Type=simple
WorkingDirectory=${SRC_DIR}
ExecStart=${SRC_DIR}/scripts/launch_gui.sh
Restart=on-failure
RestartSec=5
Environment=XDG_RUNTIME_DIR=/run/user/%U

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
ExecStart=${PYTHON} -m uvicorn web.server:app --host 0.0.0.0 --port 8080
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
EOF

chown "${REAL_USER}:${REAL_USER}" \
    "${SERVICE_DIR}/smartkegerator.service" \
    "${SERVICE_DIR}/smartkegerator-web.service"

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

case "${COMPOSITOR}" in
    labwc)
        LABWC_AUTOSTART="${REAL_HOME}/.config/labwc/autostart"
        mkdir -p "$(dirname "${LABWC_AUTOSTART}")"
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
        if ! grep -q "smartkegerator" "${WAYFIRE_INI}" 2>/dev/null; then
            if grep -q "^\[autostart\]" "${WAYFIRE_INI}" 2>/dev/null; then
                sed -i "/^\[autostart\]/a smartkegerator = ${LAUNCH_SCRIPT}" "${WAYFIRE_INI}"
            else
                printf '\n[autostart]\nsmartkegerator = %s\n' "${LAUNCH_SCRIPT}" >> "${WAYFIRE_INI}"
            fi
            chown "${REAL_USER}:${REAL_USER}" "${WAYFIRE_INI}"
            info "Added SmartKegerator to Wayfire [autostart] in wayfire.ini."
        else
            info "wayfire.ini already has SmartKegerator autostart entry."
        fi
        # Autohide the desktop panel for kiosk mode
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
# 8. Display rotation — Pi 7" touchscreen at 90° (portrait)
#
#    KMS driver (vc4-kms-v3d) is used on all modern Pi OS images, so
#    display_rotate in config.txt is NOT used.  Rotation is handled by
#    the compositor: Wayfire via wayfire.ini, labwc via wlr-randr at startup.
# ---------------------------------------------------------------------------
section "Display rotation"

# Remove any stale display_rotate from config.txt (legacy — breaks KMS)
CONFIG_TXT="/boot/firmware/config.txt"
[[ -f "${CONFIG_TXT}" ]] || CONFIG_TXT="/boot/config.txt"
if grep -q "^display_rotate=" "${CONFIG_TXT}" 2>/dev/null; then
    sed -i '/^display_rotate=/d' "${CONFIG_TXT}"
    info "Removed legacy display_rotate from ${CONFIG_TXT}"
fi

case "${COMPOSITOR}" in
    labwc)
        # labwc: run wlr-randr at startup to rotate the DSI-1 output
        LABWC_AUTOSTART="${REAL_HOME}/.config/labwc/autostart"
        mkdir -p "$(dirname "${LABWC_AUTOSTART}")"
        if ! grep -q "wlr-randr.*DSI-1" "${LABWC_AUTOSTART}" 2>/dev/null; then
            echo "wlr-randr --output DSI-1 --transform 270 &" >> "${LABWC_AUTOSTART}"
            chown "${REAL_USER}:${REAL_USER}" "${LABWC_AUTOSTART}"
            info "Added wlr-randr 90° rotation to labwc autostart."
        else
            info "labwc autostart already has rotation entry."
        fi
        ;;
    wayfire)
        # Wayfire: set transform in wayfire.ini
        WAYFIRE_INI="${REAL_HOME}/.config/wayfire.ini"
        mkdir -p "$(dirname "${WAYFIRE_INI}")"
        if grep -q "^\[output:DSI-1\]" "${WAYFIRE_INI}" 2>/dev/null; then
            sed -i '/^\[output:DSI-1\]/,/^\[/{s/^transform *=.*/transform = 270/}' "${WAYFIRE_INI}"
        else
            printf '\n[output:DSI-1]\ntransform = 270\n' >> "${WAYFIRE_INI}"
        fi
        chown "${REAL_USER}:${REAL_USER}" "${WAYFIRE_INI}"
        info "Wayfire DSI-1 transform set to 90° (portrait)."
        ;;
    *)
        warn "Unknown compositor — set display rotation manually."
        ;;
esac

# ---------------------------------------------------------------------------
# 9. Hardware setup (1-Wire, camera, GPIO, screen blanking)
# ---------------------------------------------------------------------------
section "Hardware setup"

SETUP_SCRIPT="${SRC_DIR}/scripts/setup_hardware.sh"
if [[ -f "${SETUP_SCRIPT}" ]]; then
    bash "${SETUP_SCRIPT}"
else
    warn "setup_hardware.sh not found at ${SETUP_SCRIPT} — run it manually after install."
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
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
