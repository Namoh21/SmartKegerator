"""
GPIO output pin control using the modern gpiod 2.x chardev API.

Replaces the original approach of shelling out to the `gpio` CLI tool.
Keeps a single LineRequest open for all managed output pins so we never
have to re-request them on every write call.
"""

from __future__ import annotations

import logging
from typing import Iterable

log = logging.getLogger(__name__)

try:
    import gpiod
    from gpiod.line import Direction, Value
    _GPIOD_AVAILABLE = True
except ImportError:
    _GPIOD_AVAILABLE = False
    log.warning("gpiod not available — GPIO calls will be no-ops (dev/non-Pi mode)")

_CHIP = "/dev/gpiochip0"


class GPIOManager:
    """
    Manages a fixed set of output GPIO pins for the lifetime of the app.

    Usage:
        gpio = GPIOManager(pins=[17, 18], config=cfg)
        gpio.write(18, True)   # camera LEDs on
        gpio.write(17, False)  # temp sensor power off
        gpio.close()
    """

    def __init__(self, pins: Iterable[int], config: dict) -> None:
        self._pins = list(pins)
        self._request = None

        if not _GPIOD_AVAILABLE or not self._pins:
            return

        chip_path = config.get("hardware", {}).get("gpio_chip", _CHIP)
        pin_config = {
            pin: gpiod.LineSettings(
                direction=Direction.OUTPUT,
                output_value=Value.INACTIVE,
            )
            for pin in self._pins
        }
        try:
            self._request = gpiod.request_lines(
                chip_path,
                consumer="smartkegerator-gpio",
                config=pin_config,
            )
            log.info("GPIOManager: claimed output pins %s", self._pins)
        except Exception as exc:
            log.error("GPIOManager: failed to claim pins %s: %s", self._pins, exc)

    def write(self, pin: int, on: bool) -> None:
        """Drive *pin* high (on=True) or low (on=False)."""
        if self._request is None:
            log.debug("GPIO stub write: pin %d = %s", pin, on)
            return
        try:
            self._request.set_value(pin, Value.ACTIVE if on else Value.INACTIVE)
        except Exception as exc:
            log.error("GPIO write failed on pin %d: %s", pin, exc)

    def pulse(self, pin: int, duration_ms: int = 100) -> None:
        """Drive pin high, sleep, drive low — useful for resets."""
        import time
        self.write(pin, True)
        time.sleep(duration_ms / 1000.0)
        self.write(pin, False)

    def close(self) -> None:
        if self._request is not None:
            self._request.release()
            self._request = None
            log.info("GPIOManager: released pins")
