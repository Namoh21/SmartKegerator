"""
Users window — add/remove users, capture training photos, trigger recognition training.

Layout:
┌─ Users ──────────────────────────────────────────────────────────────┐
│ ┌─ User list ──┐  ┌─ Detail panel ──────────────────────────────────┐│
│ │ Unknown      │  │  Name                          [View History]   ││
│ │ Alice Smith  │  │  ┌─ Photo / Live view (full width) ───────────┐ ││
│ │ Bob Jones    │  │  │  shows training photo or live camera feed   │ ││
│ │              │  │  └────────────────────────────────────────────┘ ││
│ │              │  │  [📷 Capture Photo]   Training Photos: 3        ││
│ │              │  │  pic0.jpg  pic1.jpg  pic2.jpg  [Delete]         ││
│ │              │  │  [Train Recognition]   ✓ 5 encoding(s) stored   ││
│ │              │  │  ─────────────────────────────────────────────  ││
│ │              │  │  Balance Owed:                                  ││
│ │              │  │  $12.50                    [Record Payment]     ││
│ [Register]     │  └─────────────────────────────────────────────────┘│
│ [Delete][Close]│                                                      │
└──────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QFont, QPixmap
from PyQt6.QtWidgets import (
    QDialog, QGridLayout, QHBoxLayout, QInputDialog, QLabel,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

from data.database import Database
from data.models import User, UNKNOWN_USER_ID
from ui.theme import get as _get_theme

log = logging.getLogger(__name__)


def _build_style(c: dict) -> str:
    return f"""
    QDialog, QWidget {{
        background-color: {c['bg']};
        color: {c['text']};
        font-family: 'DejaVu Sans', Arial, sans-serif;
    }}
    QListWidget {{
        background-color: {c['card']};
        border: 1px solid {c['border']};
        border-radius: 4px;
        font-size: 16px;
    }}
    QListWidget::item:selected {{
        background-color: {c['accent']};
        color: white;
    }}
    QListWidget::item:hover {{
        background-color: {c['border']};
    }}
    QPushButton {{
        background-color: {c['card']};
        color: {c['text']};
        border: 1px solid {c['accent']};
        border-radius: 4px;
        padding: 8px 14px;
        font-size: 15px;
    }}
    QPushButton:pressed {{ background-color: {c['accent']}; }}
    QPushButton#danger {{ border-color: {c['warn']}; }}
    QPushButton#train {{
        background-color: {c['ok']};
        color: #111;
        border: none;
        font-weight: bold;
    }}
    QPushButton#live {{
        background-color: {c['accent']};
        color: white;
        border: none;
        font-weight: bold;
    }}
"""


# ---------------------------------------------------------------------------
# Payment numpad dialog
# ---------------------------------------------------------------------------

class _PaymentDialog(QDialog):
    def __init__(self, balance: float, c: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Record Payment")
        self.setMinimumWidth(300)
        self._c      = c
        self._balance = balance
        self._raw    = ""

        self.setStyleSheet(f"""
            QDialog, QWidget {{ background: {c['bg']}; color: {c['text']}; font-family: 'DejaVu Sans', Arial; }}
            QPushButton {{
                background: {c['card']}; color: {c['text']};
                border: 1px solid {c['border']}; border-radius: 4px;
                padding: 12px; font-size: 20px; min-width: 60px;
            }}
            QPushButton:pressed {{ background: {c['accent']}; color: white; }}
            QPushButton#payall {{
                background: {c['ok']}; color: #111; border: none; font-weight: bold; font-size: 16px;
            }}
            QPushButton#ok {{
                background: {c['accent']}; color: white; border: none; font-weight: bold; font-size: 16px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Amount display
        self._display = QLabel("$0.00")
        self._display.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        f = QFont(); f.setPointSize(28); f.setWeight(QFont.Weight.Bold)
        self._display.setFont(f)
        self._display.setStyleSheet(
            f"color: {c['accent']}; background: {c['card']}; "
            f"border: 1px solid {c['border']}; border-radius: 4px; padding: 8px 12px;"
        )
        layout.addWidget(self._display)

        # Pay All
        pay_all = QPushButton(f"Pay All  (${balance:.2f})")
        pay_all.setObjectName("payall")
        pay_all.clicked.connect(lambda: self._set_amount(balance))
        layout.addWidget(pay_all)

        # Number pad
        grid = QGridLayout()
        grid.setSpacing(6)
        pad = [("7","8","9"), ("4","5","6"), ("1","2","3"), (".","0","⌫")]
        for row, row_keys in enumerate(pad):
            for col, key in enumerate(row_keys):
                btn = QPushButton(key)
                btn.clicked.connect(lambda _, k=key: self._press(k))
                grid.addWidget(btn, row, col)
        layout.addLayout(grid)

        # OK / Cancel
        actions = QHBoxLayout()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("OK")
        ok.setObjectName("ok")
        ok.clicked.connect(self._confirm)
        actions.addWidget(cancel)
        actions.addWidget(ok)
        layout.addLayout(actions)

    def _press(self, key: str) -> None:
        if key == "⌫":
            self._raw = self._raw[:-1]
        elif key == ".":
            if "." not in self._raw:
                self._raw += "."
        else:
            # Limit to 2 decimal places
            if "." in self._raw:
                decimals = len(self._raw.split(".")[1])
                if decimals >= 2:
                    return
            self._raw += key
        self._update_display()

    def _set_amount(self, amount: float) -> None:
        self._raw = f"{amount:.2f}"
        self._update_display()

    def _update_display(self) -> None:
        try:
            val = float(self._raw) if self._raw else 0.0
            self._display.setText(f"${val:.2f}")
        except ValueError:
            self._display.setText(f"${self._raw}")

    def _confirm(self) -> None:
        if self.amount <= 0:
            QMessageBox.warning(self, "Invalid", "Enter an amount greater than $0.00.")
            return
        self.accept()

    @property
    def amount(self) -> float:
        try:
            return float(self._raw)
        except (ValueError, TypeError):
            return 0.0


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class UsersWindow(QDialog):
    def __init__(
        self,
        config: dict,
        db: Database,
        recognizer,
        camera,
        parent=None,
        *,
        is_admin: bool = False,
    ) -> None:
        super().__init__(parent)
        self._config     = config
        self._db         = db
        self._recognizer = recognizer
        self._camera     = camera
        self._is_admin   = is_admin
        self._selected_user: Optional[User] = None
        self._live_mode  = False   # True = show live camera; False = show photo

        self._c = _get_theme(config)
        self.setWindowTitle("Users")
        self.setStyleSheet(_build_style(self._c))
        self.setMinimumSize(840, 560)
        self.resize(960, 620)

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        root.addWidget(self._build_user_list(), stretch=1)
        root.addWidget(self._build_detail_panel(), stretch=3)

        if self._recognizer:
            self._recognizer.training_complete.connect(self._on_training_complete)
            self._recognizer.training_failed.connect(self._on_training_failed)

        if self._camera:
            self._camera.frame_ready.connect(self._on_camera_frame)

        self._load_users()

    def closeEvent(self, event):
        if self._camera:
            try:
                self._camera.frame_ready.disconnect(self._on_camera_frame)
            except Exception:
                pass
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Layout — user list panel (narrow)
    # ------------------------------------------------------------------

    def _build_user_list(self) -> QWidget:
        panel  = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        header = QLabel("Users")
        f = QFont(); f.setPointSize(17); f.setWeight(QFont.Weight.Bold)
        header.setFont(f)
        header.setStyleSheet(f"color: {self._c['accent']};")
        layout.addWidget(header)

        self._user_list = QListWidget()
        self._user_list.currentRowChanged.connect(self._on_user_selected)
        layout.addWidget(self._user_list, stretch=1)

        # Register button — full width, top
        reg_btn = QPushButton("Register / Add Me")
        reg_btn.clicked.connect(self._register_user)
        layout.addWidget(reg_btn)

        # Delete + Close on bottom row
        bottom = QHBoxLayout()
        bottom.setSpacing(6)
        if self._is_admin:
            self._del_user_btn = QPushButton("Delete")
            self._del_user_btn.setObjectName("danger")
            self._del_user_btn.clicked.connect(self._delete_user)
            bottom.addWidget(self._del_user_btn)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(close_btn)
        layout.addLayout(bottom)

        return panel

    # ------------------------------------------------------------------
    # Layout — detail panel
    # ------------------------------------------------------------------

    def _build_detail_panel(self) -> QWidget:
        panel  = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Name + history button
        name_row = QHBoxLayout()
        self._lbl_name = QLabel("Select a user")
        f = QFont(); f.setPointSize(18); f.setWeight(QFont.Weight.Bold)
        self._lbl_name.setFont(f)
        name_row.addWidget(self._lbl_name, stretch=1)
        self._history_btn = QPushButton("View History")
        self._history_btn.setEnabled(False)
        self._history_btn.clicked.connect(self._view_history)
        name_row.addWidget(self._history_btn)
        layout.addLayout(name_row)

        if self._is_admin:
            # Image / live view display — full panel width
            self._image_label = QLabel()
            self._image_label.setMinimumHeight(220)
            self._image_label.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )
            self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._image_label.setStyleSheet(
                f"background-color: {self._c['card']}; border: 1px solid {self._c['border']}; "
                f"border-radius: 4px; color: {self._c['muted']};"
            )
            self._image_label.setText("Select a user")
            layout.addWidget(self._image_label, stretch=1)

            # Capture button
            self._capture_btn = QPushButton("📷  Capture Photo")
            self._capture_btn.setEnabled(False)
            self._capture_btn.clicked.connect(self._toggle_capture)
            layout.addWidget(self._capture_btn)

            # Photo list row (compact horizontal)
            photo_row = QHBoxLayout()
            photo_row.setSpacing(6)
            self._photo_list = QListWidget()
            self._photo_list.setFixedHeight(60)
            self._photo_list.setFlow(QListWidget.Flow.LeftToRight)
            self._photo_list.setStyleSheet("font-size: 14px;")
            self._photo_list.currentItemChanged.connect(self._on_photo_selected)
            photo_row.addWidget(self._photo_list, stretch=1)
            self._del_photo_btn = QPushButton("Delete\nPhoto")
            self._del_photo_btn.setObjectName("danger")
            self._del_photo_btn.setFixedWidth(80)
            self._del_photo_btn.clicked.connect(self._delete_photo)
            photo_row.addWidget(self._del_photo_btn)
            layout.addLayout(photo_row)

            # Train row
            train_row = QHBoxLayout()
            self._train_btn = QPushButton("Train Recognition")
            self._train_btn.setObjectName("train")
            self._train_btn.setEnabled(False)
            self._train_btn.clicked.connect(self._train_user)
            train_row.addWidget(self._train_btn)
            self._lbl_train_status = QLabel("")
            self._lbl_train_status.setStyleSheet(f"color: {self._c['muted']}; font-size: 15px;")
            train_row.addWidget(self._lbl_train_status, stretch=1)
            layout.addLayout(train_row)

            # Separator
            sep = QLabel()
            sep.setFixedHeight(1)
            sep.setStyleSheet(f"background: {self._c['border']};")
            layout.addWidget(sep)

            # Balance — two lines
            self._lbl_balance_title = QLabel("Balance Owed:")
            self._lbl_balance_title.setStyleSheet(
                f"color: {self._c['muted']}; font-size: 14px; letter-spacing: 1px;"
            )
            layout.addWidget(self._lbl_balance_title)

            bal_row = QHBoxLayout()
            self._lbl_balance = QLabel("")
            f2 = QFont(); f2.setPointSize(20); f2.setWeight(QFont.Weight.Bold)
            self._lbl_balance.setFont(f2)
            bal_row.addWidget(self._lbl_balance, stretch=1)
            self._payment_btn = QPushButton("Record Payment")
            self._payment_btn.setEnabled(False)
            self._payment_btn.clicked.connect(self._record_payment)
            bal_row.addWidget(self._payment_btn)
            layout.addLayout(bal_row)

        layout.addStretch()
        return panel

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_users(self) -> None:
        self._user_list.clear()
        for user in self._db.get_all_users():
            item = QListWidgetItem(user.name)
            item.setData(Qt.ItemDataRole.UserRole, user.id)
            self._user_list.addItem(item)

    def _on_user_selected(self, row: int) -> None:
        # Exit live mode when switching users
        if self._live_mode:
            self._exit_live_mode()

        if row < 0:
            self._selected_user = None
            self._lbl_name.setText("Select a user")
            self._history_btn.setEnabled(False)
            if self._is_admin:
                self._capture_btn.setEnabled(False)
                self._train_btn.setEnabled(False)
                self._payment_btn.setEnabled(False)
                self._photo_list.clear()
                self._lbl_balance.setText("")
                self._image_label.setText("Select a user")
                self._image_label.setPixmap(QPixmap())
            return

        item    = self._user_list.item(row)
        user_id = item.data(Qt.ItemDataRole.UserRole)
        user    = self._db.get_user(user_id)
        if not user:
            return

        self._selected_user = user
        self._lbl_name.setText(user.name)
        self._history_btn.setEnabled(user.id != UNKNOWN_USER_ID)

        if self._is_admin:
            is_real = user.id != UNKNOWN_USER_ID
            self._capture_btn.setEnabled(is_real)
            self._train_btn.setEnabled(is_real and bool(user.image_paths))
            self._payment_btn.setEnabled(is_real)
            self._refresh_photo_list(user)
            self._refresh_balance(user)
            self._lbl_train_status.setText(
                f"{len(self._db.get_face_encodings_for_user(user.id))} encoding(s) stored"
            )
            self._show_latest_photo(user)

    def _refresh_photo_list(self, user: User) -> None:
        self._photo_list.clear()
        for path in user.image_paths:
            item = QListWidgetItem(Path(path).name)
            item.setData(Qt.ItemDataRole.UserRole, path)
            self._photo_list.addItem(item)
        # Select the last (most recent) photo
        if self._photo_list.count() > 0:
            self._photo_list.setCurrentRow(self._photo_list.count() - 1)

    def _on_photo_selected(self, current, previous) -> None:
        """Show whichever photo is selected in the list (when not in live mode)."""
        if self._live_mode or current is None:
            return
        path = current.data(Qt.ItemDataRole.UserRole)
        self._display_photo_file(path)

    def _show_latest_photo(self, user: User) -> None:
        """Display the most recently captured photo, or placeholder if none."""
        if user.image_paths:
            self._display_photo_file(user.image_paths[-1])
        else:
            self._image_label.setPixmap(QPixmap())
            self._image_label.setText("No photos yet — click Capture Photo")

    def _display_photo_file(self, path: str) -> None:
        px = QPixmap(path)
        if px.isNull():
            self._image_label.setText(f"Cannot load {Path(path).name}")
            return
        scaled = px.scaled(
            self._image_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._image_label.setPixmap(scaled)
        self._image_label.setText("")

    def _refresh_balance(self, user: User) -> None:
        balance = self._db.balance_for_user(user.id)
        color   = self._c['warn'] if balance > 0 else self._c['ok']
        self._lbl_balance.setText(f"${balance:.2f}")
        self._lbl_balance.setStyleSheet(f"color: {color}; font-size: 20px; font-weight: bold;")

    # ------------------------------------------------------------------
    # Camera — live mode toggle
    # ------------------------------------------------------------------

    def _on_camera_frame(self, pixmap: QPixmap) -> None:
        if not self._is_admin or not self._live_mode:
            return
        scaled = pixmap.scaled(
            self._image_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._image_label.setPixmap(scaled)

    def _toggle_capture(self) -> None:
        if not self._selected_user or not self._camera:
            return
        if not self._live_mode:
            self._enter_live_mode()
        else:
            self._do_capture()

    def _enter_live_mode(self) -> None:
        self._live_mode = True
        self._capture_btn.setText("💾  Save Photo")
        self._capture_btn.setObjectName("live")
        self._capture_btn.setStyleSheet("")   # force style refresh
        self._image_label.setText("")

    def _exit_live_mode(self) -> None:
        self._live_mode = False
        self._capture_btn.setText("📷  Capture Photo")
        self._capture_btn.setObjectName("")
        self._capture_btn.setStyleSheet("")

    def _do_capture(self) -> None:
        """Capture a frame from the camera and save it as a training photo."""
        photos_dir = Path(self._config["data"]["user_photos_dir"])
        user_dir   = photos_dir / str(self._selected_user.id)
        user_dir.mkdir(parents=True, exist_ok=True)

        next_id = len(list(user_dir.glob("*.jpg")))
        path    = str(user_dir / f"pic{next_id}.jpg")

        if not self._camera.capture_photo(path):
            QMessageBox.warning(self, "Capture Failed",
                                "Could not capture photo — is the camera running?")
            self._exit_live_mode()
            return

        self._db.add_user_image(self._selected_user.id, path)
        self._selected_user = self._db.get_user(self._selected_user.id)

        self._exit_live_mode()
        self._refresh_photo_list(self._selected_user)
        self._train_btn.setEnabled(True)
        # Show the newly captured photo
        self._display_photo_file(path)
        log.info("Captured photo for user %d: %s", self._selected_user.id, path)

    # ------------------------------------------------------------------
    # User actions
    # ------------------------------------------------------------------

    def _register_user(self) -> None:
        name, ok = QInputDialog.getText(
            self, "Register / Add Me",
            "Enter your name:"
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        existing = [u for u in self._db.get_all_users()
                    if u.name.lower() == name.lower() and u.id != UNKNOWN_USER_ID]
        if existing:
            QMessageBox.warning(self, "Name Taken",
                f"'{name}' is already registered.")
            return
        user = User(id=None, name=name)
        self._db.save_user(user)
        log.info("Registered user: %s (id=%d)", user.name, user.id)
        self._load_users()
        for i in range(self._user_list.count()):
            if self._user_list.item(i).data(Qt.ItemDataRole.UserRole) == user.id:
                self._user_list.setCurrentRow(i)
                break
        QMessageBox.information(self, "Registered!",
            f"Welcome, {user.name}!\n\n"
            + ("Ask an admin to add your photo for face recognition."
               if not self._is_admin else
               "Use the camera panel to capture training photos."))

    def _view_history(self) -> None:
        if not self._selected_user:
            return
        from ui.history_window import HistoryWindow
        w = HistoryWindow(self._config, self._db, self,
                          current_user_id=self._selected_user.id,
                          is_admin=self._is_admin)
        w.exec()

    def _delete_user(self) -> None:
        if not self._selected_user:
            return
        if self._selected_user.id == UNKNOWN_USER_ID:
            QMessageBox.warning(self, "Cannot Delete",
                                "The Unknown user cannot be deleted.")
            return
        result = QMessageBox.question(
            self, "Delete User",
            f"Delete '{self._selected_user.name}'?\n"
            "Pours will remain but be attributed to Unknown.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        self._db.delete_face_encodings_for_user(self._selected_user.id)
        self._db.delete_user(self._selected_user.id)
        log.info("Deleted user %d (%s)", self._selected_user.id, self._selected_user.name)
        if self._recognizer:
            self._recognizer.reload_encodings()
        self._selected_user = None
        self._load_users()

    # ------------------------------------------------------------------
    # Photo management
    # ------------------------------------------------------------------

    def _delete_photo(self) -> None:
        item = self._photo_list.currentItem()
        if not item or not self._selected_user:
            return
        path   = item.data(Qt.ItemDataRole.UserRole)
        result = QMessageBox.question(
            self, "Delete Photo", f"Delete {Path(path).name}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        user = self._selected_user
        user.image_paths = [p for p in user.image_paths if p != path]
        self._db.save_user(user)
        try:
            Path(path).unlink(missing_ok=True)
        except Exception as exc:
            log.warning("Could not delete photo file %s: %s", path, exc)
        self._refresh_photo_list(user)
        self._train_btn.setEnabled(bool(user.image_paths))
        self._show_latest_photo(user)

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def _train_user(self) -> None:
        try:
            if not self._selected_user or not self._recognizer:
                return
            self._train_btn.setEnabled(False)
            self._lbl_train_status.setText("Training…")
            self._lbl_train_status.setStyleSheet(
                f"color: {self._c['warn']}; font-size: 15px;")
            self._recognizer.train_user(self._selected_user.id)
        except Exception as exc:
            log.error("Train user error: %s", exc, exc_info=True)
            self._lbl_train_status.setText(f"✗ {exc}")
            self._lbl_train_status.setStyleSheet(
                f"color: {self._c['warn']}; font-size: 15px;")
            self._train_btn.setEnabled(True)

    def _on_training_complete(self, user_id: int, count: int) -> None:
        if self._selected_user and self._selected_user.id == user_id:
            self._lbl_train_status.setText(f"✓  {count} encoding(s) stored")
            self._lbl_train_status.setStyleSheet(
                f"color: {self._c['ok']}; font-size: 15px;")
            self._train_btn.setEnabled(True)

    def _on_training_failed(self, user_id: int, reason: str) -> None:
        if self._selected_user and self._selected_user.id == user_id:
            self._lbl_train_status.setText(f"✗  {reason}")
            self._lbl_train_status.setStyleSheet(
                f"color: {self._c['warn']}; font-size: 15px;")
            self._train_btn.setEnabled(True)

    # ------------------------------------------------------------------
    # Payments
    # ------------------------------------------------------------------

    def _record_payment(self) -> None:
        if not self._selected_user:
            return
        balance = self._db.balance_for_user(self._selected_user.id)
        dlg     = _PaymentDialog(balance, self._c, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        amount = dlg.amount
        if amount <= 0:
            return
        self._db.add_payment(self._selected_user.id, amount)
        log.info("Recorded payment $%.2f for user %d", amount, self._selected_user.id)
        self._refresh_balance(self._selected_user)
