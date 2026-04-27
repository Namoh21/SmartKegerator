"""
Application coordinator.

Creates every subsystem in the right order, wires all Qt signals together,
and manages the pour lifecycle (pour started → pouring window → save to DB
→ back to main window).

Session model
-------------
The "current user" is whoever facial recognition last identified.
It is tracked only on the touchscreen — the web interface has no
standard-user login.

Timeout rules:
  • 20 s after a pour ends with no further interaction  → logout
  • 30 s after the last touchscreen touch                → logout
  • A new pour always resets (logs out) the session so face recognition
    identifies the person at the tap fresh every time.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from PyQt6.QtCore import QEvent, QObject, Qt, QTimer
from PyQt6.QtWidgets import QApplication

from data.database import Database
from data.models import Pour, UNKNOWN_USER_ID
from hardware.camera import Camera
from hardware.flow_meter import FlowMeterManager
from hardware.gpio_manager import GPIOManager
from hardware.temp_sensor import TempSensorManager
from recognition.face_recognizer import FaceRecognizer
from ui.main_window import MainWindow
from ui.pouring_window import PouringWindow

log = logging.getLogger(__name__)


class App(QObject):
    def __init__(self, config: dict) -> None:
        super().__init__()
        self._config = config

        # -----------------------------------------------------------------
        # Data layer
        # -----------------------------------------------------------------
        self._db = Database(config["data"]["database_path"])

        # -----------------------------------------------------------------
        # Hardware
        # -----------------------------------------------------------------
        hw = config["hardware"]
        self._gpio = GPIOManager(
            pins=[hw.get("camera_leds_pin", 18), hw.get("temp_sensor_power_pin", 17)],
            config=config,
        )
        self._camera      = Camera(config)
        self._flow_meter  = FlowMeterManager(config)
        self._temp_sensor = TempSensorManager(config)

        # -----------------------------------------------------------------
        # Facial recognition
        # -----------------------------------------------------------------
        self._recognizer = FaceRecognizer(config, self._db)

        # -----------------------------------------------------------------
        # Touchscreen session state
        # -----------------------------------------------------------------
        self._current_user_id:   Optional[int] = None
        self._current_user_name: str            = ""

        # 20 s after pour ends, log out (unless the user interacts first)
        self._post_pour_timer = QTimer()
        self._post_pour_timer.setSingleShot(True)
        self._post_pour_timer.timeout.connect(self._logout_user)

        # 30 s after the last touchscreen interaction, log out
        self._idle_timer = QTimer()
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._logout_user)

        # Catch all mouse / touch events across the whole application
        QApplication.instance().installEventFilter(self)

        # -----------------------------------------------------------------
        # Windows
        # -----------------------------------------------------------------
        self._main_window    = MainWindow(config, self._db, self._recognizer)
        self._pouring_window = PouringWindow(config, self._db)

        # Set before _start_hardware() in case a pour fires during startup
        self._fullscreen: bool = False

        # -----------------------------------------------------------------
        # Wire signals
        # -----------------------------------------------------------------
        self._wire_signals()

        # -----------------------------------------------------------------
        # Start hardware, then show the UI
        # -----------------------------------------------------------------
        self._start_hardware()
        self._apply_display_settings()
        self._main_window.show()

    # ------------------------------------------------------------------
    # Signal wiring
    # ------------------------------------------------------------------

    def _wire_signals(self) -> None:
        # Flow meter → pour lifecycle
        self._flow_meter.pour_started.connect(self._on_pour_started)
        self._flow_meter.pour_finished.connect(self._on_pour_finished)
        self._flow_meter.flow_tick.connect(self._pouring_window.on_tick)

        # Camera → live display and face recognizer
        self._camera.frame_ready.connect(self._pouring_window.on_frame)
        self._camera.raw_frame_ready.connect(self._recognizer.submit_frame)

        # Temperature sensors → main window
        self._temp_sensor.readings_updated.connect(self._main_window.on_readings_updated)

        # Face recognizer → pouring window (shows who's pouring)
        self._recognizer.user_identified.connect(self._pouring_window.on_user_identified)
        self._recognizer.face_detected.connect(self._pouring_window.on_face_detected)

        # Face recognizer → App session (updates main window + timers)
        self._recognizer.user_identified.connect(self._on_user_identified)

        # Main window navigation
        self._main_window.history_requested.connect(self._open_history)
        self._main_window.settings_requested.connect(self._open_settings)
        self._main_window.users_requested.connect(self._open_users)

    # ------------------------------------------------------------------
    # Hardware startup
    # ------------------------------------------------------------------

    def _start_hardware(self) -> None:
        if not self._camera.start():
            log.warning("Camera failed to open — live feed will be unavailable")
        self._temp_sensor.start(gpio_manager=self._gpio)
        self._flow_meter.start()
        self._recognizer.start()

    # ------------------------------------------------------------------
    # Display configuration (fullscreen on Pi touchscreen)
    # ------------------------------------------------------------------

    def _apply_display_settings(self) -> None:
        ui  = self._config.get("ui", {})
        app = QApplication.instance()
        geo = app.primaryScreen().availableGeometry()

        is_touchscreen = (
            (geo.width() == 800 and geo.height() <= 480) or
            (geo.width() <= 480 and geo.height() == 800)
        )
        self._fullscreen = ui.get("fullscreen", False) or is_touchscreen
        if self._fullscreen:
            app.setOverrideCursor(Qt.CursorShape.BlankCursor)
            self._main_window.showFullScreen()
        else:
            self._main_window.move(ui.get("window_x", 100), ui.get("window_y", 100))
            self._main_window.resize(900, 520)

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def _on_user_identified(self, user_id: int, confidence: float) -> None:
        """Called whenever facial recognition matches someone.

        Updates the main-window greeting and resets/starts the idle timer.
        Only fires if the recognised user is different from the current one
        (avoids redundant DB hits and label flicker when recognition is steady).
        """
        # Always reset idle timer — recognition counts as "activity"
        self._idle_timer.start(30_000)

        if user_id == self._current_user_id:
            return  # same person still recognised — timers already reset above

        user = self._db.get_user(user_id)
        if not user:
            return

        self._current_user_id   = user.id
        self._current_user_name = user.name
        self._post_pour_timer.stop()          # new person takes over immediately
        self._main_window.set_current_user(user.id, user.name)
        log.info(
            "Session started: %s (id=%d, confidence=%.0f%%)",
            user.name, user.id, confidence * 100,
        )

    def _on_interaction(self) -> None:
        """Touchscreen tap detected — keep session alive."""
        self._post_pour_timer.stop()
        self._idle_timer.start(30_000)

    def _logout_user(self) -> None:
        """Clear the current session (called by either timer)."""
        if self._current_user_id is not None:
            log.info(
                "Session timed out — logging out %s (id=%d)",
                self._current_user_name, self._current_user_id,
            )
        self._current_user_id   = None
        self._current_user_name = ""
        self._post_pour_timer.stop()
        self._idle_timer.stop()
        self._main_window.set_current_user(None, "")

    # ------------------------------------------------------------------
    # Qt event filter — catches all touch / mouse events
    # ------------------------------------------------------------------

    def eventFilter(self, obj, event) -> bool:
        if self._current_user_id is not None:
            if event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.TouchBegin):
                self._on_interaction()
        return False  # never consume events

    # ------------------------------------------------------------------
    # Pour lifecycle
    # ------------------------------------------------------------------

    def _on_pour_started(self, tap: str) -> None:
        taps   = self._db.get_tap_assignments()
        keg_id = taps.get_keg_id(tap)

        if keg_id is None:
            log.warning("Pour started on %s tap but no keg is assigned — ignoring", tap)
            return

        keg  = self._db.get_keg(keg_id)
        beer = self._db.get_beer(keg.beer_id) if keg else None

        log.info("Pour started: tap=%s keg=%s beer=%s", tap, keg_id, beer.name if beer else "?")

        # Log out and clear session — face recognition will re-identify the pourer
        self._logout_user()

        self._pouring_window.start_pour(tap, keg, beer)

        hw = self._config["hardware"]
        self._gpio.write(hw.get("camera_leds_pin", 18), True)

        if self._fullscreen:
            self._pouring_window.showFullScreen()
        else:
            self._pouring_window.resize(self._main_window.size())
            self._pouring_window.move(self._main_window.pos())
            self._pouring_window.show()

        self._main_window.hide()

    def _on_pour_finished(self, tap: str, ticks: int) -> None:
        hw = self._config["hardware"]
        self._gpio.write(hw.get("camera_leds_pin", 18), False)

        keg     = self._pouring_window.current_keg
        user_id = self._pouring_window.current_user_id

        if keg is not None and ticks > 0:
            ticks_per_liter = hw.get("ticks_per_liter", 500)
            liters  = ticks / ticks_per_liter
            ounces  = liters * 33.814
            price   = keg.price_for_ounces(ounces)

            pour = Pour(
                id=None,
                time=time.time(),
                keg_id=keg.id,
                user_id=user_id if user_id is not None else UNKNOWN_USER_ID,
                ticks=ticks,
                ounces=ounces,
                price=price,
            )
            self._db.add_pour(pour)
            log.info(
                "Pour saved: tap=%s ticks=%d %.1f oz $%.2f user=%s",
                tap, ticks, ounces, price, user_id,
            )
        else:
            log.info("Pour finished with no ticks or no keg — nothing saved")

        # Start 20 s post-pour logout countdown
        self._post_pour_timer.start(20_000)

        self._pouring_window.end_pour()
        self._pouring_window.hide()
        self._main_window.show()
        self._main_window.refresh()

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _open_history(self) -> None:
        from ui.history_window import HistoryWindow
        w = HistoryWindow(self._config, self._db, self._main_window)
        if self._fullscreen:
            w.showFullScreen()
        w.exec()

    def _open_settings(self) -> None:
        from ui.settings_window import SettingsWindow
        w = SettingsWindow(self._config, self._db, self._main_window)
        if self._fullscreen:
            w.showFullScreen()
        w.exec()

    def _open_users(self) -> None:
        from ui.users_window import UsersWindow
        w = UsersWindow(self._config, self._db, self._recognizer, self._camera, self._main_window)
        if self._fullscreen:
            w.showFullScreen()
        w.exec()

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        log.info("Shutting down SmartKegerator")
        self._flow_meter.stop()
        self._temp_sensor.stop()
        self._recognizer.stop()
        self._camera.stop()
        self._gpio.close()
