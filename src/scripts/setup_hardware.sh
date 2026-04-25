#!/usr/bin/env bash
# =============================================================================
# SmartKegerator hardware setup — Raspberry Pi 4, Pi OS Bookworm
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
# Done
# ---------------------------------------------------------------------------
echo ""
if [[ "${REBOOT_NEEDED}" == "true" ]]; then
    echo -e "${YELLOW}A reboot is required for hardware changes to take effect.${NC}"
    echo ""
    read -rp "Reboot now? [y/N] " ans
    if [[ "${ans,,}" == "y" ]]; then
        reboot
    else
        info "Reboot when ready:  sudo reboot"
    fi
else
    ok "All hardware already configured — no reboot needed."
fi
echo ""
