"""
catalog.beer search dialog for the PyQt6 touchscreen app.

Opens when the user taps "Search Beer Database" in the beer/keg management screen.
Reads API credentials from the database (never from source code).
Returns a pre-filled Beer dataclass on accept.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PyQt6.QtGui import QFont, QPixmap
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from data.database import Database
from data.models import Beer

log = logging.getLogger(__name__)

_DARK_BG = "#1a1a2e"
_CARD_BG = "#16213e"
_ACCENT  = "#e94560"
_TEXT    = "#eaeaea"
_MUTED   = "#8888aa"

_STYLE = f"""
    QDialog, QWidget {{
        background-color: {_DARK_BG};
        color: {_TEXT};
        font-family: 'DejaVu Sans', Arial, sans-serif;
    }}
    QLineEdit {{
        background-color: {_CARD_BG};
        color: {_TEXT};
        border: 1px solid #2a2a4e;
        border-radius: 4px;
        padding: 8px 12px;
        font-size: 15px;
    }}
    QListWidget {{
        background-color: {_CARD_BG};
        border: 1px solid #2a2a4e;
        border-radius: 4px;
        font-size: 13px;
    }}
    QListWidget::item {{
        padding: 10px 8px;
        border-bottom: 1px solid #2a2a4e;
    }}
    QListWidget::item:selected {{
        background-color: {_ACCENT};
        color: #fff;
    }}
    QPushButton {{
        border-radius: 4px;
        padding: 8px 18px;
        font-size: 13px;
    }}
    QPushButton#btn-select {{
        background-color: {_ACCENT};
        color: #fff;
        border: none;
    }}
    QPushButton#btn-cancel {{
        background-color: {_CARD_BG};
        color: {_TEXT};
        border: 1px solid #2a2a4e;
    }}
"""


class BeerSearchDialog(QDialog):
    """
    Modal dialog that searches catalog.beer and returns a Beer instance.

    Usage:
        dlg = BeerSearchDialog(db, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            beer = dlg.selected_beer   # pre-filled Beer(id=None, ...)
    """

    def __init__(self, db: Database, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._db   = db
        self._nam  = QNetworkAccessManager(self)
        self._reply: Optional[QNetworkReply] = None
        self._results: list[dict] = []
        self.selected_beer: Optional[Beer] = None

        self.setWindowTitle("Search Beer Database")
        self.setStyleSheet(_STYLE)
        self.setMinimumSize(520, 480)

        self._build_ui()
        self._check_credentials()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.setContentsMargins(16, 16, 16, 16)

        # Title
        title = QLabel("Search Untappd")
        title.setFont(QFont("DejaVu Sans", 16, QFont.Weight.Bold))
        lay.addWidget(title)

        # Status label (credentials warning, search state)
        self._status = QLabel("")
        self._status.setStyleSheet(f"color: {_MUTED}; font-size: 12px;")
        self._status.setWordWrap(True)
        lay.addWidget(self._status)

        # Search box
        self._search = QLineEdit()
        self._search.setPlaceholderText("Type a beer name…")
        self._search.textChanged.connect(self._on_text_changed)
        lay.addWidget(self._search)

        # Debounce timer
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(450)
        self._timer.timeout.connect(self._do_search)

        # Results list
        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(self._accept_selection)
        lay.addWidget(self._list)

        # Buttons
        btn_row = QHBoxLayout()
        self._btn_select = QPushButton("Select Beer")
        self._btn_select.setObjectName("btn-select")
        self._btn_select.setEnabled(False)
        self._btn_select.clicked.connect(self._accept_selection)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setObjectName("btn-cancel")
        btn_cancel.clicked.connect(self.reject)

        btn_row.addWidget(btn_cancel)
        btn_row.addStretch()
        btn_row.addWidget(self._btn_select)
        lay.addLayout(btn_row)

        self._list.itemSelectionChanged.connect(
            lambda: self._btn_select.setEnabled(bool(self._list.selectedItems()))
        )

    # ------------------------------------------------------------------
    # Credential check
    # ------------------------------------------------------------------

    def _check_credentials(self) -> None:
        cid    = self._db.get_setting("untappd_client_id")
        secret = self._db.get_setting("untappd_client_secret")
        if not cid or not secret:
            self._status.setText(
                "⚠  Untappd credentials not configured.\n"
                "Go to the web interface → Settings to add them."
            )
            self._search.setEnabled(False)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def _on_text_changed(self, text: str) -> None:
        self._timer.stop()
        if len(text.strip()) >= 2:
            self._timer.start()
        else:
            self._list.clear()
            self._results.clear()

    def _do_search(self) -> None:
        query  = self._search.text().strip()
        cid    = self._db.get_setting("untappd_client_id")
        secret = self._db.get_setting("untappd_client_secret")

        if not cid or not secret or not query:
            return

        if self._reply and self._reply.isRunning():
            self._reply.abort()

        url = QUrl(
            f"https://api.untappd.com/v4/search/beer"
            f"?q={QUrl.toPercentEncoding(query).data().decode()}"
            f"&client_id={cid}&client_secret={secret}&limit=10"
        )
        req = QNetworkRequest(url)
        req.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, "SmartKegerator/1.0")
        self._status.setText("Searching…")
        self._reply = self._nam.get(req)
        self._reply.finished.connect(self._on_reply)

    def _on_reply(self) -> None:
        reply = self._reply
        if reply.error() != QNetworkReply.NetworkError.NoError:
            self._status.setText(f"Network error: {reply.errorString()}")
            return

        try:
            data  = json.loads(reply.readAll().data())
            items = data["response"]["beers"]["items"]
        except Exception as e:
            self._status.setText(f"Parse error: {e}")
            return

        self._results = items
        self._list.clear()

        if not items:
            self._status.setText("No results found.")
            return

        self._status.setText(f"{len(items)} results")

        for item in items:
            beer    = item["beer"]
            brewery = item["brewery"]
            label   = QListWidgetItem()

            name    = beer["beer_name"]
            company = brewery["brewery_name"]
            style   = beer["beer_style"]
            abv     = beer["beer_abv"]
            rating  = beer.get("rating_score", 0)

            label.setText(
                f"{name}\n"
                f"{company}  ·  {style}  ·  {abv:.1f}% ABV"
                + (f"  ·  ★ {rating:.2f}" if rating else "")
            )
            label.setData(Qt.ItemDataRole.UserRole, item)
            self._list.addItem(label)

    # ------------------------------------------------------------------
    # Accept
    # ------------------------------------------------------------------

    def _accept_selection(self) -> None:
        items = self._list.selectedItems()
        if not items:
            return

        item_data = items[0].data(Qt.ItemDataRole.UserRole)
        beer_data = item_data["beer"]
        brew_data = item_data["brewery"]
        loc       = brew_data.get("location", {})

        self.selected_beer = Beer(
            id=None,
            name=beer_data["beer_name"],
            company=brew_data["brewery_name"],
            location=f"{loc.get('brewery_city', '')}, {loc.get('country_name', '')}".strip(", "),
            style=beer_data["beer_style"],
            abv=beer_data["beer_abv"],
            ibu=int(beer_data.get("beer_ibu", 0) or 0),
            description=beer_data.get("beer_description", ""),
            untappd_id=beer_data.get("bid"),
            untappd_rating=beer_data.get("rating_score") or None,
            label_url=beer_data.get("beer_label", ""),
        )
        self.accept()
