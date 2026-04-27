"""
Main window — always-visible home screen.

Layout (800 × 480):
┌─ Header bar ─────────────────────────────────────────── 50 px ─┐
│  SmartKegerator          [History]  [Users]  [Settings]         │
├─ Tap cards (3) ─────────────────── Sidebar ─────────────────────┤
│  ┌─ Left ──┐  ┌─ Center ─┐  ┌─ Right ──┐  │  Ambient: 68°F     │
│  │ Beer    │  │ Beer     │  │ Beer     │  │  Humidity: 45%     │
│  │ Name    │  │ Name     │  │ Name     │  │                    │
│  │ ▓▓▓▓░░ │  │ ▓▓▓▓▓▓▓ │  │ ▓▓░░░░ │  │  Liquid: 38°F      │
│  │ 62%     │  │ 100%     │  │ 33%      │  │                    │
│  │ ABV 5.2 │  │ ABV 6.5  │  │ ABV 4.2  │  │                    │
│  │ $2.50/pt│  │ $3.00/pt │  │ $2.75/pt │  │                    │
│  └─────────┘  └──────────┘  └──────────┘  │                    │
└─────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

from data.database import Database
from data.models import Beer, Keg, get_configured_taps

log = logging.getLogger(__name__)

_DARK_BG   = "#1a1a2e"
_CARD_BG   = "#16213e"
_ACCENT    = "#e94560"
_TEXT      = "#eaeaea"
_MUTED     = "#8888aa"
_LEVEL_OK  = "#2ecc71"
_LEVEL_LOW = "#e67e22"
_LEVEL_EMPTY = "#e74c3c"

_GLOBAL_STYLE = f"""
    QWidget {{
        background-color: {_DARK_BG};
        color: {_TEXT};
        font-family: 'DejaVu Sans', Arial, sans-serif;
    }}
    QFrame#card {{
        background-color: {_CARD_BG};
        border: 1px solid #2a2a4e;
        border-radius: 8px;
    }}
    QPushButton {{
        background-color: #2a2a4e;
        color: {_TEXT};
        border: 1px solid {_ACCENT};
        border-radius: 4px;
        padding: 6px 14px;
        font-size: 13px;
    }}
    QPushButton:pressed {{
        background-color: {_ACCENT};
    }}
    QProgressBar {{
        border: 1px solid #2a2a4e;
        border-radius: 4px;
        text-align: center;
        background-color: #0f0f23;
    }}
    QProgressBar::chunk {{
        border-radius: 4px;
    }}
"""


class MainWindow(QWidget):
    history_requested  = pyqtSignal()
    settings_requested = pyqtSignal()
    users_requested    = pyqtSignal()

    def __init__(self, config: dict, db: Database, recognizer=None, parent=None) -> None:
        super().__init__(parent)
        self._config     = config
        self._db         = db
        self._recognizer = recognizer

        self.setWindowTitle("SmartKegerator")
        self.setStyleSheet(_GLOBAL_STYLE)
        self.setMinimumSize(800, 480)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        root.addWidget(self._build_header())
        root.addLayout(self._build_content(), stretch=1)

        self.refresh()

    # ------------------------------------------------------------------
    # Layout builders
    # ------------------------------------------------------------------

    def _build_header(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(50)
        row = QHBoxLayout(bar)
        row.setContentsMargins(4, 0, 4, 0)

        title = QLabel("SmartKegerator")
        font  = QFont()
        font.setPointSize(18)
        font.setWeight(QFont.Weight.Bold)
        title.setFont(font)
        title.setStyleSheet(f"color: {_ACCENT};")
        row.addWidget(title)

        # Current user greeting — updated by App.set_current_user()
        self._lbl_current_user = QLabel("Tap to pour")
        self._lbl_current_user.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_current_user.setStyleSheet(f"color: {_MUTED}; font-size: 13px;")
        row.addWidget(self._lbl_current_user, stretch=1)

        for label, signal in [
            ("History",  self.history_requested),
            ("Users",    self.users_requested),
        ]:
            btn = QPushButton(label)
            btn.clicked.connect(signal.emit)
            row.addWidget(btn)

        self._settings_btn = QPushButton("\U0001f512 Settings")
        self._settings_btn.clicked.connect(self.settings_requested.emit)
        row.addWidget(self._settings_btn)

        return bar

    def _build_content(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        self._tap_cards: dict[str, _TapCard] = {}
        for tap_id, display_name in get_configured_taps(self._config):
            card = _TapCard(tap_id, display_name)
            self._tap_cards[tap_id] = card
            row.addWidget(card, stretch=3)

        row.addWidget(self._build_sidebar(), stretch=2)
        return row

    def _build_sidebar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        header = QLabel("Environment")
        header.setStyleSheet(f"color: {_MUTED}; font-size: 11px;")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header)

        self._lbl_ambient  = _reading_label("Ambient", "—")
        self._lbl_humidity = _reading_label("Humidity", "—")
        self._lbl_liquid   = _reading_label("Liquid", "—")

        for widget in (self._lbl_ambient, self._lbl_humidity, self._lbl_liquid):
            layout.addWidget(widget)

        layout.addStretch()
        return frame

    # ------------------------------------------------------------------
    # Data refresh
    # ------------------------------------------------------------------

    def set_current_user(
        self,
        user_id: Optional[int],
        name: str,
        is_admin: bool = False,
    ) -> None:
        """Called by App whenever the touchscreen session user changes."""
        if user_id is not None:
            badge = " ⚡ Admin" if is_admin else ""
            self._lbl_current_user.setText(f"Welcome, {name}!{badge}")
            color = _ACCENT if not is_admin else "#f0c040"
            self._lbl_current_user.setStyleSheet(
                f"color: {color}; font-size: 13px; font-weight: bold;"
            )
        else:
            self._lbl_current_user.setText("Tap to pour")
            self._lbl_current_user.setStyleSheet(f"color: {_MUTED}; font-size: 13px;")

        # Reflect admin state on the Settings button
        if is_admin:
            self._settings_btn.setText("Settings")
            self._settings_btn.setStyleSheet("")
        else:
            self._settings_btn.setText("\U0001f512 Settings")
            self._settings_btn.setStyleSheet(f"color: {_MUTED};")

    def refresh(self) -> None:
        taps = self._db.get_tap_assignments()
        for tap_id, card in self._tap_cards.items():
            keg_id = taps.get_keg_id(tap_id)
            keg    = self._db.get_keg(keg_id) if keg_id is not None else None
            beer   = self._db.get_beer(keg.beer_id) if keg else None
            card.update(keg, beer)

    # ------------------------------------------------------------------
    # Sensor slot
    # ------------------------------------------------------------------

    def on_readings_updated(
        self,
        ambient_f: Optional[float],
        humidity:  Optional[float],
        liquid_f:  Optional[float],
    ) -> None:
        self._lbl_ambient.setText(
            f"Ambient:  {ambient_f:.1f} °F" if ambient_f is not None else "Ambient:  —"
        )
        self._lbl_humidity.setText(
            f"Humidity: {humidity:.0f} %" if humidity is not None else "Humidity: —"
        )
        self._lbl_liquid.setText(
            f"Liquid:   {liquid_f:.1f} °F" if liquid_f is not None else "Liquid:   —"
        )


# ---------------------------------------------------------------------------
# Tap card widget
# ---------------------------------------------------------------------------

class _TapCard(QFrame):
    def __init__(self, tap_id: str, display_name: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("card")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        # Tap label
        tap_lbl = QLabel((display_name or tap_id).upper())
        tap_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tap_lbl.setStyleSheet(f"color: {_MUTED}; font-size: 11px; font-weight: bold; letter-spacing: 2px;")
        layout.addWidget(tap_lbl)

        # Beer name
        self._lbl_beer = QLabel("No Keg")
        self._lbl_beer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_beer.setWordWrap(True)
        font = QFont()
        font.setPointSize(14)
        font.setWeight(QFont.Weight.Bold)
        self._lbl_beer.setFont(font)
        layout.addWidget(self._lbl_beer)

        # Company / style
        self._lbl_sub = QLabel("")
        self._lbl_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_sub.setStyleSheet(f"color: {_MUTED}; font-size: 11px;")
        self._lbl_sub.setWordWrap(True)
        layout.addWidget(self._lbl_sub)

        # Level bar
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setFixedHeight(22)
        self._bar.setTextVisible(True)
        layout.addWidget(self._bar)

        # Stats row (ABV · IBU)
        self._lbl_stats = QLabel("")
        self._lbl_stats.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_stats.setStyleSheet(f"color: {_MUTED}; font-size: 11px;")
        layout.addWidget(self._lbl_stats)

        # Price
        self._lbl_price = QLabel("")
        self._lbl_price.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_price.setStyleSheet(f"color: {_ACCENT}; font-size: 13px; font-weight: bold;")
        layout.addWidget(self._lbl_price)

        layout.addStretch()
        self.update(None, None)

    def update(self, keg: Optional[Keg], beer: Optional[Beer]) -> None:  # type: ignore[override]
        if keg is None or beer is None:
            self._lbl_beer.setText("No Keg")
            self._lbl_sub.setText("")
            self._bar.setValue(0)
            self._bar.setFormat("Empty")
            self._bar.setStyleSheet(f"QProgressBar::chunk {{ background-color: {_LEVEL_EMPTY}; }}")
            self._lbl_stats.setText("")
            self._lbl_price.setText("")
            return

        self._lbl_beer.setText(beer.name)
        sub_parts = [p for p in (beer.company, beer.style) if p]
        self._lbl_sub.setText("  ·  ".join(sub_parts))

        pct = int(keg.percent_remaining)
        self._bar.setValue(pct)
        self._bar.setFormat(f"{pct}%  ({keg.liters_remaining:.1f} L left)")

        if pct > 25:
            color = _LEVEL_OK
        elif pct > 10:
            color = _LEVEL_LOW
        else:
            color = _LEVEL_EMPTY
        self._bar.setStyleSheet(f"QProgressBar::chunk {{ background-color: {color}; }}")

        stats_parts = []
        if beer.abv:
            stats_parts.append(f"ABV {beer.abv:.1f}%")
        if beer.ibu:
            stats_parts.append(f"IBU {beer.ibu}")
        self._lbl_stats.setText("  ·  ".join(stats_parts))

        price_per_pint = keg.price_for_ounces(16.0)
        self._lbl_price.setText(f"${price_per_pint:.2f} / pint" if price_per_pint else "")


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _reading_label(title: str, value: str) -> QLabel:
    lbl = QLabel(f"{title}:  {value}")
    lbl.setStyleSheet(f"color: {_TEXT}; font-size: 13px; font-family: monospace;")
    return lbl
