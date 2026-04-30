"""
PIN login dialog — touchscreen fallback for face recognition.

Shows a list of admin names; after selecting one, a compact numeric
PIN pad is displayed with OK / Cancel buttons to the right.

Admins set their PIN through the web Settings → Administrators page.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QGridLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QSizePolicy, QStackedWidget,
    QVBoxLayout, QWidget,
)

from data.database import Database
from ui.theme import get as _get_theme


class PinLoginDialog(QDialog):
    """Two-step modal: pick your name → enter PIN."""

    def __init__(self, config: dict, db: Database, parent=None) -> None:
        super().__init__(parent)
        self._db     = db
        self._c      = _get_theme(config)
        self._admins = db.get_all_admins()
        self._selected: Optional[dict] = None
        self._pin    = ""
        self._auth_user_id: Optional[int]  = None
        self._auth_admin:   Optional[dict] = None

        self.setWindowTitle("Admin Login")
        self.setModal(True)
        self.setMinimumSize(400, 360)
        self.setStyleSheet(self._style())

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_select_page())
        self._stack.addWidget(self._build_pin_page())

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.addWidget(self._stack)

    # ── Stylesheet ───────────────────────────────────────────────────

    def _style(self) -> str:
        c = self._c
        return f"""
        QDialog, QWidget {{
            background: {c['bg']};
            color: {c['text']};
            font-family: 'DejaVu Sans', Arial, sans-serif;
        }}
        QPushButton {{
            background: {c['card']};
            color: {c['text']};
            border: 1px solid {c['border']};
            border-radius: 6px;
            padding: 8px;
            font-size: 18px;
        }}
        QPushButton:pressed {{ background: {c['accent']}; color: {c['bg']}; }}
        QPushButton#admin   {{ font-size: 20px; min-height: 54px; }}
        QPushButton#digit   {{
            font-size: 20px;
            min-width: 58px; max-width: 70px;
            min-height: 50px; max-height: 60px;
        }}
        QPushButton#ok      {{
            background: {c['accent']}; color: {c['bg']};
            border-color: {c['accent']}; font-size: 18px;
            min-width: 72px; min-height: 50px;
        }}
        QPushButton#back    {{
            background: transparent; color: {c['muted']};
            border: none; font-size: 15px; padding: 2px 6px;
        }}
        QPushButton#cancel  {{
            background: transparent; color: {c['muted']};
            border: 1px solid {c['muted']}; font-size: 16px;
            min-width: 72px; min-height: 50px;
        }}
        QScrollArea {{ border: none; }}
        """

    # ── Page 1: select admin ─────────────────────────────────────────

    def _build_select_page(self) -> QWidget:
        page   = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)

        hdr = QLabel("Who are you?")
        hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hdr.setStyleSheet(f"color: {self._c['muted']}; font-size: 18px; padding: 6px;")
        layout.addWidget(hdr)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner  = QWidget()
        vbox   = QVBoxLayout(inner)
        vbox.setSpacing(8)
        vbox.setContentsMargins(4, 4, 4, 4)
        for admin in self._admins:
            label = admin.get("display_name") or admin["username"]
            btn   = QPushButton(label)
            btn.setObjectName("admin")
            btn.clicked.connect(lambda _, a=admin: self._select_admin(a))
            vbox.addWidget(btn)
        vbox.addStretch()
        scroll.setWidget(inner)
        layout.addWidget(scroll)

        cancel = QPushButton("Cancel")
        cancel.setObjectName("cancel")
        cancel.clicked.connect(self.reject)
        layout.addWidget(cancel)
        return page

    def _select_admin(self, admin: dict) -> None:
        self._selected = admin
        self._pin      = ""
        self._lbl_who.setText(admin.get("display_name") or admin["username"])
        self._lbl_error.clear()
        self._refresh_dots()
        self._stack.setCurrentIndex(1)

    # ── Page 2: PIN pad ──────────────────────────────────────────────

    def _build_pin_page(self) -> QWidget:
        page   = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(6)
        layout.setContentsMargins(0, 0, 0, 0)

        # ── Header: back button + name ──
        top  = QHBoxLayout()
        back = QPushButton("← Back")
        back.setObjectName("back")
        back.clicked.connect(lambda: self._stack.setCurrentIndex(0))
        top.addWidget(back)
        top.addStretch()
        self._lbl_who = QLabel("")
        self._lbl_who.setStyleSheet(
            f"color: {self._c['accent']}; font-size: 18px; font-weight: bold;"
        )
        top.addWidget(self._lbl_who)
        layout.addLayout(top)

        # ── PIN dots ──
        self._lbl_dots = QLabel()
        self._lbl_dots.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_dots.setStyleSheet(
            f"color: {self._c['muted']}; font-size: 26px; letter-spacing: 8px; padding: 4px;"
        )
        layout.addWidget(self._lbl_dots)
        self._refresh_dots()

        # ── Error label ──
        self._lbl_error = QLabel("")
        self._lbl_error.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_error.setStyleSheet(f"color: {self._c['warn']}; font-size: 13px;")
        self._lbl_error.setWordWrap(True)
        self._lbl_error.setFixedHeight(36)
        layout.addWidget(self._lbl_error)

        # ── Numpad (left) + OK/Cancel (right) ──
        pad_row = QHBoxLayout()
        pad_row.setSpacing(10)

        # 3×4 digit grid: 1-9 on rows 0-2, ⌫ and 0 on row 3
        grid = QGridLayout()
        grid.setSpacing(6)
        for i, key in enumerate(["1","2","3","4","5","6","7","8","9","⌫","0"]):
            btn = QPushButton(key)
            btn.setObjectName("digit")
            btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            btn.clicked.connect(lambda _, k=key: self._tap(k))
            grid.addWidget(btn, i // 3, i % 3)
        pad_row.addLayout(grid)

        # OK + Cancel stacked on the right
        side = QVBoxLayout()
        side.setSpacing(6)

        ok_btn = QPushButton("OK")
        ok_btn.setObjectName("ok")
        ok_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        ok_btn.clicked.connect(lambda: self._tap("✓"))
        side.addWidget(ok_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("cancel")
        cancel_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        cancel_btn.clicked.connect(self.reject)
        side.addWidget(cancel_btn)

        side.addStretch()
        pad_row.addLayout(side)
        pad_row.addStretch()

        layout.addLayout(pad_row)
        layout.addStretch()
        return page

    # ── PIN logic ────────────────────────────────────────────────────

    def _refresh_dots(self) -> None:
        n      = len(self._pin)
        filled = "●" * n
        empty  = "○" * max(4 - n, 0)
        self._lbl_dots.setText("  ".join(filled + empty))

    def _tap(self, key: str) -> None:
        if key == "⌫":
            self._pin = self._pin[:-1]
            self._lbl_error.clear()
        elif key == "✓":
            self._check_pin()
            return
        elif len(self._pin) < 6:
            self._pin += key
        self._refresh_dots()

    def _check_pin(self) -> None:
        if not self._selected or not self._pin:
            return
        stored = (self._selected.get("pin_hash") or "").strip()
        if not stored:
            self._lbl_error.setText(
                "No PIN set — use web Settings → Administrators to set one."
            )
            self._pin = ""
            self._refresh_dots()
            return
        from web.auth import verify_password
        if verify_password(self._pin, stored):
            self._auth_user_id = self._selected.get("user_id")
            self._auth_admin   = self._selected
            self.accept()
        else:
            self._lbl_error.setText("Incorrect PIN — try again.")
            self._pin = ""
            self._refresh_dots()

    # ── Result accessors ─────────────────────────────────────────────

    def authenticated_user_id(self) -> Optional[int]:
        return self._auth_user_id

    def authenticated_admin(self) -> Optional[dict]:
        return self._auth_admin
