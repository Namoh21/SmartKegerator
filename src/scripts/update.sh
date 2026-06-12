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
REAL_HOME=$(getent passwd "${REAL_USER}" | cut -d: -f6)

# ---------------------------------------------------------------------------
# 1. Pull latest code
# ---------------------------------------------------------------------------
info "Pulling latest code…"
# The git clone lives in the real user's home, not /opt (which is the rsync target)
REPO_DIR="${REAL_HOME}/SmartKegerator"
if [[ ! -d "${REPO_DIR}/.git" ]]; then
    echo "ERROR: Git repo not found at ${REPO_DIR}" >&2
    exit 1
fi
REPO_SRC="${REPO_DIR}/src"
CHANNEL_FILE="${INSTALL_DIR}/update_channel"
DB_PATH="${INSTALL_DIR}/data/smartkegerator.db"
BRANCH="master"
# Read channel exclusively from the DB — the DB is the single source of truth
# written by the web UI.  The channel file (/opt/.../update_channel) is only
# used as a last resort when sqlite3 is not available, and is always rewritten
# (chowned to REAL_USER) so the web service can update it on the next save.
if [[ -f "${DB_PATH}" ]] && command -v sqlite3 &>/dev/null; then
    _db_branch=$(sqlite3 "${DB_PATH}" \
        "SELECT value FROM settings WHERE key='update_channel' LIMIT 1;" 2>/dev/null)
    _db_branch=$(echo "${_db_branch}" | tr -d '[:space:]')
    if [[ "${_db_branch}" == "dev" || "${_db_branch}" == "master" ]]; then
        BRANCH="${_db_branch}"
    elif [[ -f "${CHANNEL_FILE}" ]]; then
        # DB had no entry yet — fall back to file and seed the DB
        _file_branch=$(cat "${CHANNEL_FILE}" | tr -d '[:space:]')
        [[ "${_file_branch}" == "dev" || "${_file_branch}" == "master" ]] && BRANCH="${_file_branch}"
        sqlite3 "${DB_PATH}" \
            "INSERT OR REPLACE INTO settings (key,value) VALUES ('update_channel','${BRANCH}');" \
            2>/dev/null || true
    fi
elif [[ -f "${CHANNEL_FILE}" ]]; then
    _file_branch=$(cat "${CHANNEL_FILE}" | tr -d '[:space:]')
    [[ "${_file_branch}" == "dev" || "${_file_branch}" == "master" ]] && BRANCH="${_file_branch}"
fi
# Always write the resolved channel back to the file and ensure the web
# service (non-root user) can overwrite it on the next save.
echo "${BRANCH}" > "${CHANNEL_FILE}"
chown "${REAL_USER}:${REAL_USER}" "${CHANNEL_FILE}" 2>/dev/null || true
info "Update channel: ${BRANCH}"

# Refuse to update from an unexpected remote — this script runs as root, so a
# swapped-out origin URL would mean executing arbitrary code with full
# privileges on the next update.
EXPECTED_ORIGIN="github.com/Namoh21/SmartKegerator"
ACTUAL_ORIGIN=$(git -C "${REPO_DIR}" remote get-url origin 2>/dev/null || true)
if [[ "${ACTUAL_ORIGIN}" != *"${EXPECTED_ORIGIN}"* ]]; then
    echo "ERROR: origin remote is '${ACTUAL_ORIGIN}', expected ${EXPECTED_ORIGIN} — refusing to update." >&2
    exit 1
fi

git -C "${REPO_DIR}" fetch origin
git -C "${REPO_DIR}" reset --hard "origin/${BRANCH}"

# Write the current commit hash so the web UI can display it without needing a git repo
git -C "${REPO_DIR}" rev-parse --short HEAD > "${INSTALL_DIR}/GIT_HASH" 2>/dev/null || true

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
# 2b. Ensure service files use /bin/bash explicitly so CRLF shebangs never
#     cause systemd exit code 203/EXEC regardless of line ending state.
# ---------------------------------------------------------------------------
SERVICE_DIR="${REAL_HOME}/.config/systemd/user"
for _svc in smartkegerator.service smartkegerator-web.service; do
    _file="${SERVICE_DIR}/${_svc}"
    if [[ -f "${_file}" ]]; then
        sed -i \
            's|ExecStart=/opt/.*/launch_gui\.sh|ExecStart=/bin/bash /opt/smartkegerator/src/scripts/launch_gui.sh|' \
            "${_file}"
        sed -i \
            's|ExecStart=/opt/.*/launch_web\.sh|ExecStart=/bin/bash /opt/smartkegerator/src/scripts/launch_web.sh|' \
            "${_file}"
    fi
done
sudo -u "${REAL_USER}" XDG_RUNTIME_DIR="/run/user/$(id -u ${REAL_USER})" \
    systemctl --user daemon-reload 2>/dev/null || true

# ---------------------------------------------------------------------------
# 2c. Upgrade Python dependencies — security fixes land as raised version
#     floors in requirements.txt, so they must be applied on update, not
#     just on fresh installs.  pip's default "only-if-needed" strategy means
#     packages already satisfying the floors are left untouched.
# ---------------------------------------------------------------------------
VENV_PIP="${INSTALL_DIR}/venv/bin/pip"
if [[ -x "${VENV_PIP}" ]]; then
    info "Upgrading Python dependencies to current security floors…"
    if [[ "$(id -u)" -eq 0 ]]; then
        sudo -u "${REAL_USER}" "${VENV_PIP}" install --upgrade --upgrade-strategy only-if-needed \
            -r "${SRC_DIR}/requirements.txt" \
            || warn "Dependency upgrade failed — continuing with existing packages."
    else
        "${VENV_PIP}" install --upgrade --upgrade-strategy only-if-needed \
            -r "${SRC_DIR}/requirements.txt" \
            || warn "Dependency upgrade failed — continuing with existing packages."
    fi
else
    warn "venv pip not found at ${VENV_PIP} — skipping dependency upgrade."
fi

# ---------------------------------------------------------------------------
# 2d. Ensure sudoers rule exists for web-initiated reboot
# ---------------------------------------------------------------------------
SUDOERS_FILE="/etc/sudoers.d/smartkegerator-reboot"
SUDOERS_REBOOT="${REAL_USER} ALL=(ALL) NOPASSWD: /sbin/reboot"
SUDOERS_UPDATE="${REAL_USER} ALL=(ALL) NOPASSWD: /bin/bash ${SRC_DIR}/scripts/update.sh"
if [[ ! -f "${SUDOERS_FILE}" ]] || ! grep -qF "${SUDOERS_UPDATE}" "${SUDOERS_FILE}"; then
    printf '%s\n%s\n' "${SUDOERS_REBOOT}" "${SUDOERS_UPDATE}" | sudo tee "${SUDOERS_FILE}" > /dev/null
    sudo chmod 440 "${SUDOERS_FILE}"
    info "Sudoers rules updated."
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
