#!/usr/bin/env bash
# SmartKegerator GUI launcher.
# Called by the compositor autostart and the systemd service.
# Waits for the Wayland socket before launching so startup race conditions
# don't cause a silent failure.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$(dirname "${SCRIPT_DIR}")"
INSTALL_DIR="$(dirname "${SRC_DIR}")"
PYTHON="${INSTALL_DIR}/venv/bin/python3"
CONFIG="${SRC_DIR}/config.yaml"

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

# Force Qt to use the Wayland platform plugin.
# Without this, Qt 6 may fall back to XWayland (no-op or invisible on a
# pure Wayland compositor) when launched from the compositor autostart.
export QT_QPA_PLATFORM=wayland
export QT_WAYLAND_DISABLE_WINDOWDECORATION=1

# Only one instance at a time
if pgrep -f "main.py ${CONFIG}" >/dev/null 2>&1; then
    exit 0
fi

# Wait up to 30 s for any Wayland socket (wayland-0 or wayland-1)
for i in $(seq 1 60); do
    for socket in wayland-0 wayland-1; do
        if [[ -S "${XDG_RUNTIME_DIR}/${socket}" ]]; then
            export WAYLAND_DISPLAY="${socket}"
            break 2
        fi
    done
    sleep 0.5
done

if [[ -z "${WAYLAND_DISPLAY:-}" ]]; then
    echo "SmartKegerator: no Wayland socket found after 30 s — aborting" >&2
    exit 1
fi

exec "${PYTHON}" "${SRC_DIR}/main.py" "${CONFIG}"
