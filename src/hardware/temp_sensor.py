"""
Temperature and humidity sensor manager.

Reads two sensors:
  • DHT22  — ambient temperature + humidity (GPIO pin, via adafruit-circuitpython-dht)
  • DS18B20 — liquid temperature in the keg line (1-Wire sysfs interface)

Replaces the original approach of spawning loldht/loldht22 as subprocesses
and parsing their stdout. Both sensors are now read directly in Python.

Emits a Qt signal on every successful reading so the UI can update in real time.
All sensor I/O happens in a daemon thread; signals are emitted from that thread
and automatically queued to the main thread by Qt.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

log = logging.getLogger(__name__)

try:
    import adafruit_dht
    import board as _board
    _DHT_AVAILABLE = True
except ImportError:
    _DHT_AVAILABLE = False
    log.warning("adafruit_dht not available — DHT22 readings will be stubbed (dev/non-Pi mode)")

_W1_BASE = Path("/sys/bus/w1/devices")
_READ_INTERVAL_SECONDS = 30.0
_MAX_DELTA_F = 20.0      # ignore readings that jump more than this between samples
_RETRY_LIMIT  = 3        # attempts per reading cycle before giving up


class TempSensorManager(QObject):
    """
    Polls DHT22 and DS18B20 sensors on a background thread and exposes
    the latest readings via properties and a Qt signal.

    Readings are in Fahrenheit to match the original application.

    Signals:
        readings_updated(ambient_f, humidity_pct, liquid_f)
            Emitted whenever a successful reading cycle completes.
            Any value may be None if that sensor failed.
    """

    readings_updated = pyqtSignal(object, object, object)  # (float|None) × 3

    def __init__(self, config: dict, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)

        hw = config.get("hardware", {})
        self._dht_pin_num     = hw.get("temp_sensor_dht_pin", 22)
        self._ds18b20_id      = hw.get("liquid_temp_sensor_id", "")
        self._power_pin       = hw.get("temp_sensor_power_pin", 17)
        self._interval        = _READ_INTERVAL_SECONDS

        # Latest readings (None until first successful read)
        self.ambient_f:  Optional[float] = None
        self.humidity:   Optional[float] = None
        self.liquid_f:   Optional[float] = None

        self._prev_ambient_f: Optional[float] = None
        self._prev_liquid_f:  Optional[float] = None

        self._dht_device = None
        self._running    = False
        self._thread:    Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Public control
    # ------------------------------------------------------------------

    def start(self, gpio_manager=None) -> None:
        """
        Begin polling. Pass the shared GPIOManager if the DHT22 power pin
        needs to be toggled during sensor resets.
        """
        self._gpio = gpio_manager
        self._init_dht()
        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop, name="temp-sensor", daemon=True
        )
        self._thread.start()
        log.info("TempSensorManager started (DHT22 pin %d, DS18B20 %s)",
                 self._dht_pin_num, self._ds18b20_id or "not configured")

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
            self._read_ds18b20()
            self.readings_updated.emit(self.ambient_f, self.humidity, self.liquid_f)
            time.sleep(self._interval)

    # ------------------------------------------------------------------
    # DHT22 (ambient temperature + humidity)
    # ------------------------------------------------------------------

    def _read_dht22(self) -> None:
        if self._dht_device is None:
            return

        for attempt in range(_RETRY_LIMIT):
            try:
                temp_c    = self._dht_device.temperature
                humidity  = self._dht_device.humidity

                if temp_c is None or humidity is None:
                    raise RuntimeError("Sensor returned None")

                temp_f = _c_to_f(temp_c)

                if self._prev_ambient_f is not None:
                    if abs(temp_f - self._prev_ambient_f) > _MAX_DELTA_F:
                        log.warning(
                            "DHT22: ignoring suspicious reading %.1f°F (prev %.1f°F)",
                            temp_f, self._prev_ambient_f,
                        )
                        return

                self.ambient_f        = temp_f
                self.humidity         = humidity
                self._prev_ambient_f  = temp_f
                log.debug("DHT22: %.1f°F, %.1f%%", temp_f, humidity)
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

    # ------------------------------------------------------------------
    # DS18B20 (liquid temperature via 1-Wire sysfs)
    # ------------------------------------------------------------------

    def _read_ds18b20(self) -> None:
        if not self._ds18b20_id:
            return

        sensor_path = _W1_BASE / self._ds18b20_id / "w1_slave"
        if not sensor_path.exists():
            log.warning("DS18B20: sysfs path not found: %s", sensor_path)
            return

        try:
            lines = sensor_path.read_text().splitlines()
            if len(lines) < 2 or "YES" not in lines[0]:
                log.warning("DS18B20: CRC check failed")
                return

            t_part = lines[1].split("t=")
            if len(t_part) < 2:
                log.warning("DS18B20: unexpected format: %s", lines[1])
                return

            temp_c = int(t_part[1]) / 1000.0
            temp_f = _c_to_f(temp_c)

            if self._prev_liquid_f is not None:
                if abs(temp_f - self._prev_liquid_f) > _MAX_DELTA_F:
                    log.warning(
                        "DS18B20: ignoring suspicious reading %.1f°F (prev %.1f°F)",
                        temp_f, self._prev_liquid_f,
                    )
                    return

            self.liquid_f        = temp_f
            self._prev_liquid_f  = temp_f
            log.debug("DS18B20: %.1f°F", temp_f)

        except Exception as exc:
            log.error("DS18B20 read failed: %s", exc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _c_to_f(celsius: float) -> float:
    return celsius * 9.0 / 5.0 + 32.0
