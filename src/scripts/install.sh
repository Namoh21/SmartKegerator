#!/usr/bin/env bash
# =============================================================================
# SmartKegerator installer — Raspberry Pi OS Bookworm (64-bit)
#
# Run once on a fresh Pi:
#   chmod +x install.sh && sudo ./install.sh
#
# What this does:
#   1. Installs system packages via apt (OpenCV, PyQt6, gpiod, dlib, etc.)
#   2. Installs remaining Python packages via pip
#   3. Creates the data/photo/video directory tree
#   4. Installs the systemd user service and Pi autostart entry
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
DATA_DIR="${INSTALL_DIR}/data"
PHOTOS_DIR="${INSTALL_DIR}/photos"
VIDEOS_DIR="${INSTALL_DIR}/videos"
LOGOS_DIR="${INSTALL_DIR}/logos"
DB_PATH="${DATA_DIR}/smartkegerator.db"

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
    gfortran

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

# Adafruit DHT22 dependencies (libgpiod3 is the Bookworm name; libgpiod-dev above pulls it in)
apt-get install -y python3-dev

# YAML
apt-get install -y python3-yaml

info "System packages installed."

# ---------------------------------------------------------------------------
# 2. Python packages (pip — only what apt doesn't provide)
# ---------------------------------------------------------------------------
section "Python pip packages"

# On Bookworm, pip requires --break-system-packages to install globally
PIP="python3 -m pip install --break-system-packages --quiet"

# dlib — must build from source on Bookworm 64-bit (~20-30 min on Pi 4, please be patient)
info "Building dlib from source — this takes 20-30 minutes on Pi 4, please wait..."
$PIP dlib

# face-recognition — depends on dlib above
$PIP face-recognition

# PyQtGraph for history charts
$PIP pyqtgraph

# Adafruit DHT22 library
$PIP adafruit-circuitpython-dht

# PyYAML (may already be present via apt; --break-system-packages is safe here)
$PIP PyYAML

# Web interface dependencies
$PIP "fastapi>=0.110" "uvicorn[standard]>=0.27" "jinja2>=3.1" "python-multipart>=0.0.9"

info "Pip packages installed."

# ---------------------------------------------------------------------------
# 3. Directory tree
# ---------------------------------------------------------------------------
section "Creating directories"

for dir in "${INSTALL_DIR}" "${SRC_DIR}" "${DATA_DIR}" "${PHOTOS_DIR}" \
           "${VIDEOS_DIR}" "${LOGOS_DIR}"; do
    mkdir -p "${dir}"
    chown "${REAL_USER}:${REAL_USER}" "${dir}"
done

info "Directories ready."

# ---------------------------------------------------------------------------
# 4. Copy source files (only if not already there — won't overwrite edits)
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
# 5. systemd user service
# ---------------------------------------------------------------------------
section "systemd user service"

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
ExecStart=/usr/bin/python3 ${SRC_DIR}/main.py ${CONFIG}
Restart=on-failure
RestartSec=5
Environment=DISPLAY=:0
Environment=XAUTHORITY=${REAL_HOME}/.Xauthority
Environment=WAYLAND_DISPLAY=wayland-1
Environment=XDG_RUNTIME_DIR=/run/user/%U

[Install]
WantedBy=graphical-session.target
EOF

chown "${REAL_USER}:${REAL_USER}" "${SERVICE_DIR}/smartkegerator.service"

# Web interface service
cat > "${SERVICE_DIR}/smartkegerator-web.service" << EOF
[Unit]
Description=SmartKegerator Web Interface
After=network.target

[Service]
Type=simple
WorkingDirectory=${SRC_DIR}
ExecStart=/usr/bin/python3 -m uvicorn web.server:app --host 0.0.0.0 --port 8080
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
EOF

chown "${REAL_USER}:${REAL_USER}" "${SERVICE_DIR}/smartkegerator-web.service"

# Enable lingering so user services start at boot without login
loginctl enable-linger "${REAL_USER}" 2>/dev/null || true

# Enable the service as the real user
sudo -u "${REAL_USER}" systemctl --user daemon-reload 2>/dev/null || true
sudo -u "${REAL_USER}" systemctl --user enable smartkegerator.service 2>/dev/null || \
    warn "Could not enable systemd service — enable manually after first login: systemctl --user enable smartkegerator.service"
sudo -u "${REAL_USER}" systemctl --user enable smartkegerator-web.service 2>/dev/null || \
    warn "Could not enable web service — enable manually: systemctl --user enable smartkegerator-web.service"

info "systemd services installed."

# ---------------------------------------------------------------------------
# 6. LXDE / Wayfire autostart (fallback for desktop environments)
# ---------------------------------------------------------------------------
section "Desktop autostart"

# Wayfire (default on Bookworm)
WAYFIRE_AUTOSTART="${REAL_HOME}/.config/wayfire/autostart"
mkdir -p "$(dirname "${WAYFIRE_AUTOSTART}")"
if ! grep -q "smartkegerator" "${WAYFIRE_AUTOSTART}" 2>/dev/null; then
    echo "python3 ${SRC_DIR}/main.py ${CONFIG} &" >> "${WAYFIRE_AUTOSTART}"
    chown "${REAL_USER}:${REAL_USER}" "${WAYFIRE_AUTOSTART}"
    info "Added to Wayfire autostart."
fi

# LXDE (older Pi OS / fallback)
LXDE_AUTOSTART="${REAL_HOME}/.config/lxsession/LXDE-pi/autostart"
if [[ -d "$(dirname "${LXDE_AUTOSTART}")" ]]; then
    if ! grep -q "smartkegerator" "${LXDE_AUTOSTART}" 2>/dev/null; then
        echo "@python3 ${SRC_DIR}/main.py ${CONFIG}" >> "${LXDE_AUTOSTART}"
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
echo "  Config:   ${CONFIG}"
echo "  Database: ${DB_PATH}"
echo "  Photos:   ${PHOTOS_DIR}"
echo ""
echo "  Next steps:"
echo ""
echo "  1. Run hardware setup (enables 1-Wire, camera, SPI):"
echo "     sudo ${SRC_DIR}/scripts/setup_hardware.sh"
echo ""
echo "  2. Migrate existing data (if upgrading from the old C++ version):"
echo "     python3 -m scripts.migrate_data --db ${DB_PATH} \\"
echo "         --beers /path/to/old/logs/beers.txt \\"
echo "         --kegs  /path/to/old/logs/kegs.txt  \\"
echo "         --users /path/to/old/logs/users.txt  \\"
echo "         --pours /path/to/old/logs/pours.txt"
echo ""
echo "  3. Add beers and kegs via the CLI:"
echo "     cd ${SRC_DIR}"
echo "     python3 -m scripts.manage beer add --name 'IPA' --company 'Brewery' --abv 6.5"
echo "     python3 -m scripts.manage keg add --beer-id 1 --capacity 19.5 --price 120"
echo "     python3 -m scripts.manage tap set left --keg-id 1"
echo ""
echo "  4. Start the app:"
echo "     systemctl --user start smartkegerator"
echo "     systemctl --user start smartkegerator-web"
echo "     # or reboot and both start automatically"
echo ""
echo "  5. Open the web interface from any device on the same network:"
echo "     http://$(hostname -I | awk '{print $1}'):8080"
echo ""
