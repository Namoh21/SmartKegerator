#!/usr/bin/env bash
# =============================================================================
# SmartKegerator database reset — wipes the database and starts fresh.
#
# Use this for troubleshooting or to clear all beers, kegs, users, pours,
# and settings.  Photos and config.yaml are NOT touched.
#
# A timestamped backup is created before deletion so you can recover if needed.
#
# Run as the service user (no sudo required):
#   bash src/scripts/reset_db.sh
# =============================================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

INSTALL_DIR="/opt/smartkegerator"
DATA_DIR="${INSTALL_DIR}/data"
DB_PATH="${DATA_DIR}/smartkegerator.db"

# ---------------------------------------------------------------------------
# Confirm intent
# ---------------------------------------------------------------------------
echo ""
echo -e "${RED}WARNING: This will delete all beers, kegs, users, pours, and settings.${NC}"
echo "Photos and config.yaml will NOT be touched."
echo "A backup will be saved before deletion."
echo ""
read -r -p "Type YES to continue: " CONFIRM
if [[ "${CONFIRM}" != "YES" ]]; then
    echo "Cancelled."
    exit 0
fi

# ---------------------------------------------------------------------------
# Stop services so nothing is writing to the database
# ---------------------------------------------------------------------------
info "Stopping services…"
systemctl --user stop smartkegerator smartkegerator-web 2>/dev/null || true

# ---------------------------------------------------------------------------
# Back up existing database
# ---------------------------------------------------------------------------
if [[ -f "${DB_PATH}" ]]; then
    BACKUP="${DATA_DIR}/smartkegerator.db.$(date +%Y%m%d-%H%M%S).bak"
    cp "${DB_PATH}" "${BACKUP}"
    info "Backup saved: ${BACKUP}"
    rm -f "${DB_PATH}"
    info "Database deleted."
else
    info "No existing database found — nothing to back up."
fi

# ---------------------------------------------------------------------------
# Restart services — the app will create a fresh database on startup
# ---------------------------------------------------------------------------
info "Starting services…"
systemctl --user start smartkegerator smartkegerator-web 2>/dev/null || \
    warn "Could not restart services — run: systemctl --user start smartkegerator smartkegerator-web"

echo ""
info "Database reset complete."
info "Open the web UI and create a new admin account to get started."
echo ""
