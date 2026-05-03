"""
Keg management window — touchscreen interface for adding, editing,
deleting kegs and assigning them to taps.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout,
    QInputDialog, QLabel, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QSizePolicy, QSpinBox, QVBoxLayout, QWidget,
)

from data.database import Database
from data.models import Keg
from ui.theme import get as _get_theme

log = logging.getLogger(__name__)


def _style(c: dict) -> str:
    return f"""
        QDialog, QWidget {{ background:{c['bg']}; color:{c['fg']}; font-size:14px; }}
        QListWidget {{ background:{c['card']}; border:1px solid {c['border']};
                       border-radius:6px; color:{c['fg']}; font-size:14px; }}
        QListWidget::item:selected {{ background:{c['accent']}; color:#fff; border-radius:4px; }}
        QPushButton {{ background:{c['card']}; color:{c['fg']}; border:1px solid {c['border']};
                       border-radius:6px; padding:8px 14px; font-size:13px; }}
        QPushButton:pressed {{ background:{c['border']}; }}
        QPushButton#accent {{ background:{c['accent']}; color:#fff; border:none; }}
        QPushButton#danger {{ background:#c0392b; color:#fff; border:none; }}
        QComboBox, QDoubleSpinBox, QSpinBox {{
            background:{c['card']}; color:{c['fg']}; border:1px solid {c['border']};
            border-radius:4px; padding:6px; font-size:13px; }}
        QLabel {{ color:{c['fg']}; }}
        QLabel#muted {{ color:{c['muted']}; font-size:12px; }}
    """


class _KegDialog(QDialog):
    """Add / Edit keg form."""

    def __init__(self, config: dict, db: Database, keg: Optional[Keg] = None,
                 parent=None) -> None:
        super().__init__(parent)
        self._db  = db
        self._keg = keg
        c = _get_theme(config)
        self.setStyleSheet(_style(c))
        self.setWindowTitle("Edit Keg" if keg else "Add Keg")
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        form = QFormLayout()
        form.setSpacing(10)

        # Beer selector
        self._beer_combo = QComboBox()
        beers = db.get_all_beers()
        self._beer_ids: list[int] = []
        for b in beers:
            self._beer_combo.addItem(f"{b.name}" + (f"  ({b.company})" if b.company else ""))
            self._beer_ids.append(b.id)
        if keg and keg.beer_id in self._beer_ids:
            self._beer_combo.setCurrentIndex(self._beer_ids.index(keg.beer_id))
        form.addRow("Beer:", self._beer_combo)

        # Capacity
        self._capacity = QDoubleSpinBox()
        self._capacity.setRange(1.0, 200.0)
        self._capacity.setSingleStep(0.5)
        self._capacity.setSuffix(" L")
        self._capacity.setDecimals(1)
        self._capacity.setValue(keg.liters_capacity if keg else 19.5)
        form.addRow("Capacity:", self._capacity)

        # Price
        self._price = QDoubleSpinBox()
        self._price.setRange(0.0, 9999.0)
        self._price.setSingleStep(5.0)
        self._price.setPrefix("$ ")
        self._price.setDecimals(2)
        self._price.setValue(keg.price if keg else 0.0)
        form.addRow("Cost:", self._price)

        layout.addLayout(form)

        # Buttons
        btns = QHBoxLayout()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.setObjectName("accent")
        save.clicked.connect(self._save)
        btns.addWidget(cancel)
        btns.addWidget(save)
        layout.addLayout(btns)

    def _save(self) -> None:
        if not self._beer_ids:
            QMessageBox.warning(self, "No Beers", "Add a beer first via the web interface.")
            return
        idx = self._beer_combo.currentIndex()
        if idx < 0:
            return
        beer_id  = self._beer_ids[idx]
        capacity = self._capacity.value()
        price    = self._price.value()

        if self._keg and self._keg.id:
            self._keg.beer_id          = beer_id
            self._keg.liters_capacity  = capacity
            self._keg.price            = price
            self._db.save_keg(self._keg)
            log.info("Updated keg id=%d", self._keg.id)
        else:
            keg = Keg(
                id=None, beer_id=beer_id,
                date_bought=datetime.now(),
                liters_capacity=capacity,
                price=price,
                warmest_temp=0.0,
            )
            self._db.save_keg(keg)
            log.info("Created keg beer_id=%d capacity=%.1fL", beer_id, capacity)
        self.accept()


class KegsWindow(QDialog):
    """Touchscreen keg management: list, add, edit, delete, assign to tap."""

    def __init__(self, config: dict, db: Database, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._db     = db
        self._c      = _get_theme(config)
        self.setWindowTitle("Keg Management")
        self.setStyleSheet(_style(self._c))
        self.setMinimumSize(560, 480)

        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(12, 12, 12, 12)

        # Title
        title = QLabel("Keg Management")
        title.setStyleSheet(f"font-size:20px;font-weight:bold;color:{self._c['accent']};")
        root.addWidget(title)

        # Keg list
        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._on_select)
        root.addWidget(self._list, stretch=1)

        # Detail row
        self._detail_lbl = QLabel("")
        self._detail_lbl.setObjectName("muted")
        self._detail_lbl.setWordWrap(True)
        root.addWidget(self._detail_lbl)

        # Tap assignment row
        tap_row = QHBoxLayout()
        tap_lbl = QLabel("Assign to tap:")
        tap_lbl.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        tap_row.addWidget(tap_lbl)
        self._tap_combo = QComboBox()
        tap_row.addWidget(self._tap_combo, stretch=1)
        assign_btn = QPushButton("Assign")
        assign_btn.setObjectName("accent")
        assign_btn.clicked.connect(self._assign_tap)
        tap_row.addWidget(assign_btn)
        root.addLayout(tap_row)

        # Action buttons
        btns = QHBoxLayout()
        add_btn = QPushButton("Add Keg")
        add_btn.setObjectName("accent")
        add_btn.clicked.connect(self._add_keg)

        self._edit_btn = QPushButton("Edit")
        self._edit_btn.clicked.connect(self._edit_keg)
        self._edit_btn.setEnabled(False)

        self._del_btn = QPushButton("Delete")
        self._del_btn.setObjectName("danger")
        self._del_btn.clicked.connect(self._delete_keg)
        self._del_btn.setEnabled(False)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)

        btns.addWidget(add_btn)
        btns.addWidget(self._edit_btn)
        btns.addWidget(self._del_btn)
        btns.addStretch()
        btns.addWidget(close_btn)
        root.addLayout(btns)

        self._load()

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load(self) -> None:
        self._kegs: list[Keg] = self._db.get_all_kegs()
        self._list.clear()

        # Build tap list from config
        cfg_taps  = self._config.get("taps", {})
        tap_count = int(cfg_taps.get("count", 3))
        self._taps: list[tuple[str, str]] = []   # (tap_key, display_name)
        for i in range(1, tap_count + 1):
            key  = f"tap{i}"
            name = cfg_taps.get(key, {}).get("name", f"Tap {i}")
            self._taps.append((key, name))

        # Map tap_key → keg_id from DB
        assignments = self._db.get_tap_assignments()
        self._tap_assignments: dict[str, int] = {
            k: v for k, v in assignments.taps.items() if v is not None
        }

        # Map keg_id → tap display name for list labels
        keg_to_tap: dict[int, str] = {}
        for tap_key, keg_id in self._tap_assignments.items():
            tap_name = next((n for k, n in self._taps if k == tap_key), tap_key)
            keg_to_tap[keg_id] = tap_name

        for keg in self._kegs:
            beer = self._db.get_beer(keg.beer_id)
            beer_name = beer.name if beer else "Unknown Beer"
            tap_info  = f" → {keg_to_tap[keg.id]}" if keg.id in keg_to_tap else ""
            pct       = int(keg.percent_remaining)
            label     = f"{beer_name}  {pct}%  ({keg.liters_remaining:.1f}L left){tap_info}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, keg.id)
            self._list.addItem(item)

        self._on_select(-1)
        self._refresh_tap_combo()

    def _refresh_tap_combo(self) -> None:
        self._tap_combo.clear()
        self._tap_combo.addItem("(unassign)", "")
        for tap_key, name in self._taps:
            self._tap_combo.addItem(name, tap_key)

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def _on_select(self, row: int) -> None:
        has = row >= 0 and row < len(self._kegs)
        self._edit_btn.setEnabled(has)
        self._del_btn.setEnabled(has)
        if not has:
            self._detail_lbl.setText("")
            return
        keg  = self._kegs[row]
        beer = self._db.get_beer(keg.beer_id)
        self._detail_lbl.setText(
            f"Capacity: {keg.liters_capacity:.1f}L  •  "
            f"Poured: {keg.liters_poured:.1f}L  •  "
            f"Remaining: {keg.liters_remaining:.1f}L ({int(keg.percent_remaining)}%)  •  "
            f"Cost: ${keg.price:.2f}"
        )
        # Pre-select tap if assigned
        for i in range(self._tap_combo.count()):
            tap_key = self._tap_combo.itemData(i)
            if tap_key and self._tap_assignments.get(tap_key) == keg.id:
                self._tap_combo.setCurrentIndex(i)
                return
        self._tap_combo.setCurrentIndex(0)

    def _selected_keg(self) -> Optional[Keg]:
        row = self._list.currentRow()
        if row < 0 or row >= len(self._kegs):
            return None
        return self._kegs[row]

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _add_keg(self) -> None:
        if not self._db.get_all_beers():
            QMessageBox.information(
                self, "No Beers",
                "No beers are in the database yet.\n"
                "Add beers via the web admin interface first."
            )
            return
        dlg = _KegDialog(self._config, self._db, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._load()

    def _edit_keg(self) -> None:
        keg = self._selected_keg()
        if not keg:
            return
        dlg = _KegDialog(self._config, self._db, keg=keg, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._load()

    def _delete_keg(self) -> None:
        keg = self._selected_keg()
        if not keg:
            return
        beer = self._db.get_beer(keg.beer_id)
        name = beer.name if beer else "this keg"
        result = QMessageBox.question(
            self, "Delete Keg",
            f"Delete the {name} keg?\n"
            "All pour records for this keg will also be deleted.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        self._db.delete_keg(keg.id)
        log.info("Deleted keg id=%d", keg.id)
        self._load()

    def _assign_tap(self) -> None:
        keg = self._selected_keg()
        if not keg:
            QMessageBox.warning(self, "No Keg Selected", "Select a keg first.")
            return
        tap_key = self._tap_combo.currentData()
        if not tap_key:
            # Unassign — find which tap has this keg and clear it
            for t, kid in list(self._tap_assignments.items()):
                if kid == keg.id:
                    self._db.set_tap(t, None)
                    log.info("Unassigned keg %d from %s", keg.id, t)
        else:
            self._db.set_tap(tap_key, keg.id)
            log.info("Assigned keg %d to %s", keg.id, tap_key)
        self._load()
