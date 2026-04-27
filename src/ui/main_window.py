"""
Main window — always-visible home screen.

Layout (800 × 480):
┌─ Header ─────────────────────────────────────────── 60 px ─┐
│  Mon Apr 27 · 2:32 PM  │  SmartKegerator  │  68°F · 45% Hum│
├─ Tap cards (fill remaining area) ────────────────────────── ┤
│  ┌─ LEFT TAP ──────┐  ┌─ CENTER TAP ─────┐  ┌─ RIGHT ─────┐│
│  │  Beer Name      │  │  Beer Name       │  │  Beer Name  ││
│  │  Company/Style  │  │  Company/Style   │  │  Co./Style  ││
│  │  ████████░ 75%  │  │  ██████████ 100% │  │  ████░ 33%  ││
│  │  ABV 5.2% IBU52 │  │  ABV 6.5% IBU40  │  │  ABV 4.2%   ││
│  │  $2.50 / pint   │  │  $3.00 / pint    │  │  $2.75/pint ││
│  └─────────────────┘  └──────────────────┘  └─────────────┘│
├─ Footer ─────────────────────────────────────── 50 px ─────┤
│  Welcome, Brian!                              [⚙ Settings]  │
└────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

from data.database import Database
from data.models import Beer, Keg, get_configured_taps

log = logging.getLogger(__name__)

_DARK_BG     = "#1a1a2e"
_CARD_BG     = "#16213e"
_ACCENT      = "#e94560"
_TEXT        = "#eaeaea"
_MUTED       = "#8888aa"
_LEVEL_OK    = "#2ecc71"
_LEVEL_LOW   = "#e67e22"
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
        padding: 8px 18px;
        font-size: 17px;
    }}
    QPushButton:pressed {{
        background-color: {_ACCENT};
    }}
    QProgressBar {{
        border: 1px solid #2a2a4e;
        border-radius: 4px;
        text-align: center;
        background-color: #0f0f23;
        font-size: 15px;
    }}
    QProgressBar::chunk {{
        border-radius: 4px;
    }}
"""


class MainWindow(QWidget):
    settings_requested = pyqtSignal()

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
        root.setSpacing(6)

        root.addWidget(self._build_header())
        root.addLayout(self._build_content(), stretch=1)
        root.addWidget(self._build_footer())

        # Clock — tick every second
        self._clock = QTimer()
        self._clock.timeout.connect(self._update_clock)
        self._clock.start(1000)
        self._update_clock()

        self.refresh()

    # ------------------------------------------------------------------
    # Layout builders
    # ------------------------------------------------------------------

    def _build_header(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(60)
        row = QHBoxLayout(bar)
        row.setContentsMargins(4, 0, 4, 0)
        row.setSpacing(0)

        # Left: date/time
        self._lbl_datetime = QLabel()
        self._lbl_datetime.setStyleSheet(
            f"color: {_MUTED}; font-size: 17px; font-family: monospace;"
        )
        row.addWidget(self._lbl_datetime, stretch=3)

        # Center: kegerator name
        name = self._config.get("ui", {}).get("name", "SmartKegerator")
        title = QLabel(name)
        font  = QFont()
        font.setPointSize(22)
        font.setWeight(QFont.Weight.Bold)
        title.setFont(font)
        title.setStyleSheet(f"color: {_ACCENT};")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(title, stretch=4)

        # Right: ambient temp + humidity
        self._lbl_env = QLabel("—")
        self._lbl_env.setStyleSheet(
            f"color: {_MUTED}; font-size: 17px; font-family: monospace;"
        )
        self._lbl_env.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._lbl_env, stretch=3)

        return bar

    def _build_content(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        self._tap_cards: dict[str, _TapCard] = {}
        for tap_id, display_name in get_configured_taps(self._config):
            card = _TapCard(tap_id, display_name)
            self._tap_cards[tap_id] = card
            row.addWidget(card, stretch=1)

        return row

    def _build_footer(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(50)
        row = QHBoxLayout(bar)
        row.setContentsMargins(4, 0, 4, 0)

        self._lbl_current_user = QLabel("Tap to pour")
        self._lbl_current_user.setStyleSheet(f"color: {_MUTED}; font-size: 17px;")
        row.addWidget(self._lbl_current_user, stretch=1)

        self._settings_btn = QPushButton("⚙  Settings")
        self._settings_btn.clicked.connect(self.settings_requested.emit)
        row.addWidget(self._settings_btn)

        return bar

    # ------------------------------------------------------------------
    # Clock
    # ------------------------------------------------------------------

    def _update_clock(self) -> None:
        now = datetime.now()
        # %-I / %-d strip leading zeros on Linux (Pi)
        try:
            text = now.strftime("%-I:%M %p  ·  %a %b %-d")
        except ValueError:
            text = now.strftime("%I:%M %p  ·  %a %b %d")
        self._lbl_datetime.setText(text)

    # ------------------------------------------------------------------
    # Public API called by App
    # ------------------------------------------------------------------

    def set_current_user(
        self,
        user_id: Optional[int],
        name: str,
        is_admin: bool = False,
    ) -> None:
        """Called by App whenever the touchscreen session user changes."""
        if user_id is not None:
            badge = "  ⚡ Admin" if is_admin else ""
            self._lbl_current_user.setText(f"Welcome, {name}!{badge}")
            color = _ACCENT if not is_admin else "#f0c040"
            self._lbl_current_user.setStyleSheet(
                f"color: {color}; font-size: 17px; font-weight: bold;"
            )
        else:
            self._lbl_current_user.setText("Tap to pour")
            self._lbl_current_user.setStyleSheet(f"color: {_MUTED}; font-size: 17px;")

        # Dim settings button for non-admins (click still works — App guards access)
        if is_admin:
            self._settings_btn.setStyleSheet("")
        else:
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
        parts: list[str] = []
        if ambient_f is not None:
            parts.append(f"{ambient_f:.0f}°F")
        if humidity is not None:
            parts.append(f"{humidity:.0f}% Hum")
        if liquid_f is not None:
            parts.append(f"Liq {liquid_f:.0f}°F")
        self._lbl_env.setText("  ·  ".join(parts) if parts else "—")


# ---------------------------------------------------------------------------
# Tap card widget
# ---------------------------------------------------------------------------

class _TapCard(QFrame):
    def __init__(self, tap_id: str, display_name: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("card")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 14, 12, 14)
        layout.setSpacing(8)

        # Tap label
        tap_lbl = QLabel((display_name or tap_id).upper())
        tap_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tap_lbl.setStyleSheet(
            f"color: {_MUTED}; font-size: 17px; font-weight: bold; letter-spacing: 2px;"
        )
        layout.addWidget(tap_lbl)

        # Beer name — largest element, most readable from distance
        self._lbl_beer = QLabel("No Keg")
        self._lbl_beer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_beer.setWordWrap(True)
        font = QFont()
        font.setPointSize(26)
        font.setWeight(QFont.Weight.Bold)
        self._lbl_beer.setFont(font)
        layout.addWidget(self._lbl_beer)

        # Company / style
        self._lbl_sub = QLabel("")
        self._lbl_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_sub.setStyleSheet(f"color: {_MUTED}; font-size: 18px;")
        self._lbl_sub.setWordWrap(True)
        layout.addWidget(self._lbl_sub)

        layout.addStretch()

        # Level bar
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setFixedHeight(32)
        self._bar.setTextVisible(True)
        layout.addWidget(self._bar)

        # Stats row (ABV · IBU)
        self._lbl_stats = QLabel("")
        self._lbl_stats.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_stats.setStyleSheet(f"color: {_MUTED}; font-size: 18px;")
        layout.addWidget(self._lbl_stats)

        # Price
        self._lbl_price = QLabel("")
        self._lbl_price.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_price.setStyleSheet(
            f"color: {_ACCENT}; font-size: 20px; font-weight: bold;"
        )
        layout.addWidget(self._lbl_price)

        self.update(None, None)

    def update(self, keg: Optional[Keg], beer: Optional[Beer]) -> None:  # type: ignore[override]
        if keg is None or beer is None:
            self._lbl_beer.setText("No Keg")
            self._lbl_beer.setStyleSheet(f"color: {_MUTED};")
            self._lbl_sub.setText("")
            self._bar.setValue(0)
            self._bar.setFormat("Empty")
            self._bar.setStyleSheet(f"QProgressBar::chunk {{ background-color: {_LEVEL_EMPTY}; }}")
            self._lbl_stats.setText("")
            self._lbl_price.setText("")
            return

        self._lbl_beer.setText(beer.name)
        self._lbl_beer.setStyleSheet("")
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
