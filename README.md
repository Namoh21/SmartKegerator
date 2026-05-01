# SmartKegerator

A Python 3 rewrite of the original C++ SmartKegerator controller for Raspberry Pi.
Manages draft beer taps with flow metering, facial recognition pour tracking,
a touchscreen UI, and a web interface accessible from any device on the network.

Original concept by [PhilsProjects](https://philsprojects.wordpress.com/2015/07/31/smartkegerator-v2-installation-guide/)

---

## Features

- **Touchscreen UI** — tap cards with beer info, keg levels, and pour history (PyQt6 / Wayland)
- **Facial recognition** — identifies who's pouring via Pi Camera (dlib ResNet)
- **Web interface** — manage beers, kegs, users, pours, and settings from any browser
- **REST API** — Android app support with JWT authentication
- **Push notifications** — pour alerts, keg-low warnings, temperature alerts (polling-based, no Firebase required)
- **Multi-tap** — up to 4 taps with configurable GPIO pins
- **Temperature monitoring** — DHT22 ambient temperature + humidity sensor
- **Admin PIN login** — touchscreen fallback when face recognition isn't set up yet

---

## Supported Hardware

| Model | OS | Notes |
|---|---|---|
| Raspberry Pi 5 (4/8 GB) | Trixie | Recommended |
| Raspberry Pi 4 (2/4 GB) | Trixie | Fully supported |
| Raspberry Pi 3B / 3B+ (1 GB) | Trixie | Supported — longer install time |

> **Pi 5 power supply:** Use the official 27W USB-C supply (5V/5A). Underpowered
> supplies cause random crashes during compilation and runtime instability.

---

## Fresh Install

### 1. Flash the Pi

Use **Raspberry Pi Imager** and select **Raspberry Pi OS (64-bit)** — Trixie.

During imaging *(click the gear/settings icon before writing)*:
- Set **hostname** (e.g. `smartkegerator`)
- Set **username and password**
- Configure **Wi-Fi**
- Enable **SSH**

This lets you connect over SSH on first boot without a monitor or keyboard.

### 2. SSH in and clone the repo

```bash
ssh <username>@smartkegerator.local

cd ~
git clone https://github.com/Namoh21/SmartKegerator.git
cd SmartKegerator
```

### 3. Run the installer

```bash
sudo bash src/scripts/install.sh
```

The installer runs unattended and handles everything:

- Detects RAM — creates a **temporary** build swap on Pi 3 (1 GB) so dlib can compile
- Installs system packages via `apt` (OpenCV, PyQt6, gpiod, picamera2, etc.)
- Creates a Python venv at `/opt/smartkegerator/venv`
- Downloads a pre-built dlib wheel from GitHub Releases, or builds from source if none matches
- Creates the data, photos, and logs directory tree
- Installs and enables two systemd services (`smartkegerator` and `smartkegerator-web`)
- Configures the Wayland compositor autostart (labwc on Trixie, Wayfire on Bookworm)
- Runs hardware setup — GPIO permissions, permanent swap (Pi 3), screen blanking

**Expected install time:**
| Model | Time | Notes |
|---|---|---|
| Pi 5 | 10–15 min | Fast; dlib installs from pre-built wheel |
| Pi 4 | 25–30 min | dlib installs from pre-built wheel |
| Pi 3 | 60–90 min | dlib compiles from source; wheel cached afterward |

**Harmless warnings you may see during install:**

- `WARNING: Error parsing dependencies of send2trash` — noise from a system package, ignore it
- `dependency conflict` warnings for `types-seaborn` or similar — system package stubs, ignore them
- The dlib pip step may pause silently for **5–10 minutes** on Pi 3/4 while unpacking — this is normal

### 4. Configure hardware

Edit the config file to match your wiring:

```bash
nano /opt/smartkegerator/src/config.yaml
```

Key settings:

```yaml
taps:
  count: 3
  tap1:
    name: Left
    pin: 23          # BCM GPIO pin for flow meter
  tap2:
    name: Center
    pin: 24
  tap3:
    name: Right
    pin: 25

hardware:
  camera_index: 0
  temp_sensor_power_pin: 17
```

Run hardware setup to set GPIO permissions and (on Pi 3) create the
permanent runtime swap that prevents OOM crashes during face recognition training:

```bash
sudo bash src/scripts/setup_hardware.sh
```

### 5. Reboot

```bash
sudo reboot
```

Both services start automatically on boot. The touchscreen GUI launches via the
compositor autostart 5–15 seconds after the desktop appears.

### 6. First-time web setup

Open a browser on any device on the same network:

```
http://<pi-hostname>.local:8080
```

Complete these steps in order:

1. **Create an admin account** — Settings → Administrators → Add Administrator
2. **Set your touchscreen PIN** — Settings → Administrators → Set PIN
   *(required to access Settings on the touchscreen before face recognition is trained)*
3. **Set display rotation** — Settings → Appearance → Display rotation
   *(90° clockwise for a portrait touchscreen mounted in landscape)*
4. **Add beers and kegs** — Beers → Add Beer, then Kegs → Add Keg
5. **Add users and train face recognition** — Users → Add User → Capture Photo (×5) → Train Recognition

---

## Troubleshooting

### Touchscreen shows desktop but not the kiosk app

The app launches ~10 seconds after the desktop. If it never appears:

```bash
# Check service status
systemctl --user status smartkegerator --no-pager

# Check logs
tail -50 /opt/smartkegerator/logs/smartkegerator-gui.log

# Try launching manually (run this on the Pi with the desktop visible)
WAYLAND_DISPLAY=wayland-0 QT_QPA_PLATFORM=wayland \
  /opt/smartkegerator/src/scripts/launch_gui.sh
```

If the manual launch works but autostart doesn't, the compositor autostart entry may
be missing. Rerun the installer — it is safe to run again:

```bash
sudo bash ~/SmartKegerator/src/scripts/install.sh
```

### dlib SIGILL crash on Pi 5 (Illegal instruction)

The pre-built dlib wheel in GitHub Releases was compiled on a Pi 3 (Cortex-A53).
On Pi 5 (Cortex-A76), its BLAS dispatch can emit instructions that crash at runtime.

**Fix:** rebuild dlib natively on the Pi 5. GCC 12 on Bookworm has a known bug that
causes `cc1: internal compiler error: Segmentation fault` — use **clang** instead:

```bash
sudo apt install -y clang

# Uninstall the broken wheel
/opt/smartkegerator/venv/bin/pip uninstall dlib -y

# Build with clang (~10-15 min)
CC=clang CXX=clang++ CMAKE_BUILD_PARALLEL_LEVEL=4 \
  /opt/smartkegerator/venv/bin/python3 -m pip wheel \
  --no-deps -w /opt/smartkegerator/wheel-cache dlib

# Install and verify
/opt/smartkegerator/venv/bin/pip install \
  --no-index --find-links /opt/smartkegerator/wheel-cache dlib

/opt/smartkegerator/venv/bin/python3 -c "import dlib; print('dlib ok', dlib.version.VERSION)"
```

After a successful build, upload the Pi 5 wheel so future installs skip this:

```bash
gh release upload dlib-wheels \
  --repo Namoh21/SmartKegerator \
  /opt/smartkegerator/wheel-cache/dlib-*.whl
```

### Face recognition training crashes on Pi 3

The Pi 3 (1 GB RAM) can be OOM-killed during training if the runtime swap isn't active.
Run hardware setup to create the permanent swap:

```bash
sudo bash ~/SmartKegerator/src/scripts/setup_hardware.sh
```

Confirm swap is active before training:

```bash
free -h   # Swap line should show ~1 GB
```

### pip install fails with IncompleteRead / network error

A transient download failure. The installer retries automatically (`--retries 5`).
If it still fails, re-run the installer — it skips steps already completed:

```bash
sudo bash ~/SmartKegerator/src/scripts/install.sh
```

---

## Speeding Up the dlib Build

dlib takes 10–90 minutes to compile from source depending on the Pi model.
Pre-built wheels are hosted on GitHub Releases and downloaded automatically
by the installer — no action needed if a matching wheel exists.

**Wheel coverage:**

| Pi OS | Python | Wheel |
|---|---|---|
| Bookworm (Pi 3/4) | 3.11 | `dlib-20.0.1-cp311-cp311-linux_aarch64.whl` |
| Bookworm (Pi 5) | 3.11 | `dlib-20.0.1-cp311-cp311-linux_aarch64.whl` *(build with clang, upload separately)* |
| Trixie | 3.13 | `dlib-20.0.1-cp313-cp313-linux_aarch64.whl` |

**To build and upload a new wheel** after a source build completes:

```bash
gh release upload dlib-wheels \
    --repo Namoh21/SmartKegerator \
    /opt/smartkegerator/wheel-cache/dlib-*.whl
```

**To reuse a wheel across reinstalls**, back up the cache before reimaging:

```bash
# Back up (from the Pi, to a USB drive)
cp -r /opt/smartkegerator/wheel-cache /media/usb/

# Restore (after cloning, before running install.sh)
sudo mkdir -p /opt/smartkegerator
sudo cp -r /media/usb/wheel-cache /opt/smartkegerator/
```

---

## Updating

```bash
# If you see "Permission denied" on git pull, fix ownership first:
sudo chown -R $(whoami):$(whoami) ~/SmartKegerator

cd ~/SmartKegerator
bash src/scripts/update.sh
```

Pulls the latest code, syncs to `/opt/smartkegerator/src/`, and restarts both services.
`config.yaml` is never overwritten.

---

## Log Files

Application logs are written to `/opt/smartkegerator/logs/`:

| File | Contents |
|---|---|
| `smartkegerator-gui.log` | Touchscreen app — camera, recognition, pours, PIN login |
| `smartkegerator-web.log` | Web server — HTTP requests, API calls, errors |

Logs rotate at 5 MB and keep 5 backups. They can also be viewed and downloaded
from the web UI: **Settings → Administrators → Application Logs**.

---

## Services

| Service | Description |
|---|---|
| `smartkegerator.service` | PyQt6 touchscreen GUI |
| `smartkegerator-web.service` | FastAPI web interface (port 8080) |

```bash
# Status
systemctl --user status smartkegerator.service
systemctl --user status smartkegerator-web.service

# Restart
systemctl --user restart smartkegerator smartkegerator-web

# View live logs
journalctl --user -u smartkegerator -f
journalctl --user -u smartkegerator-web -f
```

---

## Architecture

```
src/
├── main.py                  # Touchscreen app entry point
├── config.yaml.example      # Configuration template
├── data/
│   ├── database.py          # SQLite (WAL mode)
│   └── models.py            # Beer, Keg, Pour, User dataclasses
├── hardware/
│   ├── camera.py            # OpenCV / picamera2 capture (auto-detected)
│   ├── flow_meter.py        # GPIO pulse counting
│   └── temp_sensor.py       # DHT22 ambient sensor
├── recognition/
│   └── face_recognizer.py   # dlib ResNet face detection + encoding
├── ui/
│   ├── app.py               # Qt coordinator — wires all subsystems
│   ├── main_window.py       # Home screen (tap cards, header, footer)
│   ├── pouring_window.py    # Full-screen pour display
│   ├── settings_window.py   # Admin settings dialog
│   ├── users_window.py      # User management + photo capture
│   └── pin_login_dialog.py  # Touchscreen PIN login
└── web/
    ├── server.py            # FastAPI app + middleware
    ├── routes/              # Web UI routes (beers, kegs, users, pours, settings)
    │   └── api/             # REST API v1 (JWT auth, Android app)
    └── templates/           # Jinja2 + HTMX + Bootstrap 5
```
