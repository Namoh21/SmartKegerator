"""
Flow meter manager — detects beer pours on up to 3 taps via GPIO edge events.

Replaces the original approach of spawning gpioWFI.py as a subprocess and
parsing its stdout. Now uses gpiod 2.x directly inside a background thread,
which is both faster and more reliable.

Pour state machine per tap:
    IDLE  →  (tick_threshold ticks received)  →  POURING
    POURING  →  (end_pour_seconds with no ticks)  →  IDLE  [emit pour_finished]

PyQt6 signals are used so the UI can connect to events from the main thread.
Signals emitted from a background thread are automatically queued by Qt.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import timedelta
from enum import Enum, auto
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

log = logging.getLogger(__name__)

try:
    import gpiod
    from gpiod.line import Direction, Edge
    _GPIOD_AVAILABLE = True
except ImportError:
    _GPIOD_AVAILABLE = False
    log.warning("gpiod not available — flow meter will not detect pours (dev/non-Pi mode)")

_CHIP = "/dev/gpiochip0"


class Tap(str, Enum):
    LEFT   = "left"
    CENTER = "center"
    RIGHT  = "right"


class _PourState(Enum):
    IDLE    = auto()
    POURING = auto()


class FlowMeterManager(QObject):
    """
    Monitors 3 flow meter GPIO pins and manages pour lifecycle.

    Signals:
        pour_started(tap: str)          — a pour has begun on the named tap
        flow_tick(tap: str, ticks: int) — tick count updated during a pour
        pour_finished(tap: str, ticks: int) — pour is complete; ticks is total
    """

    pour_started  = pyqtSignal(str)
    flow_tick     = pyqtSignal(str, int)
    pour_finished = pyqtSignal(str, int)

    def __init__(self, config: dict, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)

        hw = config.get("hardware", {})
        self._pins: dict[int, Tap] = {
            hw.get("flow_meter_pin_left",   23): Tap.LEFT,
            hw.get("flow_meter_pin_center", 24): Tap.CENTER,
            hw.get("flow_meter_pin_right",  25): Tap.RIGHT,
        }
        self._tick_threshold  = hw.get("tick_threshold",    3)
        self._end_pour_secs   = hw.get("end_pour_seconds", 5.0)
        self._chip_path       = hw.get("gpio_chip",        _CHIP)

        # Per-tap state
        self._ticks:      dict[Tap, int]         = {t: 0     for t in Tap}
        self._state:      dict[Tap, _PourState]  = {t: _PourState.IDLE for t in Tap}
        self._last_tick:  dict[Tap, float]       = {t: 0.0   for t in Tap}

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._watchdog_thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Public control
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._event_loop, name="flow-meter", daemon=True
        )
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop, name="flow-watchdog", daemon=True
        )
        self._thread.start()
        self._watchdog_thread.start()
        log.info("FlowMeterManager started on pins %s", list(self._pins.keys()))

    def stop(self) -> None:
        self._running = False
        log.info("FlowMeterManager stopped")

    def simulate_tick(self, tap: Tap) -> None:
        """Inject a synthetic tick — useful for testing without hardware."""
        self._handle_tick(tap)

    # ------------------------------------------------------------------
    # GPIO event loop (background thread)
    # ------------------------------------------------------------------

    def _event_loop(self) -> None:
        if not _GPIOD_AVAILABLE:
            log.warning("Flow meter event loop skipped — gpiod unavailable")
            return

        pin_config = {
            pin: gpiod.LineSettings(
                direction=Direction.INPUT,
                edge_detection=Edge.RISING,
                debounce_period=timedelta(milliseconds=5),
            )
            for pin in self._pins
        }

        try:
            with gpiod.request_lines(
                self._chip_path,
                consumer="smartkegerator-flow",
                config=pin_config,
            ) as request:
                while self._running:
                    if request.wait_edge_events(timedelta(seconds=0.5)):
                        for event in request.read_edge_events():
                            tap = self._pins.get(event.line_offset)
                            if tap is not None:
                                self._handle_tick(tap)
        except Exception as exc:
            log.error("Flow meter event loop crashed: %s", exc)

    # ------------------------------------------------------------------
    # Watchdog loop — fires pour_finished when ticks go quiet (background thread)
    # ------------------------------------------------------------------

    def _watchdog_loop(self) -> None:
        while self._running:
            now = time.monotonic()
            for tap in Tap:
                if self._state[tap] is _PourState.POURING:
                    idle_secs = now - self._last_tick[tap]
                    if idle_secs >= self._end_pour_secs:
                        self._finish_pour(tap)
            time.sleep(0.25)

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------

    def _handle_tick(self, tap: Tap) -> None:
        self._ticks[tap]     += 1
        self._last_tick[tap]  = time.monotonic()

        if self._state[tap] is _PourState.IDLE:
            if self._ticks[tap] >= self._tick_threshold:
                self._state[tap] = _PourState.POURING
                log.info("Pour started on %s tap", tap.value)
                self.pour_started.emit(tap.value)
        else:
            self.flow_tick.emit(tap.value, self._ticks[tap])

    def _finish_pour(self, tap: Tap) -> None:
        total_ticks = self._ticks[tap]
        self._state[tap] = _PourState.IDLE
        self._ticks[tap] = 0
        log.info("Pour finished on %s tap: %d ticks", tap.value, total_ticks)
        self.pour_finished.emit(tap.value, total_ticks)
