#!/usr/bin/env bash
# =============================================================================
# SmartKegerator updater — pull latest code and restart services
#
# Run from the git clone directory:
#   cd ~/smartkegerator && bash src/scripts/update.sh
# =============================================================================
set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info() { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $*"; }

INSTALL_DIR="/opt/smartkegerator"
SRC_DIR="${INSTALL_DIR}/src"
VENV_DIR="${INSTALL_DIR}/venv"
REAL_USER="${SUDO_USER:-$(whoami)}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_SRC="$(dirname "${SCRIPT_DIR}")"   # parent of scripts/ = src/

# ---------------------------------------------------------------------------
# 1. Pull latest code
# ---------------------------------------------------------------------------
info "Pulling latest code…"
git -C "$(dirname "${REPO_SRC}")" pull

# ---------------------------------------------------------------------------
# 2. Sync source files to /opt (preserve config.yaml — it's gitignored)
# ---------------------------------------------------------------------------
info "Syncing source files to ${SRC_DIR}…"
if [[ "$(id -u)" -eq 0 ]]; then
    rsync -a --exclude="config.yaml" "${REPO_SRC}/" "${SRC_DIR}/"
    chown -R "${REAL_USER}:${REAL_USER}" "${SRC_DIR}"
else
    sudo rsync -a --exclude="config.yaml" "${REPO_SRC}/" "${SRC_DIR}/"
    sudo chown -R "${REAL_USER}:${REAL_USER}" "${SRC_DIR}"
fi
info "Source files updated."

# ---------------------------------------------------------------------------
# 3. Restart services
# ---------------------------------------------------------------------------
info "Restarting services…"
REAL_UID=$(id -u "${REAL_USER}")
sudo -u "${REAL_USER}" XDG_RUNTIME_DIR="/run/user/${REAL_UID}" \
    systemctl --user restart smartkegerator smartkegerator-web 2>/dev/null || \
    warn "Could not restart services — run: systemctl --user restart smartkegerator smartkegerator-web"

info "Update complete."
