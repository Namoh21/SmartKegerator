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
from pathlib import Path
from typing import Any, Optional

import yaml
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QDoubleSpinBox, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

log = logging.getLogger(__name__)

_DARK_BG = "#1a1a2e"
_CARD_BG = "#16213e"
_ACCENT  = "#e94560"
_TEXT    = "#eaeaea"
_MUTED   = "#8888aa"

_STYLE = f"""
    QDialog, QWidget, QScrollArea, QGroupBox {{
        background-color: {_DARK_BG};
        color: {_TEXT};
        font-family: 'DejaVu Sans', Arial, sans-serif;
    }}
    QGroupBox {{
        border: 1px solid #2a2a4e;
        border-radius: 6px;
        margin-top: 10px;
        padding-top: 6px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        color: {_MUTED};
        font-size: 11px;
        letter-spacing: 1px;
    }}
    QLineEdit, QSpinBox, QDoubleSpinBox {{
        background-color: {_CARD_BG};
        color: {_TEXT};
        border: 1px solid #2a2a4e;
        border-radius: 4px;
        padding: 4px 8px;
        min-width: 180px;
    }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
        border-color: {_ACCENT};
    }}
    QCheckBox {{
        color: {_TEXT};
    }}
    QPushButton {{
        background-color: #2a2a4e;
        color: {_TEXT};
        border: 1px solid {_ACCENT};
        border-radius: 4px;
        padding: 7px 18px;
    }}
    QPushButton#save {{
        background-color: {_ACCENT};
        color: white;
        border: none;
    }}
    QPushButton:pressed {{ background-color: {_ACCENT}; }}
"""


class SettingsWindow(QDialog):
    def __init__(self, config: dict, db, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._config_path = _find_config_path()
        self._widgets: dict[tuple[str, str], QWidget] = {}

        self.setWindowTitle("Settings")
        self.setStyleSheet(_STYLE)
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
        title.setStyleSheet(f"color: {_ACCENT};")
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

        layout.addWidget(self._build_group(
            "POUR",
            [
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
                ("hardware", "camera_index",  "Camera device index", "spin", (0, 10)),
                ("hardware", "camera_width",  "Capture width",       "spin", (160, 1920)),
                ("hardware", "camera_height", "Capture height",      "spin", (120, 1080)),
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
                ("admin", "password", "Admin password", "password", None),
            ],
        ))

        layout.addWidget(self._build_group(
            "UI",
            [
                ("ui", "fullscreen", "Fullscreen mode", "check", None),
            ],
        ))

        layout.addStretch()
        scroll.setWidget(container)
        return scroll

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

        if self._config_path:
            path_lbl = QLabel(f"Config: {self._config_path}")
            path_lbl.setStyleSheet(f"color: {_MUTED}; font-size: 11px;")
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
