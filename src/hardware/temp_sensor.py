"""
Temperature and humidity sensor manager.

Reads the DHT22 ambient temperature + humidity sensor via GPIO
using the adafruit-circuitpython-dht library.

Emits a Qt signal on every successful reading so the UI can update in real time.
All sensor I/O happens in a daemon thread; signals are emitted from that thread
and automatically queued to the main thread by Qt.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

log = logging.getLogger(__name__)

import os
from hardware.pi_model import pi_generation as _pi_gen

# adafruit-blinka selects its GPIO backend at import time via environment
# variables.  On Pi 5 the RPi.GPIO backend doesn't exist; BLINKA_LGPIO=1
# tells blinka to use the lgpio C library instead.  This must be set
# before any adafruit/blinka import occurs.
if _pi_gen() == 5:
    os.environ.setdefault("BLINKA_LGPIO", "1")
    log.debug("Pi 5 detected — using lgpio backend for adafruit_dht")

try:
    import adafruit_dht
    import board as _board
    _DHT_AVAILABLE = True
    log.debug("adafruit_dht imported successfully")
except ImportError:
    _DHT_AVAILABLE = False
    log.warning("adafruit_dht not available — DHT22 readings will be stubbed (dev/non-Pi mode)")

_READ_INTERVAL_SECONDS = 30.0
_MAX_DELTA_F = 20.0      # ignore readings that jump more than this between samples
_RETRY_LIMIT  = 3        # attempts per reading cycle before giving up
_MIN_SANE_F   = 14.0     # -10°C — below this is a bad reading (kegerator is indoors)
_MAX_SANE_F   = 120.0    # 49°C — above this is a bad reading
_MIN_SANE_HUM = 1.0      # % — below this is a bad reading
_MAX_SANE_HUM = 100.0


class TempSensorManager(QObject):
    """
    Polls the DHT22 sensor on a background thread and exposes the latest
    readings via properties and a Qt signal.

    Readings are in Fahrenheit to match the original application.

    Signals:
        readings_updated(ambient_f, humidity_pct)
            Emitted whenever a successful reading cycle completes.
            Either value may be None if the sensor failed.
    """

    readings_updated = pyqtSignal(object, object)  # (float|None) × 2

    def __init__(self, config: dict, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)

        hw = config.get("hardware", {})
        self._dht_pin_num = hw.get("temp_sensor_dht_pin", 22)
        self._power_pin   = hw.get("temp_sensor_power_pin", 17)
        self._interval    = _READ_INTERVAL_SECONDS

        self.ambient_f: Optional[float] = None
        self.humidity:  Optional[float] = None

        self._prev_ambient_f: Optional[float] = None

        self._dht_device = None
        self._running    = False
        self._thread:    Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Public control
    # ------------------------------------------------------------------

    def start(self, gpio_manager=None) -> None:
        self._gpio = gpio_manager
        self._init_dht()
        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop, name="temp-sensor", daemon=True
        )
        self._thread.start()
        log.info("TempSensorManager started (DHT22 pin %d)", self._dht_pin_num)

    def stop(self) -> None:
        self._running = False
        if self._dht_device is not None:
            try:
                self._dht_device.exit()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Sensor init
    # ------------------------------------------------------------------

    def _init_dht(self) -> None:
        if not _DHT_AVAILABLE:
            return
        try:
            pin = getattr(_board, f"D{self._dht_pin_num}")
            self._dht_device = adafruit_dht.DHT22(pin, use_pulseio=False)
        except Exception as exc:
            log.error("Failed to initialise DHT22 on pin %d: %s", self._dht_pin_num, exc)
            self._dht_device = None

    # ------------------------------------------------------------------
    # Poll loop (background thread)
    # ------------------------------------------------------------------

    def _poll_loop(self) -> None:
        while self._running:
            self._read_dht22()
            self.readings_updated.emit(self.ambient_f, self.humidity)
            time.sleep(self._interval)

    # ------------------------------------------------------------------
    # DHT22 (ambient temperature + humidity)
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

                # Hard sanity range — reject physically impossible values
                # before they reach the UI or database.
                if not (_MIN_SANE_F <= temp_f <= _MAX_SANE_F):
                    log.warning(
                        "DHT22: rejecting out-of-range reading %.1f°F (%.1f°C) "
                        "— check wiring and pull-up resistor",
                        temp_f, temp_c,
                    )
                    time.sleep(2.0)
                    continue

                if not (_MIN_SANE_HUM <= humidity <= _MAX_SANE_HUM):
                    log.warning(
                        "DHT22: rejecting out-of-range humidity %.1f%% "
                        "— check wiring and pull-up resistor",
                        humidity,
                    )
                    time.sleep(2.0)
                    continue

                # Delta filter — ignore sudden jumps between successive reads
                if self._prev_ambient_f is not None:
                    if abs(temp_f - self._prev_ambient_f) > _MAX_DELTA_F:
                        log.warning(
                            "DHT22: ignoring suspicious jump %.1f°F → %.1f°F",
                            self._prev_ambient_f, temp_f,
                        )
                        return

                self.ambient_f       = temp_f
                self.humidity        = humidity
                self._prev_ambient_f = temp_f
                log.debug("DHT22: %.1f°F (%.1f°C), %.1f%%", temp_f, temp_c, humidity)
                return

            except RuntimeError as exc:
                log.debug("DHT22 read attempt %d failed: %s", attempt + 1, exc)
                time.sleep(2.0)
            except Exception as exc:
                log.error("DHT22 unexpected error: %s", exc)
                self._reset_dht()
                return

        log.warning("DHT22: all %d read attempts failed", _RETRY_LIMIT)

    def _reset_dht(self) -> None:
        """Power-cycle the sensor via the GPIO power pin and reinitialise."""
        log.info("DHT22: resetting sensor")
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
        self._init_dht()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _c_to_f(celsius: float) -> float:
    return celsius * 9.0 / 5.0 + 32.0
