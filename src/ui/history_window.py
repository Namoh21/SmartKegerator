"""
History window — pour log with filters, summary stats, and a bar graph.

Opens as a modal dialog over the main window.

Filters:
  • User   — All Users or a specific user
  • Period — Last 7 days / 30 days / 90 days / All Time

Table columns: Date · Time · User · Beer · Amount · Price

Bar graph: oz poured per day over the selected period (PyQtGraph).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel,
    QPushButton, QSizePolicy, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from data.database import Database
from data.models import Pour, User
from ui.theme import get as _get_theme

log = logging.getLogger(__name__)

_PG_AVAILABLE = False
try:
    import pyqtgraph as pg
    _PG_AVAILABLE = True
except ImportError:
    log.warning("pyqtgraph not available — history graph will be hidden")


def _build_style(c: dict) -> str:
    return f"""
    QDialog, QWidget {{
        background-color: {c['bg']};
        color: {c['text']};
        font-family: 'DejaVu Sans', Arial, sans-serif;
    }}
    QTableWidget {{
        background-color: {_CARD_BG};
        alternate-background-color: #1e1e3a;
        gridline-color: #2a2a4e;
        border: 1px solid {c['border']};
        border-radius: 4px;
    }}
    QTableWidget::item:selected {{
        background-color: {c['accent']};
    }}
    QHeaderView::section {{
        background-color: {c['deep']};
        color: {c['muted']};
        padding: 8px;
        border: none;
        font-size: 15px;
        letter-spacing: 1px;
    }}
    QComboBox {{
        background-color: {c['card']};
        color: {c['text']};
        border: 1px solid {c['border']};
        border-radius: 4px;
        padding: 6px 12px;
        min-width: 140px;
        font-size: 15px;
    }}
    QComboBox::drop-down {{ border: none; }}
    QPushButton {{
        background-color: {c['card']};
        color: {c['text']};
        border: 1px solid {c['accent']};
        border-radius: 4px;
        padding: 8px 20px;
        font-size: 16px;
    }}
    QPushButton:pressed {{ background-color: {c['accent']}; }}
"""

_PERIODS = {
    "Last 7 days":  7,
    "Last 30 days": 30,
    "Last 90 days": 90,
    "All time":     None,
}


class HistoryWindow(QDialog):
    def __init__(
        self,
        config: dict,
        db: Database,
        parent=None,
        *,
        current_user_id: Optional[int] = None,
        is_admin: bool = False,
    ) -> None:
        super().__init__(parent)
        self._config          = config
        self._db              = db
        self._current_user_id = current_user_id
        self._is_admin        = is_admin
        self._users: dict[int, str] = {}
        self._c               = _get_theme(config)

        title = "Pour History" if is_admin else "My Pour History"
        self.setWindowTitle(title)
        self.setStyleSheet(_build_style(self._c))
        if _PG_AVAILABLE:
            pg.setConfigOption("background", self._c['bg'])
            pg.setConfigOption("foreground", self._c['text'])
        self.setMinimumSize(860, 560)
        self.resize(960, 620)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        root.addWidget(self._build_header(title))
        if is_admin:
            root.addWidget(self._build_filter_bar())
        root.addWidget(self._build_summary_bar())
        root.addLayout(self._build_body(), stretch=1)

        self._load_users()
        self._refresh()

    # ------------------------------------------------------------------
    # Layout builders
    # ------------------------------------------------------------------

    def _build_header(self, title_text: str = "Pour History") -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(56)
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)

        title = QLabel(title_text)
        f = QFont()
        f.setPointSize(20)
        f.setWeight(QFont.Weight.Bold)
        title.setFont(f)
        title.setStyleSheet(f"color: {self._c['accent']};")
        row.addWidget(title)

        row.addStretch()

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        row.addWidget(close_btn)

        return bar

    def _build_filter_bar(self) -> QWidget:
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        row.addWidget(QLabel("User:"))
        self._combo_user = QComboBox()
        self._combo_user.addItem("All Users", userData=None)
        self._combo_user.currentIndexChanged.connect(self._refresh)
        row.addWidget(self._combo_user)

        row.addWidget(QLabel("Period:"))
        self._combo_period = QComboBox()
        for label in _PERIODS:
            self._combo_period.addItem(label)
        self._combo_period.setCurrentText("Last 30 days")
        self._combo_period.currentIndexChanged.connect(self._refresh)
        row.addWidget(self._combo_period)

        row.addStretch()
        return bar

    def _build_summary_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(46)
        row = QHBoxLayout(bar)
        row.setContentsMargins(4, 0, 4, 0)
        row.setSpacing(30)

        tc = self._c['text']
        self._lbl_count   = _stat_label("Pours", "0", tc)
        self._lbl_oz      = _stat_label("Total oz", "0.0", tc)
        self._lbl_spent   = _stat_label("Total", "$0.00", tc)
        self._lbl_balance = _stat_label("Balance", "$0.00", tc)

        for w in (self._lbl_count, self._lbl_oz, self._lbl_spent, self._lbl_balance):
            row.addWidget(w)

        row.addStretch()
        return bar

    def _build_body(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        row.addWidget(self._build_table(), stretch=3)

        if _PG_AVAILABLE:
            row.addWidget(self._build_graph(), stretch=2)

        return row

    def _build_table(self) -> QTableWidget:
        cols = ["Date", "Time", "User", "Beer", "Amount", "Price"]
        self._table = QTableWidget(0, len(cols))
        self._table.setHorizontalHeaderLabels(cols)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        return self._table

    def _build_graph(self) -> QWidget:
        self._plot = pg.PlotWidget(title="oz poured per day")
        self._plot.setLabel("left",   "Ounces")
        self._plot.setLabel("bottom", "Day")
        self._plot.showGrid(y=True, alpha=0.3)
        self._plot.setMinimumWidth(220)
        return self._plot

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_users(self) -> None:
        users = self._db.get_all_users()
        self._users = {u.id: u.name for u in users}
        if self._is_admin:
            for u in users:
                if u.id == -1:
                    continue
                self._combo_user.addItem(u.name, userData=u.id)

    def _refresh(self) -> None:
        # -- Filters --
        # Admins use the combo box; standard users are locked to their own pours
        if self._is_admin:
            user_id = self._combo_user.currentData()
            period  = _PERIODS[self._combo_period.currentText()]
        else:
            user_id = self._current_user_id
            period  = _PERIODS[self._combo_period.currentText()]

        since = (time.time() - period * 86400) if period else 0.0

        pours = self._db.get_pours_since(since)
        if user_id is not None:
            pours = [p for p in pours if p.user_id == user_id]

        # Enrich with beer names (cache keg→beer lookups)
        keg_beer: dict[int, str] = {}
        for p in pours:
            if p.keg_id not in keg_beer:
                keg = self._db.get_keg(p.keg_id)
                if keg:
                    beer = self._db.get_beer(keg.beer_id)
                    keg_beer[p.keg_id] = beer.name if beer else "Unknown"
                else:
                    keg_beer[p.keg_id] = "Unknown"

        # -- Summary --
        total_oz    = sum(p.ounces for p in pours)
        total_price = sum(p.price  for p in pours)

        balance_label = ""
        if user_id is not None:
            payments = sum(pay.amount for pay in self._db.get_payments_for_user(user_id))
            balance  = total_price - payments
            balance_label = f"${balance:+.2f}"
        else:
            balance_label = "—"

        self._lbl_count.setText(f"Pours: {len(pours)}")
        self._lbl_oz.setText(f"Total: {total_oz:.1f} oz")
        self._lbl_spent.setText(f"Charged: ${total_price:.2f}")
        self._lbl_balance.setText(f"Balance: {balance_label}")

        # -- Table --
        self._table.setRowCount(0)
        for pour in reversed(pours):   # newest first
            row = self._table.rowCount()
            self._table.insertRow(row)

            dt       = pour.poured_at
            username = self._users.get(pour.user_id, "Unknown")
            beer     = keg_beer.get(pour.keg_id, "Unknown")

            cells = [
                dt.strftime("%Y-%m-%d"),
                dt.strftime("%H:%M"),
                username,
                beer,
                f"{pour.ounces:.1f} oz",
                f"${pour.price:.2f}",
            ]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setTextAlignment(
                    int(Qt.AlignmentFlag.AlignCenter)
                    if col in (0, 1, 4, 5)
                    else int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                )
                self._table.setItem(row, col, item)

        # -- Graph --
        if _PG_AVAILABLE:
            self._update_graph(pours, period)

    def _update_graph(self, pours: list[Pour], period: Optional[int]) -> None:
        self._plot.clear()
        if not pours:
            return

        days = period or 30
        now  = datetime.now()

        # Bucket pours by day index (0 = oldest)
        buckets: dict[int, float] = {}
        for pour in pours:
            dt      = pour.poured_at
            day_idx = (now.date() - dt.date()).days
            if day_idx < days:
                buckets[days - 1 - day_idx] = buckets.get(days - 1 - day_idx, 0.0) + pour.ounces

        if not buckets:
            return

        x = list(range(days))
        y = [buckets.get(i, 0.0) for i in x]

        bar = pg.BarGraphItem(x=x, height=y, width=0.7, brush=self._c['accent'])
        self._plot.addItem(bar)
        self._plot.setXRange(-0.5, days - 0.5)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stat_label(title: str, value: str, text_color: str = "#eaeaea") -> QLabel:
    lbl = QLabel(f"{title}: {value}")
    lbl.setStyleSheet(f"color: {text_color}; font-size: 17px;")
    return lbl
