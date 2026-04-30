"""
Users window — add/remove users, capture training photos, trigger recognition training.

Layout:
┌─ Users ─────────────────────────────────────────────── [Close] ─┐
│  ┌─ User list ────┐  ┌─ Detail panel ──────────────────────────┐ │
│  │ Unknown        │  │  Name: Alice Smith                      │ │
│  │ Alice Smith    │  │                                         │ │
│  │ Sarah Jones    │  │  ┌─ Camera ─────────┐  ┌─ Photos ────┐ │ │
│  │                │  │  │  Live preview    │  │ pic0.jpg    │ │ │
│  │                │  │  │                  │  │ pic1.jpg    │ │ │
│  │                │  │  │                  │  │ pic2.jpg    │ │ │
│  │                │  │  │  [Capture Photo] │  │ [Delete]    │ │ │
│  │                │  │  └──────────────────┘  └─────────────┘ │ │
│  │                │  │                                         │ │
│  │                │  │  [Train Recognition]    Status: Trained │ │
│  │                │  │                                         │ │
│  │  [Add] [Delete]│  │  Balance owed: $12.50     [Add Payment] │ │
│  └────────────────┘  └─────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QPixmap
from PyQt6.QtWidgets import (
    QDialog, QDoubleSpinBox, QHBoxLayout, QInputDialog, QLabel,
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
        font-size: 17px;
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
        padding: 8px 18px;
        font-size: 16px;
    }}
    QPushButton:pressed {{ background-color: {c['accent']}; }}
    QPushButton#danger {{
        border-color: {c['warn']};
    }}
    QPushButton#train {{
        background-color: {c['ok']};
        color: #111;
        border: none;
        font-weight: bold;
    }}
    QDoubleSpinBox {{
        background-color: {c['card']};
        color: {c['text']};
        border: 1px solid {c['border']};
        border-radius: 4px;
        padding: 6px 10px;
        min-width: 110px;
        font-size: 16px;
    }}
"""


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

        self._c = _get_theme(config)
        self.setWindowTitle("Users")
        self.setStyleSheet(_build_style(self._c))
        self.setMinimumSize(820, 540)
        self.resize(900, 580)

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        root.addWidget(self._build_user_list(), stretch=2)
        root.addWidget(self._build_detail_panel(), stretch=5)

        # Connect recognizer feedback while this window is open
        if self._recognizer:
            self._recognizer.training_complete.connect(self._on_training_complete)
            self._recognizer.training_failed.connect(self._on_training_failed)

        # Live camera preview — connect while window is open
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
    # Layout — user list panel
    # ------------------------------------------------------------------

    def _build_user_list(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        header = QLabel("Users")
        f = QFont()
        f.setPointSize(18)
        f.setWeight(QFont.Weight.Bold)
        header.setFont(f)
        header.setStyleSheet(f"color: {self._c['accent']};")
        layout.addWidget(header)

        self._user_list = QListWidget()
        self._user_list.currentRowChanged.connect(self._on_user_selected)
        layout.addWidget(self._user_list, stretch=1)

        btns = QHBoxLayout()

        # Register button — visible to everyone (self-registration, no password needed)
        reg_btn = QPushButton("Register / Add Me")
        reg_btn.clicked.connect(self._register_user)
        btns.addWidget(reg_btn)

        if self._is_admin:
            del_btn = QPushButton("Delete")
            del_btn.setObjectName("danger")
            del_btn.clicked.connect(self._delete_user)
            btns.addWidget(del_btn)

        btns.addStretch()

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btns.addWidget(close_btn)
        layout.addLayout(btns)

        return panel

    # ------------------------------------------------------------------
    # Layout — detail panel
    # ------------------------------------------------------------------

    def _build_detail_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # Name header + history button
        name_row = QHBoxLayout()
        self._lbl_name = QLabel("Select a user")
        f = QFont()
        f.setPointSize(19)
        f.setWeight(QFont.Weight.Bold)
        self._lbl_name.setFont(f)
        name_row.addWidget(self._lbl_name, stretch=1)

        self._history_btn = QPushButton("View History")
        self._history_btn.setEnabled(False)
        self._history_btn.clicked.connect(self._view_history)
        name_row.addWidget(self._history_btn)
        layout.addLayout(name_row)

        # Camera + photo list side by side
        mid = QHBoxLayout()
        mid.setSpacing(10)

        if self._is_admin:
            # Camera column (admin only — for photo capture)
            cam_col = QVBoxLayout()
            self._camera_label = QLabel()
            self._camera_label.setFixedSize(280, 210)
            self._camera_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._camera_label.setStyleSheet(
                f"background-color: {self._c['card']}; border: 1px solid {self._c['border']}; "
                f"border-radius: 4px; color: {self._c['muted']};"
            )
            self._camera_label.setText("No camera")
            cam_col.addWidget(self._camera_label)

            self._capture_btn = QPushButton("📷  Capture Photo")
            self._capture_btn.clicked.connect(self._capture_photo)
            self._capture_btn.setEnabled(False)
            cam_col.addWidget(self._capture_btn)
            cam_col.addStretch()
            mid.addLayout(cam_col)

            # Photo list column (admin only)
            photo_col = QVBoxLayout()
            photo_header = QLabel("Training Photos")
            photo_header.setStyleSheet(f"color: {self._c['muted']}; font-size: 15px; letter-spacing: 1px;")
            photo_col.addWidget(photo_header)

            self._photo_list = QListWidget()
            self._photo_list.setFixedWidth(200)
            self._photo_list.setStyleSheet("font-size: 15px;")
            photo_col.addWidget(self._photo_list, stretch=1)

            del_photo_btn = QPushButton("Delete Photo")
            del_photo_btn.setObjectName("danger")
            del_photo_btn.clicked.connect(self._delete_photo)
            photo_col.addWidget(del_photo_btn)
            mid.addLayout(photo_col)

        layout.addLayout(mid)

        if self._is_admin:
            # Training row (admin only)
            train_row = QHBoxLayout()
            self._train_btn = QPushButton("Train Recognition")
            self._train_btn.setObjectName("train")
            self._train_btn.clicked.connect(self._train_user)
            self._train_btn.setEnabled(False)
            train_row.addWidget(self._train_btn)

            self._lbl_train_status = QLabel("")
            self._lbl_train_status.setStyleSheet(f"color: {self._c['muted']}; font-size: 16px;")
            train_row.addWidget(self._lbl_train_status)
            train_row.addStretch()
            layout.addLayout(train_row)

            # Balance + payment row (admin only)
            bal_row = QHBoxLayout()
            self._lbl_balance = QLabel("")
            self._lbl_balance.setStyleSheet("font-size: 17px;")
            bal_row.addWidget(self._lbl_balance)
            bal_row.addStretch()

            self._payment_spin = QDoubleSpinBox()
            self._payment_spin.setRange(0.01, 999.99)
            self._payment_spin.setValue(5.00)
            self._payment_spin.setPrefix("$")
            self._payment_spin.setDecimals(2)
            bal_row.addWidget(self._payment_spin)

            self._payment_btn = QPushButton("Record Payment")
            self._payment_btn.clicked.connect(self._record_payment)
            self._payment_btn.setEnabled(False)
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
            is_real_user = user.id != UNKNOWN_USER_ID
            self._capture_btn.setEnabled(is_real_user)
            self._train_btn.setEnabled(is_real_user and bool(user.image_paths))
            self._payment_btn.setEnabled(is_real_user)
            self._refresh_photo_list(user)
            self._refresh_balance(user)
            self._lbl_train_status.setText(
                f"{len(self._db.get_face_encodings_for_user(user.id))} encoding(s) stored"
            )

    def _refresh_photo_list(self, user: User) -> None:
        self._photo_list.clear()
        for path in user.image_paths:
            name = Path(path).name
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, path)
            self._photo_list.addItem(item)

    def _refresh_balance(self, user: User) -> None:
        balance = self._db.balance_for_user(user.id)
        color   = self._c['warn'] if balance > 0 else self._c['ok']
        self._lbl_balance.setText(f"Balance owed: ${balance:.2f}")
        self._lbl_balance.setStyleSheet(f"color: {color}; font-size: 17px; font-weight: bold;")  # color set above

    # ------------------------------------------------------------------
    # Camera feed
    # ------------------------------------------------------------------

    def _on_camera_frame(self, pixmap: QPixmap) -> None:
        if not self._is_admin:
            return
        scaled = pixmap.scaled(
            self._camera_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._camera_label.setPixmap(scaled)

    # ------------------------------------------------------------------
    # User actions
    # ------------------------------------------------------------------

    def _register_user(self) -> None:
        """Self-registration — anyone can add themselves (no password needed)."""
        name, ok = QInputDialog.getText(
            self, "Register / Add Me",
            "Enter your name (used for pour tracking and face recognition):"
        )
        if not ok or not name.strip():
            return

        name = name.strip()
        # Check for duplicate name
        existing = [
            u for u in self._db.get_all_users()
            if u.name.lower() == name.lower() and u.id != UNKNOWN_USER_ID
        ]
        if existing:
            QMessageBox.warning(
                self, "Name Taken",
                f"'{name}' is already registered.\n"
                "Choose a different name or ask an admin to update your profile.",
            )
            return

        user = User(id=None, name=name)
        self._db.save_user(user)
        log.info("Registered user: %s (id=%d)", user.name, user.id)
        self._load_users()

        # Select the new user
        for i in range(self._user_list.count()):
            if self._user_list.item(i).data(Qt.ItemDataRole.UserRole) == user.id:
                self._user_list.setCurrentRow(i)
                break

        QMessageBox.information(
            self, "Registered!",
            f"Welcome, {user.name}!\n\n"
            "Ask an admin to add your photo so the kegerator can identify you."
            if not self._is_admin else
            f"Welcome, {user.name}! Use the camera panel to capture training photos.",
        )

    def _view_history(self) -> None:
        if not self._selected_user:
            return
        from ui.history_window import HistoryWindow
        w = HistoryWindow(
            self._config, self._db, self,
            current_user_id=self._selected_user.id,
            is_admin=self._is_admin,
        )
        w.exec()

    def _delete_user(self) -> None:
        if not self._selected_user:
            return
        if self._selected_user.id == UNKNOWN_USER_ID:
            QMessageBox.warning(self, "Cannot Delete", "The Unknown user cannot be deleted.")
            return

        result = QMessageBox.question(
            self, "Delete User",
            f"Delete '{self._selected_user.name}'?\nAll their pours will remain but be attributed to Unknown.",
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

    def _capture_photo(self) -> None:
        if not self._selected_user or not self._camera:
            return

        photos_dir = Path(self._config["data"]["user_photos_dir"])
        user_dir   = photos_dir / str(self._selected_user.id)
        user_dir.mkdir(parents=True, exist_ok=True)

        next_id = len(list(user_dir.glob("*.jpg")))
        path    = str(user_dir / f"pic{next_id}.jpg")

        if not self._camera.capture_photo(path):
            QMessageBox.warning(self, "Capture Failed", "Could not capture photo — is the camera running?")
            return

        self._db.add_user_image(self._selected_user.id, path)

        # Reload user and refresh UI
        self._selected_user = self._db.get_user(self._selected_user.id)
        self._refresh_photo_list(self._selected_user)
        self._train_btn.setEnabled(True)
        log.info("Captured photo for user %d: %s", self._selected_user.id, path)

    def _delete_photo(self) -> None:
        item = self._photo_list.currentItem()
        if not item or not self._selected_user:
            return

        path = item.data(Qt.ItemDataRole.UserRole)
        result = QMessageBox.question(
            self, "Delete Photo",
            f"Delete {Path(path).name}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return

        # Remove from DB and optionally from disk
        user = self._selected_user
        new_paths = [p for p in user.image_paths if p != path]
        user.image_paths = new_paths
        self._db.save_user(user)

        try:
            Path(path).unlink(missing_ok=True)
        except Exception as exc:
            log.warning("Could not delete photo file %s: %s", path, exc)

        self._refresh_photo_list(user)
        self._train_btn.setEnabled(bool(new_paths))

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def _train_user(self) -> None:
        try:
            if not self._selected_user or not self._recognizer:
                return
            self._train_btn.setEnabled(False)
            self._lbl_train_status.setText("Training…")
            self._lbl_train_status.setStyleSheet(f"color: {self._c['warn']}; font-size: 16px;")
            self._recognizer.train_user(self._selected_user.id)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error("Train user error: %s", exc, exc_info=True)
            self._lbl_train_status.setText(f"✗  Error: {exc}")
            self._lbl_train_status.setStyleSheet(f"color: {self._c['warn']}; font-size: 16px;")
            self._train_btn.setEnabled(True)

    def _on_training_complete(self, user_id: int, count: int) -> None:
        if self._selected_user and self._selected_user.id == user_id:
            self._lbl_train_status.setText(f"✓  {count} encoding(s) stored")
            self._lbl_train_status.setStyleSheet(f"color: {self._c['ok']}; font-size: 16px;")
            self._train_btn.setEnabled(True)

    def _on_training_failed(self, user_id: int, reason: str) -> None:
        if self._selected_user and self._selected_user.id == user_id:
            self._lbl_train_status.setText(f"✗  {reason}")
            self._lbl_train_status.setStyleSheet(f"color: {self._c['warn']}; font-size: 16px;")
            self._train_btn.setEnabled(True)

    # ------------------------------------------------------------------
    # Payments
    # ------------------------------------------------------------------

    def _record_payment(self) -> None:
        if not self._selected_user:
            return
        amount  = self._payment_spin.value()
        payment = self._db.add_payment(self._selected_user.id, amount)
        log.info("Recorded payment $%.2f for user %d", amount, self._selected_user.id)
        self._refresh_balance(self._selected_user)
