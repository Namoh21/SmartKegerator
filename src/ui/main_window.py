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
├─ Footer ─────────────────────────────────────────── 50 px ──┤
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
    QVBoxLayout, QWidget,
)

from data.database import Database
from data.models import Beer, Keg, get_configured_taps
from ui.theme import get as _get_theme, site_name as _site_name

log = logging.getLogger(__name__)


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
        background-color: {c['card']};
        color: {c['text']};
        border: 1px solid {c['accent']};
        border-radius: 4px;
        padding: 8px 18px;
        font-size: 17px;
    }}
    QPushButton:pressed {{
        background-color: {c['accent']};
    }}
    QProgressBar {{
        border: 1px solid {c['border']};
        border-radius: 4px;
        text-align: center;
        background-color: {c['deep']};
        font-size: 15px;
    }}
    QProgressBar::chunk {{
        border-radius: 4px;
    }}
"""


class MainWindow(QWidget):
    settings_requested = pyqtSignal()
    login_requested    = pyqtSignal()

    def __init__(self, config: dict, db: Database, recognizer=None, parent=None) -> None:
        super().__init__(parent)
        self._config     = config
        self._db         = db
        self._recognizer = recognizer
        self._c          = _get_theme(config)

        self.setWindowTitle(_site_name(config))
        self.setStyleSheet(_build_style(self._c))
        self.setMinimumSize(800, 480)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        root.addWidget(self._build_header())
        root.addLayout(self._build_content(), stretch=1)
        root.addWidget(self._build_footer())

        # Capture banner — shown briefly when a web-triggered photo is taken
        self._capture_banner = QLabel("")
        self._capture_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._capture_banner.setStyleSheet(
            f"background:{self._c['accent']}; color:{self._c['bg']};"
            f"font-size:20px; font-weight:bold; padding:10px; border-radius:4px;"
        )
        self._capture_banner.setVisible(False)
        root.addWidget(self._capture_banner)

        self._capture_banner_timer = QTimer()
        self._capture_banner_timer.setSingleShot(True)
        self._capture_banner_timer.timeout.connect(lambda: self._capture_banner.setVisible(False))

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
        c   = self._c
        bar = QWidget()
        bar.setFixedHeight(60)
        row = QHBoxLayout(bar)
        row.setContentsMargins(4, 0, 4, 0)
        row.setSpacing(0)

        # Left: date/time
        self._lbl_datetime = QLabel()
        self._lbl_datetime.setStyleSheet(
            f"color: {c['muted']}; font-size: 17px; font-family: monospace;"
        )
        row.addWidget(self._lbl_datetime, stretch=3)

        # Center: kegerator name
        title = QLabel(_site_name(self._config))
        font  = QFont()
        font.setPointSize(22)
        font.setWeight(QFont.Weight.Bold)
        title.setFont(font)
        title.setStyleSheet(f"color: {c['accent']};")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(title, stretch=4)

        # Right: ambient temp + humidity
        self._lbl_env = QLabel("—")
        self._lbl_env.setStyleSheet(
            f"color: {c['muted']}; font-size: 17px; font-family: monospace;"
        )
        self._lbl_env.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._lbl_env, stretch=3)

        return bar

    def _build_content(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        self._tap_cards: dict[str, _TapCard] = {}
        for tap_id, display_name in get_configured_taps(self._config):
            card = _TapCard(tap_id, display_name, self._c)
            self._tap_cards[tap_id] = card
            row.addWidget(card, stretch=1)

        return row

    def _build_footer(self) -> QWidget:
        c   = self._c
        bar = QWidget()
        bar.setFixedHeight(50)
        row = QHBoxLayout(bar)
        row.setContentsMargins(4, 0, 4, 0)

        self._lbl_current_user = QLabel("")
        self._lbl_current_user.setStyleSheet(f"color: {c['muted']}; font-size: 17px;")
        row.addWidget(self._lbl_current_user, stretch=1)

        self._login_btn = QPushButton("🔑  Login")
        self._login_btn.clicked.connect(self.login_requested.emit)
        row.addWidget(self._login_btn)

        self._settings_btn = QPushButton("⚙  Settings")
        self._settings_btn.clicked.connect(self.settings_requested.emit)
        row.addWidget(self._settings_btn)

        return bar

    # ------------------------------------------------------------------
    # Clock
    # ------------------------------------------------------------------

    def _update_clock(self) -> None:
        now = datetime.now()
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
        c = self._c
        if user_id is not None:
            badge = "  ⚡ Admin" if is_admin else ""
            self._lbl_current_user.setText(f"Welcome, {name}!{badge}")
            color = c['accent'] if not is_admin else "#f0c040"
            self._lbl_current_user.setStyleSheet(
                f"color: {color}; font-size: 17px; font-weight: bold;"
            )
        else:
            self._lbl_current_user.setText("")
            self._lbl_current_user.setStyleSheet(f"color: {c['muted']}; font-size: 17px;")

        if is_admin:
            self._settings_btn.setStyleSheet("")
            self._login_btn.setVisible(False)
        else:
            self._settings_btn.setStyleSheet(f"color: {c['muted']};")
            self._login_btn.setVisible(user_id is None)

    def show_capture_banner(self, message: str = "📷  Stand still — capturing photo…") -> None:
        """Flash a banner at the bottom of the screen for 3 seconds."""
        self._capture_banner.setText(message)
        self._capture_banner.setVisible(True)
        self._capture_banner_timer.start(3000)

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
    def __init__(self, tap_id: str, display_name: str = "", c: dict = {}, parent=None) -> None:
        super().__init__(parent)
        self._c = c
        self.setObjectName("card")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 14, 12, 14)
        layout.setSpacing(8)

        # Tap label
        tap_lbl = QLabel((display_name or tap_id).upper())
        tap_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tap_lbl.setStyleSheet(
            f"color: {c.get('muted', '#888')}; font-size: 17px; font-weight: bold; letter-spacing: 2px;"
        )
        layout.addWidget(tap_lbl)

        # Beer name
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
        self._lbl_sub.setStyleSheet(f"color: {c.get('muted', '#888')}; font-size: 18px;")
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
        self._lbl_stats.setStyleSheet(f"color: {c.get('muted', '#888')}; font-size: 18px;")
        layout.addWidget(self._lbl_stats)

        # Price
        self._lbl_price = QLabel("")
        self._lbl_price.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_price.setStyleSheet(
            f"color: {c.get('accent', '#e94560')}; font-size: 20px; font-weight: bold;"
        )
        layout.addWidget(self._lbl_price)

        self.update(None, None)

    def update(self, keg: Optional[Keg], beer: Optional[Beer]) -> None:  # type: ignore[override]
        c = self._c
        if keg is None or beer is None:
            self._lbl_beer.setText("No Keg")
            self._lbl_beer.setStyleSheet(f"color: {c.get('muted', '#888')};")
            self._lbl_sub.setText("")
            self._bar.setValue(0)
            self._bar.setFormat("Empty")
            self._bar.setStyleSheet(f"QProgressBar::chunk {{ background-color: {c.get('err', '#e74c3c')}; }}")
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
            bar_color = c.get('ok', '#2ecc71')
        elif pct > 10:
            bar_color = c.get('warn', '#e67e22')
        else:
            bar_color = c.get('err', '#e74c3c')
        self._bar.setStyleSheet(f"QProgressBar::chunk {{ background-color: {bar_color}; }}")

        stats_parts = []
        if beer.abv:
            stats_parts.append(f"ABV {beer.abv:.1f}%")
        if beer.ibu:
            stats_parts.append(f"IBU {beer.ibu}")
        self._lbl_stats.setText("  ·  ".join(stats_parts))

        price_per_pint = keg.price_for_ounces(16.0)
        self._lbl_price.setText(f"${price_per_pint:.2f} / pint" if price_per_pint else "")
