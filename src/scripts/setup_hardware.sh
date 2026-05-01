#!/usr/bin/env bash
# =============================================================================
# SmartKegerator hardware setup — Raspberry Pi 3 / 4 / 5, Pi OS Bookworm / Trixie
#
# Enables kernel interfaces needed by SmartKegerator:
#   • 1-Wire         (DS18B20 liquid temp sensor)
#   • Camera         (Pi Camera Module — V2 or later)
#   • GPIO chardev   (already built-in; gpiod package required)
#
# Run ONCE, then reboot:
#   sudo ./setup_hardware.sh
# =============================================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }

[[ $EUID -eq 0 ]] || { echo "Run with sudo."; exit 1; }

CONFIG="/boot/firmware/config.txt"   # Bookworm path
[[ -f "${CONFIG}" ]] || CONFIG="/boot/config.txt"   # fallback for older Pi OS

REBOOT_NEEDED=false

# Detect available RAM for Pi 3 / low-memory tuning
MEM_MB=$(awk '/MemTotal/ { printf "%d", $2/1024 }' /proc/meminfo)
PI_MODEL=$(tr -d '\0' < /proc/device-tree/model 2>/dev/null || echo "Unknown")
LOW_MEM=false
[[ ${MEM_MB} -lt 1536 ]] && LOW_MEM=true

# ---------------------------------------------------------------------------
# Helper: add a line to config.txt if it isn't already present
# ---------------------------------------------------------------------------
add_overlay() {
    local line="$1"
    if grep -qF "${line}" "${CONFIG}"; then
        ok "Already set: ${line}"
    else
        echo "${line}" >> "${CONFIG}"
        info "Added to ${CONFIG}: ${line}"
        REBOOT_NEEDED=true
    fi
}

echo ""
echo "SmartKegerator hardware setup"
echo "Config file: ${CONFIG}"
echo ""

# ---------------------------------------------------------------------------
# 1. GPU memory split — Pi 3 / 1 GB systems need gpu_mem bumped from the
#     default 64 MB to 128 MB so the camera has enough VRAM.  Pi 4/5 have
#     dedicated VRAM and ignore this setting.
# ---------------------------------------------------------------------------
if [[ "${LOW_MEM}" == "true" ]]; then
    echo ""
    echo "── GPU memory (Pi 3 / low-memory) ──"
    if grep -q "^gpu_mem=" "${CONFIG}"; then
        CURRENT_GPU=$(grep "^gpu_mem=" "${CONFIG}" | cut -d= -f2)
        if [[ "${CURRENT_GPU}" -lt 128 ]]; then
            sed -i "s/^gpu_mem=.*/gpu_mem=128/" "${CONFIG}"
            info "gpu_mem raised from ${CURRENT_GPU} to 128 MB (camera requires ≥ 128 MB)."
            REBOOT_NEEDED=true
        else
            ok "gpu_mem already set to ${CURRENT_GPU} MB."
        fi
    else
        echo "gpu_mem=128" >> "${CONFIG}"
        info "Set gpu_mem=128 in ${CONFIG} (camera requires ≥ 128 MB on 1 GB Pi)."
        REBOOT_NEEDED=true
    fi
fi

# ---------------------------------------------------------------------------
# 2. Pi Camera Module
#    Bookworm uses libcamera natively; the legacy camera stack is optional.
#    SmartKegerator uses OpenCV + V4L2, which is provided by libcamera's
#    v4l2-compat layer.  No extra overlay is needed unless you're using
#    a non-standard sensor.
# ---------------------------------------------------------------------------
echo ""
echo "── Camera ──"
if v4l2-ctl --list-devices &>/dev/null 2>&1; then
    ok "V4L2 camera device detected — no changes needed"
else
    warn "No V4L2 device found.  If using the official Pi Camera:"
    warn "  • For Pi Camera V2 (imx219): already enabled by default in Bookworm"
    warn "  • For Pi Camera V3 (imx708): add dtoverlay=imx708 to ${CONFIG}"
    warn "  • For a USB webcam: plug it in and it should appear as /dev/video0"
    echo ""
    info "Checking /dev/video*..."
    ls /dev/video* 2>/dev/null || warn "No /dev/video* device found — camera may not be connected"
fi

# ---------------------------------------------------------------------------
# 3. GPIO permissions
#    gpiod uses the kernel chardev (/dev/gpiochip0).  Users in the 'gpio'
#    group can access it without sudo.
# ---------------------------------------------------------------------------
echo ""
echo "── GPIO permissions ──"
REAL_USER="${SUDO_USER:-pi}"
REAL_HOME=$(getent passwd "${REAL_USER}" | cut -d: -f6)
if groups "${REAL_USER}" | grep -q gpio; then
    ok "User ${REAL_USER} is already in the gpio group"
else
    usermod -aG gpio "${REAL_USER}"
    info "Added ${REAL_USER} to the gpio group (takes effect after next login)"
    REBOOT_NEEDED=true
fi

# dialout group (needed for some serial sensor interfaces)
if ! groups "${REAL_USER}" | grep -q dialout; then
    usermod -aG dialout "${REAL_USER}"
    info "Added ${REAL_USER} to the dialout group"
fi

# ---------------------------------------------------------------------------
# Screen blanking — disable for always-on kegerator display
# ---------------------------------------------------------------------------
echo ""
echo "── Screen blanking ──"

# Detect compositor
if command -v labwc &>/dev/null; then
    COMPOSITOR="labwc"
elif command -v wayfire &>/dev/null; then
    COMPOSITOR="wayfire"
else
    COMPOSITOR="unknown"
fi
info "Compositor: ${COMPOSITOR}"

# consoleblank=0 keeps the TTY console from going dark.
# On Pi5 this is managed via the compositor config instead, so skip it to
# avoid any risk of corrupting the kernel command line on Pi5's boot partition.
CMDLINE="/boot/firmware/cmdline.txt"
[[ -f "${CMDLINE}" ]] || CMDLINE="/boot/cmdline.txt"
if [[ -f "${CMDLINE}" ]]; then
    if grep -q "consoleblank=0" "${CMDLINE}"; then
        ok "consoleblank=0 already set"
    elif echo "${PI_MODEL}" | grep -qi "Raspberry Pi 5"; then
        info "Pi 5 detected — skipping cmdline.txt consoleblank (managed via compositor)."
    else
        # Back up before touching, restore on failure
        cp "${CMDLINE}" "${CMDLINE}.bak"
        # Read the first line, strip any trailing CR, append parameter
        CMDLINE_CONTENT=$(head -n1 "${CMDLINE}" | tr -d '\r')
        echo "${CMDLINE_CONTENT} consoleblank=0" > "${CMDLINE}"
        # Sanity check — file must not be empty and must contain 'root='
        if grep -q "root=" "${CMDLINE}"; then
            info "Added consoleblank=0 to ${CMDLINE}"
            rm -f "${CMDLINE}.bak"
            REBOOT_NEEDED=true
        else
            warn "cmdline.txt validation failed — restoring backup"
            cp "${CMDLINE}.bak" "${CMDLINE}"
            rm -f "${CMDLINE}.bak"
        fi
    fi
fi

case "${COMPOSITOR}" in
    wayfire)
        WAYFIRE_CONF="${REAL_HOME}/.config/wayfire.ini"
        mkdir -p "$(dirname "${WAYFIRE_CONF}")"
        chown "${REAL_USER}:${REAL_USER}" "$(dirname "${WAYFIRE_CONF}")"
        if grep -q "^\[idle\]" "${WAYFIRE_CONF}" 2>/dev/null; then
            sed -i '/^\[idle\]/,/^\[/{
                s/^screensaver_timeout *=.*/screensaver_timeout = 0/
                s/^dpms_timeout *=.*/dpms_timeout = 0/
            }' "${WAYFIRE_CONF}"
            ok "Wayfire idle timeouts set to 0"
        else
            printf '\n[idle]\nscreensaver_timeout = 0\ndpms_timeout = 0\n' >> "${WAYFIRE_CONF}"
            chown "${REAL_USER}:${REAL_USER}" "${WAYFIRE_CONF}"
            info "Disabled Wayfire screensaver/DPMS in ${WAYFIRE_CONF}"
        fi
        ;;
    labwc)
        # labwc delegates idle to swayidle; ensure it isn't blanking the screen.
        # The cleanest approach: add wlopm --on to autostart so the display
        # is forced on after the compositor starts.
        LABWC_AUTOSTART="${REAL_HOME}/.config/labwc/autostart"
        mkdir -p "$(dirname "${LABWC_AUTOSTART}")"
        chown "${REAL_USER}:${REAL_USER}" "$(dirname "${LABWC_AUTOSTART}")"
        if ! grep -q "wlopm" "${LABWC_AUTOSTART}" 2>/dev/null; then
            # Kill any swayidle instance and keep display on
            printf 'pkill swayidle 2>/dev/null || true\n' >> "${LABWC_AUTOSTART}"
            chown "${REAL_USER}:${REAL_USER}" "${LABWC_AUTOSTART}"
            info "Disabled swayidle screen blanking in labwc autostart"
        else
            ok "labwc autostart already has blanking configuration"
        fi
        ;;
    *)
        warn "Unknown compositor — disable screen blanking manually."
        ;;
esac

# ---------------------------------------------------------------------------
# GPIO chip — Pi 5 uses /dev/gpiochip4 (RP1); all others use /dev/gpiochip0
# Write gpio_chip into config.yaml so the app uses the correct device.
# ---------------------------------------------------------------------------
echo ""
echo "── GPIO chip detection ──"

CONFIG_YAML="${REAL_HOME}/SmartKegerator/src/config.yaml"
# Prefer the installed copy
[[ -f "/opt/smartkegerator/src/config.yaml" ]] && CONFIG_YAML="/opt/smartkegerator/src/config.yaml"

if echo "${PI_MODEL}" | grep -qi "Raspberry Pi 5"; then
    GPIO_CHIP="/dev/gpiochip4"
    info "Pi 5 detected — GPIO chip: ${GPIO_CHIP}"
else
    GPIO_CHIP="/dev/gpiochip0"
    info "GPIO chip: ${GPIO_CHIP}"
fi

if [[ -f "${CONFIG_YAML}" ]]; then
    if grep -q "gpio_chip:" "${CONFIG_YAML}"; then
        sed -i "s|gpio_chip:.*|gpio_chip: ${GPIO_CHIP}|" "${CONFIG_YAML}"
    else
        # Insert under [hardware] if present, or append at end of file
        if grep -q "^hardware:" "${CONFIG_YAML}"; then
            sed -i "/^hardware:/a\\  gpio_chip: ${GPIO_CHIP}" "${CONFIG_YAML}"
        else
            echo "" >> "${CONFIG_YAML}"
            echo "hardware:" >> "${CONFIG_YAML}"
            echo "  gpio_chip: ${GPIO_CHIP}" >> "${CONFIG_YAML}"
        fi
    fi
    info "gpio_chip written to ${CONFIG_YAML}"
else
    warn "config.yaml not found at ${CONFIG_YAML} — set hardware.gpio_chip: ${GPIO_CHIP} manually"
fi

# ---------------------------------------------------------------------------
# Display rotation — managed via web UI (Settings → Appearance)
#    Remove any rotation line written by older versions of this script.
# ---------------------------------------------------------------------------
echo ""
echo "── Display rotation ──"

if [[ -f "${REAL_HOME}/.config/labwc/autostart" ]]; then
    if grep -q "wlr-randr.*DSI-1.*transform" "${REAL_HOME}/.config/labwc/autostart"; then
        sed -i '/wlr-randr --output DSI-1 --transform/d' "${REAL_HOME}/.config/labwc/autostart"
        info "Removed stale wlr-randr rotation line — configure via web UI."
        REBOOT_NEEDED=true
    fi
fi
info "Display rotation is configured via Settings → Appearance in the web UI."

# ---------------------------------------------------------------------------
# Permanent swap — Pi 3 / 1 GB only
#
# dlib face encoding uses ~350-400 MB peak per image.  Combined with the
# Qt GUI (~250 MB) and web server (~120 MB) the OOM killer fires on 1 GB
# systems.  A 1 GB swap file on the SD card gives enough headroom without
# noticeably affecting runtime speed (encoding is CPU-bound, not RAM-bound).
# ---------------------------------------------------------------------------
if [[ "${LOW_MEM}" == "true" ]]; then
    echo ""
    echo "── Permanent swap (Pi 3 / low-memory) ──"
    SWAP_FILE="/opt/smartkegerator/runtime-swap"
    SWAP_SIZE_MB=1024

    if swapon --show | grep -qF "${SWAP_FILE}"; then
        ok "Runtime swap already active at ${SWAP_FILE}."
    else
        if [[ ! -f "${SWAP_FILE}" ]]; then
            info "Creating ${SWAP_SIZE_MB} MB swap at ${SWAP_FILE}..."
            fallocate -l "${SWAP_SIZE_MB}M" "${SWAP_FILE}" 2>/dev/null || \
                dd if=/dev/zero of="${SWAP_FILE}" bs=1M count="${SWAP_SIZE_MB}" status=none
            chmod 600 "${SWAP_FILE}"
            mkswap "${SWAP_FILE}" -q
            info "Swap file created."
        fi
        swapon "${SWAP_FILE}"
        ok "Swap active: $(free -h | awk '/Swap/{print $2}') total."
    fi

    # Persist across reboots via /etc/fstab
    if ! grep -qF "${SWAP_FILE}" /etc/fstab; then
        echo "${SWAP_FILE} none swap sw 0 0" >> /etc/fstab
        info "Added swap to /etc/fstab (persists across reboots)."
    else
        ok "Swap already in /etc/fstab."
    fi
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
if [[ "${REBOOT_NEEDED}" == "true" ]]; then
    echo -e "${YELLOW}A reboot is required for hardware changes to take effect.${NC}"
    info "Reboot when ready:  sudo reboot"
else
    ok "All hardware already configured — no reboot needed."
fi
echo ""
