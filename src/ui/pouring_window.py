"""
Pouring window — replaces the main window while a pour is in progress.

Layout (800 × 480):
┌─ Header bar ────────────────────────────────────────────────── 50 px ─┐
│  POURING — LEFT TAP · African Amber              [Stop Pour]           │
├─ Camera feed ──────────────┬─ Info panel ───────────────────────────── ┤
│                            │                                           │
│   Live camera (640×360)    │   👤  Alice Smith  (96%)                 │
│                            │                                           │
│   Face detected indicator  │   🍺  African Amber                      │
│                            │       Mac & Jack's · Amber Ale           │
│                            │       ABV 5.2%  ·  IBU 52                │
│                            │                                           │
│                            │  ┌─ Pour ──────────────────────────────┐ │
│                            │  │        16.4 oz   ($2.87)            │ │
│                            │  └─────────────────────────────────────┘ │
│                            │                                           │
└────────────────────────────┴───────────────────────────────────────────┘
"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QPixmap
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

from data.database import Database
from data.models import Beer, Keg, UNKNOWN_USER_ID
from ui.theme import get as _get_theme

log = logging.getLogger(__name__)

_OUNCES_PER_LITER = 33.814


def _build_style(c: dict) -> str:
    return f"""
    QWidget {{
        background-color: {c['bg']};
        color: {c['text']};
        font-family: 'DejaVu Sans', Arial, sans-serif;
    }}
    QFrame#card {{
        background-color: {c['card']};
        border: 1px solid {c['border']};
        border-radius: 8px;
    }}
    QPushButton {{
        background-color: {c['accent']};
        color: white;
        border: none;
        border-radius: 4px;
        padding: 10px 22px;
        font-size: 18px;
        font-weight: bold;
    }}
    QPushButton:pressed {{
        background-color: {c['err']};
    }}
"""


class PouringWindow(QWidget):
    pour_cancelled = pyqtSignal()   # emitted if user manually stops the pour

    def __init__(self, config: dict, db: Database, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._db     = db
        self._c      = _get_theme(config)

        # Current pour state
        self._tap:         Optional[str]  = None
        self._keg:         Optional[Keg]  = None
        self._beer:        Optional[Beer] = None
        self._ticks:       int   = 0
        self._user_id:     Optional[int]  = None
        self._user_name:   str   = "Unknown"
        self._confidence:  float = 0.0
        self._face_found:  bool  = False

        self.setWindowTitle("Pouring")
        self.setStyleSheet(_build_style(self._c))

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        root.addWidget(self._build_header())
        root.addLayout(self._build_content(), stretch=1)

    # ------------------------------------------------------------------
    # Layout builders
    # ------------------------------------------------------------------

    def _build_header(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(60)
        row = QHBoxLayout(bar)
        row.setContentsMargins(8, 0, 8, 0)

        self._lbl_title = QLabel("POURING")
        font = QFont()
        font.setPointSize(20)
        font.setWeight(QFont.Weight.Bold)
        self._lbl_title.setFont(font)
        self._lbl_title.setStyleSheet(f"color: {self._c['accent']};")
        row.addWidget(self._lbl_title)

        row.addStretch()

        stop_btn = QPushButton("Stop Pour")
        stop_btn.clicked.connect(self._on_stop_clicked)
        row.addWidget(stop_btn)

        return bar

    def _build_content(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        # Left: camera feed
        cam_frame = QFrame()
        cam_frame.setObjectName("card")
        cam_layout = QVBoxLayout(cam_frame)
        cam_layout.setContentsMargins(4, 4, 4, 4)

        self._camera_label = QLabel()
        self._camera_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._camera_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._camera_label.setMinimumSize(320, 240)
        self._camera_label.setStyleSheet("color: #555;")
        self._camera_label.setText("Camera starting…")
        cam_layout.addWidget(self._camera_label)

        self._lbl_face_status = QLabel("")
        self._lbl_face_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_face_status.setFixedHeight(28)
        cam_layout.addWidget(self._lbl_face_status)

        row.addWidget(cam_frame, stretch=5)

        # Right: info panel
        row.addWidget(self._build_info_panel(), stretch=4)

        return row

    def _build_info_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # User identity
        self._lbl_user_icon = QLabel("👤")
        self._lbl_user_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_user_icon.setStyleSheet("font-size: 40px;")
        layout.addWidget(self._lbl_user_icon)

        self._lbl_user = QLabel("Identifying…")
        self._lbl_user.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont()
        font.setPointSize(19)
        font.setWeight(QFont.Weight.Bold)
        self._lbl_user.setFont(font)
        layout.addWidget(self._lbl_user)

        self._lbl_confidence = QLabel("")
        self._lbl_confidence.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_confidence.setStyleSheet(f"color: {self._c['muted']}; font-size: 15px;")
        layout.addWidget(self._lbl_confidence)

        # Divider
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color: {self._c['border']};")
        layout.addWidget(line)

        # Beer info
        self._lbl_beer_icon = QLabel("🍺")
        self._lbl_beer_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_beer_icon.setStyleSheet("font-size: 30px;")
        layout.addWidget(self._lbl_beer_icon)

        self._lbl_beer_name = QLabel("—")
        self._lbl_beer_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font2 = QFont()
        font2.setPointSize(17)
        font2.setWeight(QFont.Weight.Bold)
        self._lbl_beer_name.setFont(font2)
        layout.addWidget(self._lbl_beer_name)

        self._lbl_beer_sub = QLabel("")
        self._lbl_beer_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_beer_sub.setStyleSheet(f"color: {self._c['muted']}; font-size: 15px;")
        self._lbl_beer_sub.setWordWrap(True)
        layout.addWidget(self._lbl_beer_sub)

        layout.addStretch()

        # Pour amount card
        pour_frame = QFrame()
        pour_frame.setStyleSheet(
            f"background-color: {self._c['deep']}; border: 1px solid {self._c['accent']}; border-radius: 6px;"
        )
        pour_layout = QVBoxLayout(pour_frame)
        pour_layout.setContentsMargins(12, 8, 12, 8)
        pour_layout.setSpacing(2)

        self._lbl_ounces = QLabel("0.0 oz")
        self._lbl_ounces.setAlignment(Qt.AlignmentFlag.AlignCenter)
        oz_font = QFont()
        oz_font.setPointSize(27)
        oz_font.setWeight(QFont.Weight.Bold)
        self._lbl_ounces.setFont(oz_font)
        self._lbl_ounces.setStyleSheet(f"color: {self._c['ok']};")
        pour_layout.addWidget(self._lbl_ounces)

        self._lbl_price = QLabel("$0.00")
        self._lbl_price.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_price.setStyleSheet(f"color: {self._c['muted']}; font-size: 18px;")
        pour_layout.addWidget(self._lbl_price)

        layout.addWidget(pour_frame)

        return panel

    # ------------------------------------------------------------------
    # Pour lifecycle (called by App)
    # ------------------------------------------------------------------

    def start_pour(self, tap: str, keg: Optional[Keg], beer: Optional[Beer]) -> None:
        self._tap        = tap
        self._keg        = keg
        self._beer       = beer
        self._ticks      = 0
        self._user_id    = None
        self._user_name  = "Identifying…"
        self._confidence = 0.0
        self._face_found = False

        self._lbl_title.setText(f"POURING  —  {tap.upper()} TAP")

        if beer:
            self._lbl_beer_name.setText(beer.name)
            sub_parts = [p for p in (beer.company, beer.style) if p]
            abv_ibu = "  ·  ".join(
                [p for p in (
                    f"ABV {beer.abv:.1f}%" if beer.abv else "",
                    f"IBU {beer.ibu}"      if beer.ibu else "",
                ) if p]
            )
            sub_parts.append(abv_ibu)
            self._lbl_beer_sub.setText("\n".join(p for p in sub_parts if p))
        else:
            self._lbl_beer_name.setText("Unknown Beer")
            self._lbl_beer_sub.setText("")

        self._lbl_user.setText("Identifying…")
        self._lbl_confidence.setText("")
        self._update_pour_display()

    def end_pour(self) -> None:
        self._tap  = None
        self._keg  = None
        self._beer = None

    # ------------------------------------------------------------------
    # Slots wired by App
    # ------------------------------------------------------------------

    def on_frame(self, pixmap: QPixmap) -> None:
        """Display the latest camera frame, scaled to fit the label."""
        scaled = pixmap.scaled(
            self._camera_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._camera_label.setPixmap(scaled)

    def on_tick(self, tap: str, ticks: int) -> None:
        if tap != self._tap:
            return
        self._ticks = ticks
        self._update_pour_display()

    def on_user_identified(self, user_id: int, confidence: float) -> None:
        self._user_id   = user_id
        self._confidence = confidence

        user = self._db.get_user(user_id)
        self._user_name = user.name if user else "Unknown"

        self._lbl_user.setText(self._user_name)
        self._lbl_confidence.setText(f"Confidence: {confidence * 100:.0f}%")
        self._lbl_confidence.setStyleSheet(
            f"color: {self._c['ok']}; font-size: 15px;" if confidence >= 0.7
            else f"color: {self._c['warn']}; font-size: 15px;"
        )

    def on_face_detected(self, found: bool) -> None:
        self._face_found = found
        if found:
            self._lbl_face_status.setText("● Face detected")
            self._lbl_face_status.setStyleSheet(f"color: {self._c['ok']}; font-size: 15px;")
        else:
            self._lbl_face_status.setText("○ No face detected")
            self._lbl_face_status.setStyleSheet(f"color: {self._c['muted']}; font-size: 15px;")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _update_pour_display(self) -> None:
        ticks_per_liter = self._config["hardware"].get("ticks_per_liter", 500)
        liters  = self._ticks / ticks_per_liter if ticks_per_liter else 0.0
        ounces  = liters * _OUNCES_PER_LITER

        self._lbl_ounces.setText(f"{ounces:.1f} oz")

        if self._keg:
            price = self._keg.price_for_ounces(ounces)
            self._lbl_price.setText(f"${price:.2f}")
        else:
            self._lbl_price.setText("")

    def _on_stop_clicked(self) -> None:
        log.info("User manually stopped pour on %s tap", self._tap)
        self.pour_cancelled.emit()

    # ------------------------------------------------------------------
    # Properties read by App after pour finishes
    # ------------------------------------------------------------------

    @property
    def current_keg(self) -> Optional[Keg]:
        return self._keg

    @property
    def current_user_id(self) -> Optional[int]:
        return self._user_id
