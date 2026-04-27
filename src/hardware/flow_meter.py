"""
Flow meter manager — detects beer pours on 1–4 taps via GPIO edge events.

Tap count and GPIO pins are read from the config `taps` section.

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


class _PourState(Enum):
    IDLE    = auto()
    POURING = auto()


class FlowMeterManager(QObject):
    """
    Monitors 1–4 flow meter GPIO pins and manages pour lifecycle.

    Tap names (tap1–tap4) and pins come from config['taps'].

    Signals:
        pour_started(tap: str)              — a pour has begun on the named tap
        flow_tick(tap: str, ticks: int)     — tick count updated during a pour
        pour_finished(tap: str, ticks: int) — pour complete; ticks is total count
    """

    pour_started  = pyqtSignal(str)
    flow_tick     = pyqtSignal(str, int)
    pour_finished = pyqtSignal(str, int)

    def __init__(self, config: dict, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)

        hw       = config.get("hardware", {})
        taps_cfg = config.get("taps", {})
        count    = min(int(taps_cfg.get("count", 3)), 4)

        # Build pin → tap_id mapping from config
        self._pins: dict[int, str] = {}
        for i in range(count):
            tap_id   = f"tap{i + 1}"
            tap_info = taps_cfg.get(tap_id, {})
            pin      = tap_info.get("pin") if isinstance(tap_info, dict) else None
            if pin is not None:
                try:
                    self._pins[int(pin)] = tap_id
                except (TypeError, ValueError):
                    log.warning("Invalid pin for %s: %s", tap_id, pin)

        self._tap_ids         = list(self._pins.values())
        self._tick_threshold  = hw.get("tick_threshold",    3)
        self._end_pour_secs   = hw.get("end_pour_seconds", 5.0)
        self._chip_path       = hw.get("gpio_chip",        _CHIP)

        # Per-tap state
        self._ticks:     dict[str, int]        = {t: 0              for t in self._tap_ids}
        self._state:     dict[str, _PourState] = {t: _PourState.IDLE for t in self._tap_ids}
        self._last_tick: dict[str, float]      = {t: 0.0            for t in self._tap_ids}

        self._running = False
        self._thread:          Optional[threading.Thread] = None
        self._watchdog_thread: Optional[threading.Thread] = None

        log.info(
            "FlowMeterManager configured: %d tap(s) on pins %s",
            count, list(self._pins.keys()),
        )

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

    def simulate_tick(self, tap_id: str) -> None:
        """Inject a synthetic tick — useful for testing without hardware."""
        if tap_id in self._ticks:
            self._handle_tick(tap_id)

    # ------------------------------------------------------------------
    # GPIO event loop (background thread)
    # ------------------------------------------------------------------

    def _event_loop(self) -> None:
        if not _GPIOD_AVAILABLE or not self._pins:
            log.warning("Flow meter event loop skipped — gpiod unavailable or no pins configured")
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
                            tap_id = self._pins.get(event.line_offset)
                            if tap_id is not None:
                                self._handle_tick(tap_id)
        except Exception as exc:
            log.error("Flow meter event loop crashed: %s", exc)

    # ------------------------------------------------------------------
    # Watchdog loop (background thread)
    # ------------------------------------------------------------------

    def _watchdog_loop(self) -> None:
        while self._running:
            now = time.monotonic()
            for tap_id in self._tap_ids:
                if self._state[tap_id] is _PourState.POURING:
                    if now - self._last_tick[tap_id] >= self._end_pour_secs:
                        self._finish_pour(tap_id)
            time.sleep(0.25)

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------

    def _handle_tick(self, tap_id: str) -> None:
        self._ticks[tap_id]     += 1
        self._last_tick[tap_id]  = time.monotonic()

        if self._state[tap_id] is _PourState.IDLE:
            if self._ticks[tap_id] >= self._tick_threshold:
                self._state[tap_id] = _PourState.POURING
                log.info("Pour started on %s", tap_id)
                self.pour_started.emit(tap_id)
        else:
            self.flow_tick.emit(tap_id, self._ticks[tap_id])

    def _finish_pour(self, tap_id: str) -> None:
        total_ticks = self._ticks[tap_id]
        self._state[tap_id] = _PourState.IDLE
        self._ticks[tap_id] = 0
        log.info("Pour finished on %s: %d ticks", tap_id, total_ticks)
        self.pour_finished.emit(tap_id, total_ticks)
