#!/usr/bin/env bash
# =============================================================================
# SmartKegerator installer — Raspberry Pi OS Bookworm (64-bit)
#
# Run once on a fresh Pi:
#   chmod +x install.sh && sudo ./install.sh
#
# What this does:
#   1. Installs system packages via apt (OpenCV, PyQt6, gpiod, etc.)
#   2. Creates a Python venv and installs pip packages into it
#   3. Creates the data/photo/video directory tree
#   4. Installs systemd user services and Pi autostart entry
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
INSTALL_DIR="${REAL_HOME}/smartkegerator"
SRC_DIR="${INSTALL_DIR}/src"
VENV_DIR="${INSTALL_DIR}/venv"
DATA_DIR="${INSTALL_DIR}/data"
PHOTOS_DIR="${INSTALL_DIR}/photos"
VIDEOS_DIR="${INSTALL_DIR}/videos"
LOGOS_DIR="${INSTALL_DIR}/logos"
DB_PATH="${DATA_DIR}/smartkegerator.db"
PYTHON="${VENV_DIR}/bin/python3"

# ---------------------------------------------------------------------------
# 1. System packages
# ---------------------------------------------------------------------------
section "System packages"

apt-get update -qq

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

# PyQt6
apt-get install -y \
    python3-pyqt6 \
    python3-pyqt6.qtmultimedia \
    qt6-base-dev

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

# dlib — must build from source on Bookworm 64-bit (~20-30 min on Pi 4)
info "Building dlib from source — this takes 20-30 minutes on Pi 4, please wait..."
sudo -u "${REAL_USER}" ${PIP} dlib

# face-recognition — depends on dlib above
sudo -u "${REAL_USER}" ${PIP} face-recognition

# PyQtGraph for history charts
sudo -u "${REAL_USER}" ${PIP} pyqtgraph

# Adafruit DHT22 library
sudo -u "${REAL_USER}" ${PIP} adafruit-circuitpython-dht

# Web interface dependencies
sudo -u "${REAL_USER}" ${PIP} \
    "fastapi>=0.110" \
    "uvicorn[standard]>=0.27" \
    "jinja2>=3.1" \
    "python-multipart>=0.0.9"

# PyYAML (likely already visible via system-site-packages, but ensure it's present)
sudo -u "${REAL_USER}" ${PIP} PyYAML

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

# Update config.yaml paths to match this installation
CONFIG="${SRC_DIR}/config.yaml"
if [[ -f "${CONFIG}" ]]; then
    sed -i \
        -e "s|database_path:.*|database_path: ${DB_PATH}|" \
        -e "s|user_photos_dir:.*|user_photos_dir: ${PHOTOS_DIR}|" \
        -e "s|pour_videos_dir:.*|pour_videos_dir: ${VIDEOS_DIR}|" \
        -e "s|beer_logos_dir:.*|beer_logos_dir: ${LOGOS_DIR}|" \
        "${CONFIG}"
    chown "${REAL_USER}:${REAL_USER}" "${CONFIG}"
    info "config.yaml paths updated."
fi

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
After=graphical-session.target

[Service]
Type=simple
WorkingDirectory=${SRC_DIR}
ExecStart=${PYTHON} ${SRC_DIR}/main.py ${CONFIG}
Restart=on-failure
RestartSec=5
Environment=DISPLAY=:0
Environment=XAUTHORITY=${REAL_HOME}/.Xauthority
Environment=WAYLAND_DISPLAY=wayland-1
Environment=XDG_RUNTIME_DIR=/run/user/%U

[Install]
WantedBy=graphical-session.target
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
# 7. LXDE / Wayfire autostart (fallback for desktop environments)
# ---------------------------------------------------------------------------
section "Desktop autostart"

WAYFIRE_AUTOSTART="${REAL_HOME}/.config/wayfire/autostart"
mkdir -p "$(dirname "${WAYFIRE_AUTOSTART}")"
if ! grep -q "smartkegerator" "${WAYFIRE_AUTOSTART}" 2>/dev/null; then
    echo "${PYTHON} ${SRC_DIR}/main.py ${CONFIG} &" >> "${WAYFIRE_AUTOSTART}"
    chown "${REAL_USER}:${REAL_USER}" "${WAYFIRE_AUTOSTART}"
    info "Added to Wayfire autostart."
fi

LXDE_AUTOSTART="${REAL_HOME}/.config/lxsession/LXDE-pi/autostart"
if [[ -d "$(dirname "${LXDE_AUTOSTART}")" ]]; then
    if ! grep -q "smartkegerator" "${LXDE_AUTOSTART}" 2>/dev/null; then
        echo "@${PYTHON} ${SRC_DIR}/main.py ${CONFIG}" >> "${LXDE_AUTOSTART}"
        chown "${REAL_USER}:${REAL_USER}" "${LXDE_AUTOSTART}"
        info "Added to LXDE autostart."
    fi
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
echo "  1. Run hardware setup (enables 1-Wire, camera, GPIO):"
echo "     sudo ${SRC_DIR}/scripts/setup_hardware.sh"
echo ""
echo "  2. Migrate existing data (if upgrading from the old C++ version):"
echo "     cd ${SRC_DIR}"
echo "     ${PYTHON} -m scripts.migrate_data --db ${DB_PATH} \\"
echo "         --beers /path/to/old/logs/beers.txt \\"
echo "         --kegs  /path/to/old/logs/kegs.txt  \\"
echo "         --users /path/to/old/logs/users.txt  \\"
echo "         --pours /path/to/old/logs/pours.txt"
echo ""
echo "  3. Add beers and kegs via the CLI:"
echo "     cd ${SRC_DIR}"
echo "     ${PYTHON} -m scripts.manage beer add --name 'IPA' --company 'Brewery' --abv 6.5"
echo "     ${PYTHON} -m scripts.manage keg add --beer-id 1 --capacity 19.5 --price 120"
echo "     ${PYTHON} -m scripts.manage tap set left --keg-id 1"
echo ""
echo "  4. Start the services:"
echo "     systemctl --user start smartkegerator"
echo "     systemctl --user start smartkegerator-web"
echo "     # or reboot and both start automatically"
echo ""
echo "  5. Open the web interface from any device on the same network:"
echo "     http://$(hostname -I | awk '{print $1}'):8080"
echo ""
