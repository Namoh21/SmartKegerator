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
- **Temperature monitoring** — DS18B20 liquid sensor + DHT22 ambient sensor
- **Admin PIN login** — touchscreen fallback when face recognition isn't set up yet

---

## Supported Hardware

| Model | OS | Notes |
|---|---|---|
| Raspberry Pi 5 (4/8 GB) | Bookworm or Trixie | Recommended |
| Raspberry Pi 4 (2/4 GB) | Bookworm or Trixie | Fully supported |
| Raspberry Pi 3B / 3B+ (1 GB) | Bookworm or Trixie | Supported — longer install time |

---

## Fresh Install

### 1. Flash the Pi

Use **Raspberry Pi Imager** and select **Raspberry Pi OS (64-bit)** — Bookworm or Trixie.
During imaging, configure your username, password, Wi-Fi, and hostname so the Pi is
accessible over SSH on first boot without a keyboard.

### 2. Clone the repo

```bash
cd ~
git clone https://github.com/Namoh21/SmartKegerator.git
cd SmartKegerator
```

### 3. Run the installer

```bash
sudo bash src/scripts/install.sh
```

The installer handles everything automatically:

- Detects RAM and creates a temporary swap file on Pi 3 / 1 GB systems (required for dlib build)
- Installs system packages via `apt` (OpenCV, PyQt6, gpiod, picamera2, etc.)
- Creates a Python venv at `/opt/smartkegerator/venv`
- Builds or downloads dlib (see [Speeding up the dlib build](#speeding-up-the-dlib-build) below)
- Creates the data, photos, and logs directory tree
- Installs and enables two systemd user services (`smartkegerator` and `smartkegerator-web`)
- Configures the Wayland compositor autostart (labwc on Trixie, Wayfire on Bookworm)
- Runs hardware setup (1-Wire, GPIO permissions, screen blanking)

**Expected install time:**
- Pi 5: ~10–15 minutes
- Pi 4: ~25–30 minutes
- Pi 3: ~60–90 minutes (dlib compiles from source)

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
  liquid_temp_sensor_id: "28-xxxxxxxxxxxx"   # from raspi-config → 1-Wire
  temp_sensor_power_pin: 17
```

Run the hardware setup script to enable 1-Wire and configure the display:

```bash
sudo bash src/scripts/setup_hardware.sh
```

### 5. Reboot

```bash
sudo reboot
```

Both services start automatically on boot. The touchscreen GUI launches via the compositor autostart.

### 6. First-time web setup

Open a browser on any device on the same network:

```
http://<pi-ip>:8080
```

1. **Create an admin account** — Settings → Administrators → Add Administrator
2. **Set your touchscreen PIN** — Settings → Administrators → Set PIN
   (This is how you log in on the touchscreen before face recognition is trained)
3. **Configure display rotation** — Settings → Appearance → Display rotation
4. **Add beers and kegs** — Beers → Add Beer, Kegs → Add Keg
5. **Add users and train face recognition** — Users → Add User → Capture Photo → Train Recognition

---

## Speeding Up the dlib Build

dlib takes 10–90 minutes to compile from source depending on the Pi model.
A pre-built wheel is hosted on GitHub Releases and downloaded automatically
by the installer — no action needed if the wheel matches your Python version.

**Wheel coverage:**

| Pi OS | Python | Wheel |
|---|---|---|
| Bookworm | 3.11 | `dlib-20.0.1-cp311-cp311-linux_aarch64.whl` |
| Trixie | 3.13 | `dlib-20.0.1-cp313-cp313-linux_aarch64.whl` |

**To build and upload a new wheel** after a source build completes:

```bash
gh release upload dlib-wheels \
    --repo Namoh21/SmartKegerator \
    /opt/smartkegerator/wheel-cache/dlib-*.whl
```

**To reuse a wheel across reinstalls**, back up the cache before reimaging:

```bash
# Back up (from the Pi)
cp -r /opt/smartkegerator/wheel-cache /media/usb/

# Restore (after cloning, before running install.sh)
sudo mkdir -p /opt/smartkegerator
sudo cp -r /media/usb/wheel-cache /opt/smartkegerator/
```

---

## Updating

```bash
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
│   └── temp_sensor.py       # DS18B20 + DHT22
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
