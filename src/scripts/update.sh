#!/usr/bin/env bash
# =============================================================================
# SmartKegerator updater — pull latest code and restart services
#
# Preserves everything user-specific:  config.yaml, database, photos, videos.
# Only source code and scripts are updated.
#
# Run from the git clone directory (no sudo required):
#   cd ~/SmartKegerator && bash src/scripts/update.sh
#
# To do a full reset (keeps only the database), re-run the installer:
#   sudo bash src/scripts/install.sh
#
# To wipe the database for a clean slate:
#   bash src/scripts/reset_db.sh
# =============================================================================
set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info() { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $*"; }

INSTALL_DIR="/opt/smartkegerator"
SRC_DIR="${INSTALL_DIR}/src"
REAL_USER="${SUDO_USER:-$(whoami)}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_SRC="$(dirname "${SCRIPT_DIR}")"   # parent of scripts/ = src/

# ---------------------------------------------------------------------------
# 1. Pull latest code
# ---------------------------------------------------------------------------
info "Pulling latest code…"
REPO_DIR="$(dirname "${REPO_SRC}")"
git -C "${REPO_DIR}" fetch origin
git -C "${REPO_DIR}" reset --hard origin/master

# ---------------------------------------------------------------------------
# 2. Sync source files — preserves config.yaml, database, photos, videos
#    (config.yaml is gitignored so rsync never touches it)
# ---------------------------------------------------------------------------
info "Syncing source files to ${SRC_DIR}…"
if [[ "$(id -u)" -eq 0 ]]; then
    rsync -a --exclude="config.yaml" "${REPO_SRC}/" "${SRC_DIR}/"
    chown -R "${REAL_USER}:${REAL_USER}" "${SRC_DIR}"
else
    sudo rsync -a --exclude="config.yaml" "${REPO_SRC}/" "${SRC_DIR}/"
    sudo chown -R "${REAL_USER}:${REAL_USER}" "${SRC_DIR}"
fi
info "Source files updated (config.yaml, database, and photos unchanged)."

# Strip Windows CRLF line endings from all text source files.
# .gitattributes enforces eol=lf in the repo, but rsync from a Windows
# working tree can still carry CRLF into /opt. CRLF in a bash shebang
# (#!/usr/bin/env bash\r) causes systemd exit code 203/EXEC.
info "Stripping CRLF from source files…"
find "${SRC_DIR}" \( -name "*.sh" -o -name "*.py" -o -name "*.html" \
    -o -name "*.yaml" -o -name "*.yml" -o -name "*.json" \
    -o -name "*.md"  -o -name "*.txt" -o -name "*.conf" \) \
    -exec sed -i 's/\r$//' {} \;

# ---------------------------------------------------------------------------
# 2b. Ensure sudoers rule exists for web-initiated reboot
# ---------------------------------------------------------------------------
SUDOERS_FILE="/etc/sudoers.d/smartkegerator-reboot"
SUDOERS_LINE="${REAL_USER} ALL=(ALL) NOPASSWD: /sbin/reboot"
if [[ ! -f "${SUDOERS_FILE}" ]] || ! grep -qF "${SUDOERS_LINE}" "${SUDOERS_FILE}"; then
    echo "${SUDOERS_LINE}" | sudo tee "${SUDOERS_FILE}" > /dev/null
    sudo chmod 440 "${SUDOERS_FILE}"
    info "Sudoers rule added: ${REAL_USER} may run sudo reboot without password."
fi

# ---------------------------------------------------------------------------
# 3. Restart services
# ---------------------------------------------------------------------------
info "Restarting services…"
REAL_UID=$(id -u "${REAL_USER}")
sudo -u "${REAL_USER}" XDG_RUNTIME_DIR="/run/user/${REAL_UID}" \
    systemctl --user restart smartkegerator smartkegerator-web 2>/dev/null || \
    warn "Could not restart services — run: systemctl --user restart smartkegerator smartkegerator-web"

info "Update complete."
