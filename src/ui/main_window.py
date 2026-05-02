"""
Main window — always-visible home screen.

Layout (800 × 480):
┌─ Header ─────────────────────────────────────────── 60 px ─┐
│  Mon Apr 27 · 2:32 PM  │  SmartKegerator  │  68°F · 45% Hum│
├─ Stats bar ────────────────────────────────────── 36 px ───┤
│   5 pours today  ·  48.2 oz  ·  $12.05 revenue             │
├─ Tap cards ────────────────────────────────── fill ────────┤
│  ┌─ LEFT TAP ──────┐  ┌─ CENTER TAP ─────┐  ┌─ RIGHT ─────┐│
│  │  Beer Name      │  │  Beer Name       │  │  Beer Name  ││
│  │  ████████░ 75%  │  │  ██████████ 100% │  │  ████░ 33%  ││
│  │  $2.50 / pint   │  │  $3.00 / pint    │  │  $2.75/pint ││
│  └─────────────────┘  └──────────────────┘  └─────────────┘│
├─ Recent pours ─────────────────────────────── 110 px ──────┤
│  Alice   Boston Lager   16.0 oz   2:30 PM                   │
│  Bob     IPA            12.5 oz   1:45 PM                   │
├─ Footer ─────────────────────────────────────── 50 px ──────┤
│  Welcome, Alice!                              [⚙ Settings]  │
└────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)
from PyQt6.QtCore import pyqtSignal

from data.database import Database
from data.models import Beer, Keg, get_configured_taps
from ui.theme import get as _get_theme, site_name as _site_name

log = logging.getLogger(__name__)

_POUR_ROWS = 4   # number of recent pour rows shown


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
    QFrame#statsbar {{
        background-color: {c['card']};
        border: 1px solid {c['border']};
        border-radius: 6px;
    }}
    QFrame#poursbar {{
        background-color: {c['card']};
        border: 1px solid {c['border']};
        border-radius: 6px;
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
        root.setSpacing(5)

        root.addWidget(self._build_header())
        root.addWidget(self._build_stats_bar())
        root.addLayout(self._build_tap_row(), stretch=3)
        root.addWidget(self._build_recent_pours(), stretch=0)
        root.addWidget(self._build_footer())

        # Capture banner
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
        bar.setFixedHeight(58)
        row = QHBoxLayout(bar)
        row.setContentsMargins(4, 0, 4, 0)
        row.setSpacing(0)

        self._lbl_datetime = QLabel()
        self._lbl_datetime.setStyleSheet(
            f"color: {c['muted']}; font-size: 16px; font-family: monospace;"
        )
        row.addWidget(self._lbl_datetime, stretch=3)

        title = QLabel(_site_name(self._config))
        font  = QFont()
        font.setPointSize(20)
        font.setWeight(QFont.Weight.Bold)
        title.setFont(font)
        title.setStyleSheet(f"color: {c['accent']};")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(title, stretch=4)

        self._lbl_env = QLabel("—")
        self._lbl_env.setStyleSheet(
            f"color: {c['muted']}; font-size: 16px; font-family: monospace;"
        )
        self._lbl_env.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._lbl_env, stretch=3)

        return bar

    def _build_stats_bar(self) -> QWidget:
        c    = self._c
        bar  = QFrame()
        bar.setObjectName("statsbar")
        bar.setFixedHeight(34)
        row  = QHBoxLayout(bar)
        row.setContentsMargins(12, 0, 12, 0)
        row.setSpacing(0)

        lbl_style = f"color: {c['muted']}; font-size: 15px;"
        val_style = f"color: {c['text']}; font-size: 15px; font-weight: bold;"

        self._stat_pours = QLabel("0")
        self._stat_pours.setStyleSheet(val_style)
        self._stat_oz    = QLabel("0.0 oz")
        self._stat_oz.setStyleSheet(val_style)
        self._stat_rev   = QLabel("$0.00")
        self._stat_rev.setStyleSheet(val_style)

        def _add(lbl_text, val_lbl):
            lbl = QLabel(lbl_text)
            lbl.setStyleSheet(lbl_style)
            row.addWidget(lbl)
            row.addWidget(val_lbl)

        _add("Today:  ", self._stat_pours)
        _add("  pours  ·  ", self._stat_oz)
        _add("  ·  ", self._stat_rev)
        row.addStretch()

        return bar

    def _build_tap_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        self._tap_cards: dict[str, _TapCard] = {}
        for tap_id, display_name in get_configured_taps(self._config):
            card = _TapCard(tap_id, display_name, self._c)
            self._tap_cards[tap_id] = card
            row.addWidget(card, stretch=1)

        return row

    def _build_recent_pours(self) -> QWidget:
        c    = self._c
        frame = QFrame()
        frame.setObjectName("poursbar")
        frame.setFixedHeight(_POUR_ROWS * 26 + 10)

        col = QVBoxLayout(frame)
        col.setContentsMargins(10, 4, 10, 4)
        col.setSpacing(1)

        hdr_style  = f"color: {c['muted']}; font-size: 12px; font-weight: bold; letter-spacing: 1px;"
        row_style  = f"color: {c['text']}; font-size: 14px;"
        time_style = f"color: {c['muted']}; font-size: 13px;"

        # Header row
        hdr = QHBoxLayout()
        hdr.setSpacing(0)
        for text, stretch in [("RECENT POURS", 3), ("BEER", 3), ("OZ", 1), ("TIME", 2)]:
            lbl = QLabel(text)
            lbl.setStyleSheet(hdr_style)
            hdr.addWidget(lbl, stretch=stretch)
        col.addLayout(hdr)

        self._pour_rows: list[tuple[QLabel, QLabel, QLabel, QLabel]] = []
        for _ in range(_POUR_ROWS):
            r = QHBoxLayout()
            r.setSpacing(0)
            user_lbl = QLabel("")
            user_lbl.setStyleSheet(row_style)
            beer_lbl = QLabel("")
            beer_lbl.setStyleSheet(f"color: {c['muted']}; font-size: 14px;")
            oz_lbl   = QLabel("")
            oz_lbl.setStyleSheet(row_style)
            time_lbl = QLabel("")
            time_lbl.setStyleSheet(time_style)
            for lbl, stretch in [(user_lbl, 3), (beer_lbl, 3), (oz_lbl, 1), (time_lbl, 2)]:
                r.addWidget(lbl, stretch=stretch)
            col.addLayout(r)
            self._pour_rows.append((user_lbl, beer_lbl, oz_lbl, time_lbl))

        return frame

    def _build_footer(self) -> QWidget:
        c   = self._c
        bar = QWidget()
        bar.setFixedHeight(48)
        row = QHBoxLayout(bar)
        row.setContentsMargins(4, 0, 4, 0)

        self._lbl_current_user = QLabel("")
        self._lbl_current_user.setStyleSheet(f"color: {c['muted']}; font-size: 17px;")
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
        else:
            self._settings_btn.setStyleSheet(f"color: {c['muted']};")

    def show_capture_banner(self, message: str = "📷  Stand still — capturing photo…") -> None:
        self._capture_banner.setText(message)
        self._capture_banner.setVisible(True)
        self._capture_banner_timer.start(3000)

    def refresh(self) -> None:
        self._refresh_taps()
        self._refresh_stats()
        self._refresh_recent_pours()

    # ------------------------------------------------------------------
    # Internal refresh helpers
    # ------------------------------------------------------------------

    def _refresh_taps(self) -> None:
        taps = self._db.get_tap_assignments()
        for tap_id, card in self._tap_cards.items():
            keg_id = taps.get_keg_id(tap_id)
            keg    = self._db.get_keg(keg_id) if keg_id is not None else None
            beer   = self._db.get_beer(keg.beer_id) if keg else None
            card.update(keg, beer)

    def _refresh_stats(self) -> None:
        try:
            today_start = datetime.now().replace(
                hour=0, minute=0, second=0, microsecond=0
            ).timestamp()
            pours = self._db.get_pours_since(today_start)
            count   = len(pours)
            oz      = sum(p.ounces for p in pours)
            revenue = sum(p.price  for p in pours)
            self._stat_pours.setText(str(count))
            self._stat_oz.setText(f"{oz:.1f} oz")
            self._stat_rev.setText(f"${revenue:.2f}")
        except Exception as exc:
            log.warning("Stats refresh error: %s", exc)

    def _refresh_recent_pours(self) -> None:
        try:
            since  = time.time() - 24 * 3600
            pours  = sorted(
                self._db.get_pours_since(since),
                key=lambda p: p.time, reverse=True
            )[:_POUR_ROWS]

            users: dict[int, str] = {u.id: u.name for u in self._db.get_all_users()}
            keg_beer: dict[int, str] = {}

            def beer_for(keg_id: int) -> str:
                if keg_id not in keg_beer:
                    keg  = self._db.get_keg(keg_id)
                    beer = self._db.get_beer(keg.beer_id) if keg else None
                    keg_beer[keg_id] = beer.name if beer else "—"
                return keg_beer[keg_id]

            for i, (u_lbl, b_lbl, oz_lbl, t_lbl) in enumerate(self._pour_rows):
                if i < len(pours):
                    p = pours[i]
                    u_lbl.setText(users.get(p.user_id, "Unknown"))
                    b_lbl.setText(beer_for(p.keg_id))
                    oz_lbl.setText(f"{p.ounces:.1f}")
                    t_lbl.setText(datetime.fromtimestamp(p.time).strftime("%I:%M %p"))
                else:
                    for lbl in (u_lbl, b_lbl, oz_lbl, t_lbl):
                        lbl.setText("")
        except Exception as exc:
            log.warning("Recent pours refresh error: %s", exc)

    # ------------------------------------------------------------------
    # Sensor slot
    # ------------------------------------------------------------------

    def on_readings_updated(
        self,
        ambient_f: Optional[float],
        humidity:  Optional[float],
    ) -> None:
        parts: list[str] = []
        if ambient_f is not None:
            parts.append(f"{ambient_f:.0f}°F")
        if humidity is not None:
            parts.append(f"{humidity:.0f}% Hum")
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
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        tap_lbl = QLabel((display_name or tap_id).upper())
        tap_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tap_lbl.setStyleSheet(
            f"color: {c.get('muted', '#888')}; font-size: 15px; font-weight: bold; letter-spacing: 2px;"
        )
        layout.addWidget(tap_lbl)

        self._lbl_beer = QLabel("No Keg")
        self._lbl_beer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_beer.setWordWrap(True)
        font = QFont()
        font.setPointSize(20)
        font.setWeight(QFont.Weight.Bold)
        self._lbl_beer.setFont(font)
        layout.addWidget(self._lbl_beer)

        self._lbl_sub = QLabel("")
        self._lbl_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_sub.setStyleSheet(f"color: {c.get('muted', '#888')}; font-size: 15px;")
        self._lbl_sub.setWordWrap(True)
        layout.addWidget(self._lbl_sub)

        layout.addStretch()

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setFixedHeight(28)
        self._bar.setTextVisible(True)
        layout.addWidget(self._bar)

        self._lbl_stats = QLabel("")
        self._lbl_stats.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_stats.setStyleSheet(f"color: {c.get('muted', '#888')}; font-size: 15px;")
        layout.addWidget(self._lbl_stats)

        self._lbl_price = QLabel("")
        self._lbl_price.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_price.setStyleSheet(
            f"color: {c.get('accent', '#e94560')}; font-size: 18px; font-weight: bold;"
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
        self._bar.setFormat(f"{pct}%  ({keg.liters_remaining:.1f} L)")

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
