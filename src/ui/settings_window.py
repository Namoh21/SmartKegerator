"""
Settings window — editable form for key config values.

Changes are applied to the in-memory config dict immediately for
runtime-safe settings (password, thresholds, UI toggles).  All changes
are also written back to config.yaml so they survive a restart.

Settings that change hardware pin assignments or file paths only take
effect after a restart — those fields are marked accordingly.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any, Optional

import yaml
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from ui.theme import get as _get_theme, THEMES
from log_config import apply_level, LEVEL_LABELS

log = logging.getLogger(__name__)


def _build_style(c: dict) -> str:
    return f"""
    QDialog, QWidget, QScrollArea, QGroupBox {{
        background-color: {c['bg']};
        color: {c['text']};
        font-family: 'DejaVu Sans', Arial, sans-serif;
    }}
    QGroupBox {{
        border: 1px solid {c['border']};
        border-radius: 6px;
        margin-top: 10px;
        padding-top: 6px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        color: {c['muted']};
        font-size: 13px;
        letter-spacing: 1px;
    }}
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
        background-color: {c['card']};
        color: {c['text']};
        border: 1px solid {c['border']};
        border-radius: 4px;
        padding: 4px 8px;
        min-width: 180px;
    }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
        border-color: {c['accent']};
    }}
    QCheckBox {{
        color: {c['text']};
    }}
    QPushButton {{
        background-color: {c['card']};
        color: {c['text']};
        border: 1px solid {c['accent']};
        border-radius: 4px;
        padding: 7px 18px;
    }}
    QPushButton#save {{
        background-color: {c['accent']};
        color: white;
        border: none;
    }}
    QPushButton:pressed {{ background-color: {c['accent']}; }}
"""


class SettingsWindow(QDialog):
    users_requested = pyqtSignal()

    def __init__(self, config: dict, db, parent=None) -> None:
        super().__init__(parent)
        self._config      = config
        self._db          = db
        self._config_path = _find_config_path()
        self._widgets: dict[tuple[str, str], QWidget] = {}
        self._c           = _get_theme(config)

        self.setWindowTitle("Settings")
        self.setStyleSheet(_build_style(self._c))
        self.setMinimumSize(540, 580)
        self.resize(560, 640)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        root.addWidget(self._build_header())
        root.addWidget(self._build_scroll_area(), stretch=1)
        root.addWidget(self._build_footer())

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build_header(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(44)
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)

        title = QLabel("Settings")
        f = QFont()
        f.setPointSize(16)
        f.setWeight(QFont.Weight.Bold)
        title.setFont(f)
        title.setStyleSheet(f"color: {self._c['accent']};")
        row.addWidget(title)

        row.addStretch()
        return bar

    def _build_scroll_area(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(scroll.Shape.NoFrame)

        container = QWidget()
        layout    = QVBoxLayout(container)
        layout.setSpacing(14)
        layout.setContentsMargins(4, 4, 4, 4)

        layout.addWidget(self._build_appearance_group())

        layout.addWidget(self._build_group(
            "TAPS",
            [
                ("taps",     "count",           "Active taps",              "spin",   (1, 4)),
                ("hardware", "ticks_per_liter",  "Ticks per liter",         "spin",   (1, 9999)),
                ("hardware", "end_pour_seconds", "End pour after (seconds)", "dspin",  (1.0, 60.0)),
                ("hardware", "tick_threshold",   "Tick threshold",           "spin",   (1, 20)),
                ("ui",       "log_pours",         "Log pours to database",   "check",  None),
            ],
        ))

        layout.addWidget(self._build_group(
            "FACIAL RECOGNITION",
            [
                ("recognition", "enabled",               "Enable recognition",   "check",  None),
                ("recognition", "confidence_threshold",  "Confidence threshold", "dspin",  (0.1, 1.0)),
                ("recognition", "detection_model",       "Model  (hog / cnn)",   "line",   None),
            ],
        ))

        layout.addWidget(self._build_group(
            "CAMERA  (restart required)",
            [
                ("hardware", "camera_index",         "Camera device index",   "spin",  (0, 10)),
                ("hardware", "camera_width",          "Capture width",         "spin",  (160, 1920)),
                ("hardware", "camera_height",         "Capture height",        "spin",  (120, 1080)),
                ("hardware", "camera_use_color",      "Color mode",            "check", None),
                ("hardware", "camera_swap_red_blue",  "Swap red/blue channels","check", None),
                ("hardware", "camera_mirror",         "Mirror image",          "check", None),
            ],
        ))

        layout.addWidget(self._build_group(
            "GPIO PINS  (restart required)",
            [
                ("hardware", "camera_leds_pin",       "Camera LEDs pin",        "spin", (0, 40)),
                ("hardware", "temp_sensor_power_pin", "Temp sensor power pin",   "spin", (0, 40)),
                ("hardware", "temp_sensor_dht_pin",   "DHT22 pin",               "spin", (0, 40)),
                ("hardware", "flow_meter_pin_left",   "Flow meter pin — left",   "spin", (0, 40)),
                ("hardware", "flow_meter_pin_center", "Flow meter pin — center", "spin", (0, 40)),
                ("hardware", "flow_meter_pin_right",  "Flow meter pin — right",  "spin", (0, 40)),
            ],
        ))

        layout.addWidget(self._build_group(
            "ADMIN",
            [
                ("admin", "password",   "Admin password", "password", None),
                ("ui",    "fullscreen", "Fullscreen mode", "check",   None),
            ],
        ))

        layout.addWidget(self._build_service_group())

        layout.addStretch()
        scroll.setWidget(container)
        return scroll

    def _build_appearance_group(self) -> QGroupBox:
        group = QGroupBox("APPEARANCE  (restart required)")
        form  = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(8)
        form.setContentsMargins(12, 16, 12, 12)

        # Kegerator name
        self._w_name = QLineEdit(
            self._config.get("ui", {}).get("name", "SmartKegerator")
        )
        form.addRow("Kegerator name:", self._w_name)

        # Color theme
        self._w_theme = QComboBox()
        current_theme = self._config.get("ui", {}).get("theme", "dark_blue")
        for key, meta in THEMES.items():
            self._w_theme.addItem(meta["label"], userData=key)
            if key == current_theme:
                self._w_theme.setCurrentIndex(self._w_theme.count() - 1)
        form.addRow("Color theme:", self._w_theme)

        # Display rotation
        self._w_rotation = QComboBox()
        current_rotation = self._config.get("display", {}).get("rotation", 90)
        for deg in (0, 90, 180, 270):
            self._w_rotation.addItem(f"{deg}°", userData=deg)
            if deg == current_rotation:
                self._w_rotation.setCurrentIndex(self._w_rotation.count() - 1)
        form.addRow("Display rotation:", self._w_rotation)

        return group

    def _build_service_group(self) -> QGroupBox:
        group = QGroupBox("SERVICE")
        form  = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(8)
        form.setContentsMargins(12, 16, 12, 12)

        self._w_log_level = QComboBox()
        current_level = self._db.get_setting("log_level", "high") if self._db else "high"
        for key, label in LEVEL_LABELS.items():
            self._w_log_level.addItem(label, userData=key)
            if key == current_level:
                self._w_log_level.setCurrentIndex(self._w_log_level.count() - 1)
        form.addRow("Log level:", self._w_log_level)

        return group

    def _build_group(self, title: str, fields: list) -> QGroupBox:
        group  = QGroupBox(title)
        form   = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(8)
        form.setContentsMargins(12, 16, 12, 12)

        for section, key, label, kind, opts in fields:
            value   = self._config.get(section, {}).get(key)
            widget  = self._make_widget(kind, value, opts)
            self._widgets[(section, key)] = widget
            form.addRow(label + ":", widget)

        return group

    def _build_footer(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(50)
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        users_btn = QPushButton("Manage Users")
        users_btn.clicked.connect(self._open_users)
        row.addWidget(users_btn)

        shutdown_btn = QPushButton("Shutdown Service")
        shutdown_btn.setObjectName("danger")
        shutdown_btn.setStyleSheet(
            f"border-color: {self._c['warn']}; color: {self._c['warn']};"
        )
        shutdown_btn.clicked.connect(self._shutdown_service)
        row.addWidget(shutdown_btn)

        restart_btn = QPushButton("Restart Services")
        restart_btn.setStyleSheet(
            f"border-color: {self._c['warn']}; color: {self._c['warn']};"
        )
        restart_btn.clicked.connect(self._restart_services)
        row.addWidget(restart_btn)

        reboot_btn = QPushButton("Reboot")
        reboot_btn.setStyleSheet(
            f"border-color: {self._c['warn']}; color: {self._c['warn']};"
        )
        reboot_btn.clicked.connect(self._reboot_system)
        row.addWidget(reboot_btn)

        if self._config_path:
            path_lbl = QLabel(f"Config: {self._config_path}")
            path_lbl.setStyleSheet(f"color: {self._c['muted']}; font-size: 11px;")
            row.addWidget(path_lbl)
        row.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        row.addWidget(cancel_btn)

        save_btn = QPushButton("Save")
        save_btn.setObjectName("save")
        save_btn.clicked.connect(self._save)
        row.addWidget(save_btn)

        return bar

    def _open_users(self) -> None:
        self.accept()   # close settings first, then App opens users via signal
        self.users_requested.emit()

    def _restart_services(self) -> None:
        result = QMessageBox.question(
            self, "Restart Services",
            "Restart the kegerator and web services?\n\n"
            "Both services will be back online within a few seconds.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        log.info("Service restart requested by user")
        subprocess.Popen(
            ["systemctl", "--user", "restart", "smartkegerator", "smartkegerator-web"],
            start_new_session=True,
        )

    def _reboot_system(self) -> None:
        result = QMessageBox.question(
            self, "Reboot System",
            "Reboot the Raspberry Pi?\n\n"
            "The kegerator will be unavailable for about 30 seconds.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        log.info("System reboot requested by user")
        subprocess.Popen(["sudo", "reboot"], start_new_session=True)
        QApplication.quit()

    def _shutdown_service(self) -> None:
        result = QMessageBox.question(
            self, "Shutdown Service",
            "Stop the kegerator service and return to the desktop?\n\n"
            "The service will not restart automatically until the next reboot\n"
            "or until you manually run:  systemctl --user start smartkegerator",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        # Stop the web service too, then exit — systemd will not auto-restart
        # because we're stopping the unit (not letting it crash).
        log.info("Shutdown requested by user — stopping services")
        subprocess.Popen(
            ["systemctl", "--user", "stop", "smartkegerator-web"],
            start_new_session=True,
        )
        # Stop this service last (a small delay lets the web stop command fire)
        subprocess.Popen(
            ["bash", "-c", "sleep 1 && systemctl --user stop smartkegerator"],
            start_new_session=True,
        )
        QApplication.quit()

    # ------------------------------------------------------------------
    # Widget factory
    # ------------------------------------------------------------------

    def _make_widget(self, kind: str, value: Any, opts) -> QWidget:
        if kind == "spin":
            w = QSpinBox()
            lo, hi = opts or (0, 9999)
            w.setRange(lo, hi)
            w.setValue(int(value) if value is not None else lo)
            return w

        if kind == "dspin":
            w = QDoubleSpinBox()
            lo, hi = opts or (0.0, 100.0)
            w.setRange(lo, hi)
            w.setSingleStep(0.05)
            w.setDecimals(2)
            w.setValue(float(value) if value is not None else lo)
            return w

        if kind == "check":
            w = QCheckBox()
            w.setChecked(bool(value))
            return w

        if kind == "password":
            w = QLineEdit(str(value) if value is not None else "")
            w.setEchoMode(QLineEdit.EchoMode.Password)
            return w

        # plain text / "line"
        w = QLineEdit(str(value) if value is not None else "")
        return w

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def _save(self) -> None:
        # Appearance fields
        self._config.setdefault("ui", {})
        self._config["ui"]["name"]  = self._w_name.text().strip() or "SmartKegerator"
        self._config["ui"]["theme"] = self._w_theme.currentData()

        # Display rotation
        self._config.setdefault("display", {})
        self._config["display"]["rotation"] = self._w_rotation.currentData()

        # Log level (DB-stored)
        level = self._w_log_level.currentData()
        if self._db:
            self._db.set_setting("log_level", level)
        apply_level(level)

        for (section, key), widget in self._widgets.items():
            value = self._read_widget(widget)
            if section not in self._config:
                self._config[section] = {}
            self._config[section][key] = value

        if self._config_path:
            try:
                with open(self._config_path, "w", encoding="utf-8") as f:
                    yaml.safe_dump(self._config, f, default_flow_style=False, allow_unicode=True)
                log.info("Settings saved to %s", self._config_path)
                QMessageBox.information(
                    self, "Saved",
                    "Settings saved.\n\nChanges to hardware pins, camera, or paths take effect after restart.",
                )
            except Exception as exc:
                log.error("Failed to save settings: %s", exc)
                QMessageBox.critical(self, "Error", f"Could not save settings:\n{exc}")
        else:
            QMessageBox.warning(
                self, "Warning",
                "Config file path unknown — settings updated in memory only (will not persist after restart).",
            )

        self.accept()

    @staticmethod
    def _read_widget(widget: QWidget) -> Any:
        if isinstance(widget, QCheckBox):
            return widget.isChecked()
        if isinstance(widget, QSpinBox):
            return widget.value()
        if isinstance(widget, QDoubleSpinBox):
            return widget.value()
        if isinstance(widget, QLineEdit):
            return widget.text()
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_config_path() -> Optional[str]:
    """Walk up from this file looking for config.yaml."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "config.yaml"
        if candidate.exists():
            return str(candidate)
    return None
