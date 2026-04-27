"""
Application coordinator.

Creates every subsystem in the right order, wires all Qt signals together,
and manages the pour lifecycle (pour started → pouring window → save to DB
→ back to main window).
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from PyQt6.QtCore import QObject, Qt
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

        # Face recognizer → pouring window
        self._recognizer.user_identified.connect(self._pouring_window.on_user_identified)
        self._recognizer.face_detected.connect(self._pouring_window.on_face_detected)

        # Main window navigation (windows opened in Phase 5)
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

        # Detect Pi 7" touchscreen: 800×480 (0°/180°) or 480×800 (90°/270°)
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

        self._pouring_window.end_pour()
        self._pouring_window.hide()
        self._main_window.show()
        self._main_window.refresh()

    # ------------------------------------------------------------------
    # Navigation (Phase 5 windows — stubs until then)
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
