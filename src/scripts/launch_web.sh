#!/usr/bin/env bash
# Launch the SmartKegerator web server, reading port and SSL settings from
# config.yaml so the systemd service honours whatever the user saved in Settings.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$(dirname "${SCRIPT_DIR}")"
CONFIG="${SRC_DIR}/config.yaml"
PYTHON="${SRC_DIR}/../venv/bin/python"

# ---------------------------------------------------------------------------
# Read port from config.yaml (default 8080)
# ---------------------------------------------------------------------------
PORT=8080
if [[ -f "${CONFIG}" ]]; then
    _port=$(python3 -c "
import yaml, sys
cfg = yaml.safe_load(open('${CONFIG}'))
print(cfg.get('web', {}).get('port', 8080))
" 2>/dev/null) && PORT="${_port}"
fi

# ---------------------------------------------------------------------------
# Read SSL settings from config.yaml
# ---------------------------------------------------------------------------
SSL_ENABLED=false
SSL_CERTFILE=""
SSL_KEYFILE=""
if [[ -f "${CONFIG}" ]]; then
    read -r _enabled _cert _key < <(python3 -c "
import yaml
cfg = yaml.safe_load(open('${CONFIG}'))
ssl = cfg.get('web', {}).get('ssl', {})
print(str(ssl.get('enabled', False)).lower(), ssl.get('certfile', ''), ssl.get('keyfile', ''))
" 2>/dev/null) || true
    SSL_ENABLED="${_enabled:-false}"
    SSL_CERTFILE="${_cert:-}"
    SSL_KEYFILE="${_key:-}"
fi

# ---------------------------------------------------------------------------
# Validate port — ports below 1024 are privileged.
# Only allow 80 (plain HTTP) or 443 (HTTPS with SSL enabled).
# Anything else below 1024 falls back to 8080.
# ---------------------------------------------------------------------------
if [[ "${PORT}" -lt 1024 ]]; then
    if [[ "${PORT}" -eq 443 && "${SSL_ENABLED}" == "true" ]]; then
        : # 443 + SSL enabled — allowed
    elif [[ "${PORT}" -eq 80 && "${SSL_ENABLED}" != "true" ]]; then
        : # 80 without SSL — allowed
    else
        echo "launch_web: port ${PORT} is not allowed (privileged ports: 80 for HTTP, 443 for HTTPS only) — falling back to 8080" >&2
        PORT=8080
    fi
fi

# ---------------------------------------------------------------------------
# Build uvicorn command
# ---------------------------------------------------------------------------
CMD=(
    "${PYTHON}" -m uvicorn web.server:app
    --host 0.0.0.0
    --port "${PORT}"
)

if [[ "${SSL_ENABLED}" == "true" && -f "${SSL_CERTFILE}" && -f "${SSL_KEYFILE}" ]]; then
    CMD+=(--ssl-certfile "${SSL_CERTFILE}" --ssl-keyfile "${SSL_KEYFILE}")
fi

cd "${SRC_DIR}"
if [[ "${PORT}" -lt 1024 ]]; then
    exec authbind --deep "${CMD[@]}"
else
    exec "${CMD[@]}"
fi
