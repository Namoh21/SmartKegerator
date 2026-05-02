"""
Temperature and humidity sensor manager.

Supports two sensor types, selected via config.yaml hardware.temp_sensor_type:

  aht20  (default, recommended) — Adafruit AHT20 / AHT21 / AHT25
           I2C interface, works on Pi 3/4/5 identically.
           Wiring: VCC→3.3V  SDA→GPIO2  SCL→GPIO3  GND→GND
           No pull-up resistor needed.

  dht22  (legacy) — DHT22 / AM2302
           Bit-bang GPIO, works on Pi 3/4.
           NOT supported on Pi 5 (RP1 GPIO timing incompatible).
           Wiring: VCC→3.3V  Data→GPIO22 (+ 4.7kΩ pull-up to 3.3V)  GND→GND

All sensor I/O runs in a daemon thread; readings are exposed via a Qt signal
so the UI can update in real time without blocking.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

from hardware.pi_model import pi_generation as _pi_gen

log = logging.getLogger(__name__)

_PI_GEN = _pi_gen()

# ---------------------------------------------------------------------------
# Library availability checks
# ---------------------------------------------------------------------------

try:
    import adafruit_ahtx0
    import board as _board
    import busio as _busio
    _AHT20_AVAILABLE = True
except ImportError:
    _AHT20_AVAILABLE = False
    log.debug("adafruit_ahtx0 not available (dev/non-Pi mode)")

try:
    import adafruit_dht
    import board as _board          # noqa: F811 — re-import is harmless
    _DHT_AVAILABLE = True
except ImportError:
    _DHT_AVAILABLE = False
    log.debug("adafruit_dht not available (dev/non-Pi mode)")

# ---------------------------------------------------------------------------
# Sanity limits
# ---------------------------------------------------------------------------

_READ_INTERVAL_SECONDS = 30.0
_MAX_DELTA_F  = 20.0    # reject readings that jump more than this between samples
_RETRY_LIMIT  = 3       # DHT22 attempts per cycle
_MIN_SANE_F   = 14.0    # -10°C — below this is a bad reading
_MAX_SANE_F   = 120.0   # 49°C  — above this is a bad reading
_MIN_SANE_HUM = 1.0
_MAX_SANE_HUM = 100.0


class TempSensorManager(QObject):
    """
    Polls the ambient temperature/humidity sensor on a background thread.
    Readings are in Fahrenheit.

    Signals:
        readings_updated(ambient_f, humidity_pct)
            Emitted on every successful read. Either value may be None.
    """

    readings_updated = pyqtSignal(object, object)   # (float|None) × 2

    def __init__(self, config: dict, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)

        hw = config.get("hardware", {})
        self._sensor_type = hw.get("temp_sensor_type", "aht20").lower()
        self._dht_pin_num = hw.get("temp_sensor_dht_pin", 22)
        self._power_pin   = hw.get("temp_sensor_power_pin", 17)
        self._interval    = _READ_INTERVAL_SECONDS

        self.ambient_f: Optional[float] = None
        self.humidity:  Optional[float] = None
        self._prev_f:   Optional[float] = None

        self._aht_device = None
        self._dht_device = None
        self._running    = False
        self._thread:    Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Public control
    # ------------------------------------------------------------------

    def start(self, gpio_manager=None) -> None:
        self._gpio = gpio_manager

        # Guard: DHT22 is not supported on Pi 5
        if self._sensor_type == "dht22" and _PI_GEN == 5:
            log.warning(
                "DHT22 is not supported on Pi 5 (RP1 GPIO timing incompatible). "
                "Set hardware.temp_sensor_type: aht20 in config.yaml and wire an "
                "AHT20 sensor to the I2C pins (SDA=GPIO2, SCL=GPIO3)."
            )
            self._sensor_type = "none"

        self._init_sensor()
        self._running = True
        self._thread  = threading.Thread(
            target=self._poll_loop, name="temp-sensor", daemon=True
        )
        self._thread.start()
        log.info("TempSensorManager started (type=%s)", self._sensor_type)

    def stop(self) -> None:
        self._running = False
        if self._dht_device is not None:
            try:
                self._dht_device.exit()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _init_sensor(self) -> None:
        if self._sensor_type == "aht20":
            self._init_aht20()
        elif self._sensor_type == "dht22":
            self._init_dht22()

    def _init_aht20(self) -> None:
        if not _AHT20_AVAILABLE:
            log.warning(
                "adafruit_ahtx0 library not installed — "
                "run: pip install adafruit-circuitpython-ahtx0"
            )
            return
        try:
            i2c = _busio.I2C(_board.SCL, _board.SDA)
            self._aht_device = adafruit_ahtx0.AHTx0(i2c)
            log.info("AHT20 sensor initialised on I2C (SDA=GPIO2, SCL=GPIO3)")
        except Exception as exc:
            log.error(
                "Failed to initialise AHT20 on I2C: %s — "
                "check wiring: VCC→3.3V  SDA→GPIO2  SCL→GPIO3  GND→GND",
                exc,
            )
            self._aht_device = None

    def _init_dht22(self) -> None:
        if not _DHT_AVAILABLE:
            log.warning("adafruit_dht not available — DHT22 stubbed")
            return
        try:
            pin = getattr(_board, f"D{self._dht_pin_num}")
            self._dht_device = adafruit_dht.DHT22(pin, use_pulseio=False)
            log.info("DHT22 sensor initialised on GPIO %d", self._dht_pin_num)
        except Exception as exc:
            log.error("Failed to initialise DHT22 on GPIO %d: %s", self._dht_pin_num, exc)
            self._dht_device = None

    # ------------------------------------------------------------------
    # Poll loop
    # ------------------------------------------------------------------

    def _poll_loop(self) -> None:
        while self._running:
            if self._sensor_type == "aht20":
                self._read_aht20()
            elif self._sensor_type == "dht22":
                self._read_dht22()
            self.readings_updated.emit(self.ambient_f, self.humidity)
            time.sleep(self._interval)

    # ------------------------------------------------------------------
    # AHT20 read
    # ------------------------------------------------------------------

    def _read_aht20(self) -> None:
        if self._aht_device is None:
            return
        try:
            temp_c   = self._aht_device.temperature
            humidity = self._aht_device.relative_humidity
        except Exception as exc:
            log.warning("AHT20 read error: %s", exc)
            return

        if temp_c is None or humidity is None:
            log.warning("AHT20 returned None — check wiring")
            return

        temp_f = _c_to_f(temp_c)
        if not self._sanity_check(temp_f, temp_c, humidity, "AHT20"):
            return

        self.ambient_f = temp_f
        self.humidity  = humidity
        self._prev_f   = temp_f
        log.debug("AHT20: %.1f°F (%.1f°C), %.1f%%", temp_f, temp_c, humidity)

    # ------------------------------------------------------------------
    # DHT22 read (Pi 3/4 only)
    # ------------------------------------------------------------------

    def _read_dht22(self) -> None:
        if self._dht_device is None:
            return

        for attempt in range(_RETRY_LIMIT):
            try:
                temp_c   = self._dht_device.temperature
                humidity = self._dht_device.humidity

                if temp_c is None or humidity is None:
                    raise RuntimeError("Sensor returned None")

                temp_f = _c_to_f(temp_c)
                if not self._sanity_check(temp_f, temp_c, humidity, "DHT22"):
                    time.sleep(2.0)
                    continue

                self.ambient_f = temp_f
                self.humidity  = humidity
                self._prev_f   = temp_f
                log.debug("DHT22: %.1f°F (%.1f°C), %.1f%%", temp_f, temp_c, humidity)
                return

            except RuntimeError as exc:
                log.debug("DHT22 read attempt %d failed: %s", attempt + 1, exc)
                time.sleep(2.0)
            except Exception as exc:
                log.error("DHT22 unexpected error: %s", exc)
                self._reset_dht22()
                return

        log.warning("DHT22: all %d read attempts failed — check wiring", _RETRY_LIMIT)

    def _reset_dht22(self) -> None:
        log.info("DHT22: resetting sensor via power pin")
        if self._gpio is not None:
            self._gpio.write(self._power_pin, False)
            time.sleep(1.0)
            self._gpio.write(self._power_pin, True)
            time.sleep(2.0)
        if self._dht_device is not None:
            try:
                self._dht_device.exit()
            except Exception:
                pass
        self._init_dht22()

    # ------------------------------------------------------------------
    # Shared sanity filter
    # ------------------------------------------------------------------

    def _sanity_check(self, temp_f: float, temp_c: float,
                      humidity: float, label: str) -> bool:
        if not (_MIN_SANE_F <= temp_f <= _MAX_SANE_F):
            log.warning(
                "%s: out-of-range temp %.1f°F (%.1f°C) — check wiring",
                label, temp_f, temp_c,
            )
            return False
        if not (_MIN_SANE_HUM <= humidity <= _MAX_SANE_HUM):
            log.warning("%s: out-of-range humidity %.1f%% — check wiring", label, humidity)
            return False
        if self._prev_f is not None and abs(temp_f - self._prev_f) > _MAX_DELTA_F:
            log.warning(
                "%s: ignoring suspicious jump %.1f°F → %.1f°F",
                label, self._prev_f, temp_f,
            )
            return False
        return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _c_to_f(celsius: float) -> float:
    return celsius * 9.0 / 5.0 + 32.0
