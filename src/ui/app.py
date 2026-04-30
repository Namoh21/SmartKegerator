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
  • 2 min of no touch and no pour                       → screen sleep
    The first touch after sleep wakes the screen (consumed, not passed on).
    Screen wakes automatically when a pour starts.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from PyQt6.QtCore import QEvent, QObject, Qt, QTimer
from PyQt6.QtWidgets import QApplication, QWidget

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

_SCREEN_SLEEP_MS  = 2 * 60 * 1000   # 2 minutes → screen sleep
_POST_POUR_MS     =      20 * 1000   # 20 seconds after pour → user logout
_IDLE_MS          =      30 * 1000   # 30 seconds of no touch → user logout




# ---------------------------------------------------------------------------
# Application coordinator
# ---------------------------------------------------------------------------

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
        self._is_admin:          bool           = False

        # 20 s after pour ends, log out (unless the user interacts first)
        self._post_pour_timer = QTimer()
        self._post_pour_timer.setSingleShot(True)
        self._post_pour_timer.timeout.connect(self._logout_user)

        # 30 s after the last touchscreen interaction, log out
        self._idle_timer = QTimer()
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._logout_user)

        # -----------------------------------------------------------------
        # Screen sleep timer (overlay created after main_window below)
        # -----------------------------------------------------------------
        self._screen_off = False

        self._screen_timer = QTimer()
        self._screen_timer.setSingleShot(True)
        self._screen_timer.timeout.connect(self._sleep_screen)

        # Catch all mouse / touch events across the whole application
        QApplication.instance().installEventFilter(self)

        # -----------------------------------------------------------------
        # Windows
        # -----------------------------------------------------------------
        self._main_window    = MainWindow(config, self._db, self._recognizer)
        self._pouring_window = PouringWindow(config, self._db)

        # Black overlay is a CHILD of main_window so it has no independent
        # Wayland surface and cannot steal input focus from other widgets.
        self._blank_overlay = QWidget(self._main_window)
        self._blank_overlay.setStyleSheet("background: black;")
        self._blank_overlay.hide()

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

        # Start sleep countdown after the window is visible
        self._screen_timer.start(_SCREEN_SLEEP_MS)

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

        # Temperature sensors → main window + alert check
        self._temp_sensor.readings_updated.connect(self._main_window.on_readings_updated)
        self._temp_sensor.readings_updated.connect(self._on_temp_readings)

        # Face recognizer → pouring window (shows who's pouring)
        self._recognizer.user_identified.connect(self._pouring_window.on_user_identified)
        self._recognizer.face_detected.connect(self._pouring_window.on_face_detected)

        # Face recognizer → App session (updates main window + timers)
        self._recognizer.user_identified.connect(self._on_user_identified)

        # Main window navigation
        self._main_window.settings_requested.connect(self._open_settings)

        # Web-initiated camera capture (DB polling IPC)
        self._capture_timer = QTimer(self)
        self._capture_timer.setInterval(2000)
        self._capture_timer.timeout.connect(self._check_web_capture_request)
        self._capture_timer.start()

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
    # Screen sleep / wake
    # ------------------------------------------------------------------

    def _sleep_screen(self) -> None:
        """Cover the main window with a black overlay after inactivity."""
        if self._screen_off:
            return
        self._screen_off = True
        # Resize overlay to fill the entire main window, then bring to front
        self._blank_overlay.resize(self._main_window.size())
        self._blank_overlay.raise_()
        self._blank_overlay.show()
        log.info("Screen sleeping after %d s idle", _SCREEN_SLEEP_MS // 1000)

    def _wake_screen(self) -> None:
        """Remove the black overlay."""
        if not self._screen_off:
            return
        self._screen_off = False
        self._blank_overlay.hide()
        self._reset_screen_timer()
        log.info("Screen woke")

    def _reset_screen_timer(self) -> None:
        """Restart the 2-minute sleep countdown."""
        self._screen_timer.start(_SCREEN_SLEEP_MS)

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def _on_user_identified(self, user_id: int, confidence: float) -> None:
        """Called whenever facial recognition matches someone."""
        self._reset_screen_timer()
        self._idle_timer.start(_IDLE_MS)

        if user_id == self._current_user_id:
            return  # same person — timers already reset above

        user = self._db.get_user(user_id)
        if not user:
            return

        self._current_user_id   = user.id
        self._current_user_name = user.name
        self._is_admin          = self._db.is_user_admin(user.id)
        self._post_pour_timer.stop()
        self._main_window.set_current_user(user.id, user.name, self._is_admin)
        log.info(
            "Session started: %s (id=%d, admin=%s, confidence=%.0f%%)",
            user.name, user.id, self._is_admin, confidence * 100,
        )

    def _on_interaction(self) -> None:
        """Touchscreen tap detected — keep session alive."""
        self._post_pour_timer.stop()
        self._idle_timer.start(_IDLE_MS)

    def _logout_user(self) -> None:
        """Clear the current session (called by either user-session timer)."""
        if self._current_user_id is not None:
            log.info(
                "Session timed out — logging out %s (id=%d)",
                self._current_user_name, self._current_user_id,
            )
        self._current_user_id   = None
        self._current_user_name = ""
        self._is_admin          = False
        self._post_pour_timer.stop()
        self._idle_timer.stop()
        self._main_window.set_current_user(None, "", is_admin=False)

    # ------------------------------------------------------------------
    # Qt event filter — catches all touch / mouse events
    # ------------------------------------------------------------------

    def eventFilter(self, obj, event) -> bool:
        if event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.TouchBegin):
            if self._screen_off:
                # First touch wakes the screen; don't pass the event to widgets
                self._wake_screen()
                return True
            else:
                self._reset_screen_timer()
                if self._current_user_id is not None:
                    self._on_interaction()
        return False

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

        # Wake screen (in case it was sleeping) and pause the sleep timer
        # during the pour so the display stays on throughout
        self._wake_screen()
        self._screen_timer.stop()

        # Log out and clear session — face recognition re-identifies the pourer
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

        # Resume sleep countdown; also start the 20 s user-logout timer
        self._reset_screen_timer()
        self._post_pour_timer.start(_POST_POUR_MS)

        self._pouring_window.end_pour()
        self._pouring_window.hide()
        self._main_window.show()
        self._main_window.refresh()

    # ------------------------------------------------------------------
    # Sensor data — stored to DB so the REST API can serve it
    # ------------------------------------------------------------------

    def _on_temp_readings(self, ambient_f, humidity_pct) -> None:
        try:
            if ambient_f is not None:
                self._db.set_setting("latest_ambient_temp_f", f"{ambient_f:.1f}")
            if humidity_pct is not None:
                self._db.set_setting("latest_humidity_pct",   f"{humidity_pct:.1f}")
            self._db.set_setting("latest_temp_ts", f"{time.time():.0f}")
        except Exception as exc:
            log.debug("Temp DB store error: %s", exc)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _open_history(self) -> None:
        if self._current_user_id is None:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(
                self._main_window, "Identify Yourself",
                "Please stand in front of the camera to be identified,\n"
                "then tap History to view your pour history.",
            )
            return
        from ui.history_window import HistoryWindow
        w = HistoryWindow(
            self._config, self._db, self._main_window,
            current_user_id=self._current_user_id,
            is_admin=self._is_admin,
        )
        if self._fullscreen:
            w.showFullScreen()
        w.exec()

    def _check_web_capture_request(self) -> None:
        """Poll DB for a photo capture request from the web UI."""
        request = self._db.get_setting("capture_request", "")
        if not request:
            return
        self._db.set_setting("capture_request", "")  # consume immediately

        try:
            user_id_str, req_id = request.split(":", 1)
            user_id = int(user_id_str)
        except ValueError:
            return

        from pathlib import Path as _Path
        photos_dir = _Path(self._config["data"]["user_photos_dir"]) / str(user_id)
        photos_dir.mkdir(parents=True, exist_ok=True)
        existing = len(list(photos_dir.glob("*.jpg")))
        dest     = str(photos_dir / f"pic{existing}.jpg")

        self._main_window.show_capture_banner()

        if not self._camera.is_running:
            self._db.set_setting("capture_result", f"{req_id}:ERROR:Camera is not running — check the camera connection and config.")
            log.warning("Web capture: camera not running for user %d", user_id)
        elif self._camera.latest_frame is None:
            self._db.set_setting("capture_result", f"{req_id}:ERROR:Camera opened but has not captured a frame yet — try again in a moment.")
            log.warning("Web capture: no frame available yet for user %d", user_id)
        elif self._camera.capture_photo(dest):
            self._db.add_user_image(user_id, dest)
            self._db.set_setting("capture_result", f"{req_id}:{dest}")
            log.info("Web capture: saved %s for user %d", dest, user_id)
        else:
            self._db.set_setting("capture_result", f"{req_id}:ERROR:Camera returned a frame but could not write the file — check disk space and photos directory permissions.")
            log.warning("Web capture: imwrite failed for user %d at %s", user_id, dest)

    def _open_settings(self) -> None:
        if not self._is_admin:
            # Prompt for PIN login before opening settings
            from PyQt6.QtWidgets import QDialog
            from ui.pin_login_dialog import PinLoginDialog
            dlg = PinLoginDialog(self._config, self._db, self._main_window)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            user_id = dlg.authenticated_user_id()
            if user_id is None:
                return
            # Establish admin session without a confidence score
            user = self._db.get_user(user_id)
            if not user:
                return
            self._current_user_id   = user.id
            self._current_user_name = user.name
            self._is_admin          = True
            self._idle_timer.start(_IDLE_MS)
            self._main_window.set_current_user(user.id, user.name, is_admin=True)
            log.info("Admin session via PIN: %s (id=%d)", user.name, user.id)

        from ui.settings_window import SettingsWindow
        w = SettingsWindow(self._config, self._db, self._main_window)
        w.users_requested.connect(self._open_users)
        if self._fullscreen:
            w.showFullScreen()
        w.exec()

    def _open_users(self) -> None:
        from ui.users_window import UsersWindow
        w = UsersWindow(
            self._config, self._db, self._recognizer, self._camera,
            self._main_window,
            is_admin=self._is_admin,
        )
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
