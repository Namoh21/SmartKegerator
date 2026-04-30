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
# 1. 1-Wire (DS18B20 liquid temperature sensor)
#    Default GPIO: pin 4.  Set w1-gpio,gpiopin=X to change.
# ---------------------------------------------------------------------------
echo "── 1-Wire (DS18B20) ──"
add_overlay "dtoverlay=w1-gpio"

# Confirm the w1-therm kernel module is available
if modinfo w1-therm &>/dev/null; then
    modprobe w1-therm 2>/dev/null || true
    ok "w1-therm module loaded"
else
    warn "w1-therm module not found — may need 'sudo apt install raspberrypi-kernel'"
fi

# ---------------------------------------------------------------------------
# 1b. GPU memory split — Pi 3 / 1 GB systems need gpu_mem bumped from the
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
# 4. SPI (not needed by default — uncomment if you add SPI peripherals)
# ---------------------------------------------------------------------------
# add_overlay "dtparam=spi=on"

# ---------------------------------------------------------------------------
# 5. I2C (not needed by default — uncomment if you add I2C peripherals)
# ---------------------------------------------------------------------------
# add_overlay "dtparam=i2c_arm=on"

# ---------------------------------------------------------------------------
# 6. Verify DS18B20 sensor ID (helps populate config.yaml)
# ---------------------------------------------------------------------------
echo ""
echo "── DS18B20 sensor check ──"
W1_DIR="/sys/bus/w1/devices"
if [[ -d "${W1_DIR}" ]]; then
    SENSORS=$(ls "${W1_DIR}" | grep "^28-" || true)
    if [[ -n "${SENSORS}" ]]; then
        for s in ${SENSORS}; do
            ok "Found DS18B20: ${s}"
            echo "    Add to config.yaml:  liquid_temp_sensor_id: \"${s}\""
        done
    else
        warn "No DS18B20 sensor found in ${W1_DIR}"
        warn "Check wiring: DATA pin → GPIO 4 (BCM), with 4.7kΩ pull-up to 3.3V"
    fi
else
    info "1-Wire sysfs not yet loaded (reboot required before sensor appears)"
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

# consoleblank=0 keeps the TTY console from going dark (all compositors)
CMDLINE="/boot/firmware/cmdline.txt"
[[ -f "${CMDLINE}" ]] || CMDLINE="/boot/cmdline.txt"
if [[ -f "${CMDLINE}" ]]; then
    if ! grep -q "consoleblank=0" "${CMDLINE}"; then
        # Modify only line 1 — 's/$/' matches every line including trailing
        # empty lines, which corrupts the single-line kernel command line.
        sed -i '1s/$/ consoleblank=0/' "${CMDLINE}"
        info "Added consoleblank=0 to ${CMDLINE}"
        REBOOT_NEEDED=true
    else
        ok "consoleblank=0 already set"
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
