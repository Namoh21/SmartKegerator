"""
Thread-safe SQLite database layer.

Each thread gets its own connection via threading.local(). WAL mode allows
concurrent readers alongside the single writer, which suits our use case of
a UI thread + several background hardware threads.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Generator, Optional

import numpy as np

from data.models import (
    Beer, Keg, Payment, Pour, TapAssignment, User, UNKNOWN_USER_ID
)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS beers (
    id              INTEGER PRIMARY KEY,
    name            TEXT    NOT NULL,
    company         TEXT    NOT NULL DEFAULT '',
    location        TEXT    NOT NULL DEFAULT '',
    style           TEXT    NOT NULL DEFAULT '',
    abv             REAL    NOT NULL DEFAULT 0.0,
    ibu             INTEGER NOT NULL DEFAULT 0,
    description     TEXT    NOT NULL DEFAULT '',
    untappd_id      INTEGER,
    untappd_rating  REAL,
    label_url       TEXT    NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS kegs (
    id               INTEGER PRIMARY KEY,
    beer_id          INTEGER NOT NULL REFERENCES beers(id),
    date_bought      TEXT    NOT NULL,
    liters_capacity  REAL    NOT NULL DEFAULT 0.0,
    price            REAL    NOT NULL DEFAULT 0.0,
    warmest_temp     REAL    NOT NULL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS tap_assignments (
    tap    TEXT PRIMARY KEY,
    keg_id INTEGER REFERENCES kegs(id)
);

CREATE TABLE IF NOT EXISTS users (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_images (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    path    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS pours (
    id             INTEGER PRIMARY KEY,
    time           REAL    NOT NULL,
    keg_id         INTEGER NOT NULL REFERENCES kegs(id),
    user_id        INTEGER NOT NULL REFERENCES users(id),
    ticks          INTEGER NOT NULL DEFAULT 0,
    ounces         REAL    NOT NULL DEFAULT 0.0,
    price          REAL    NOT NULL DEFAULT 0.0,
    price_modifier REAL    NOT NULL DEFAULT 1.0
);

CREATE TABLE IF NOT EXISTS payments (
    id      INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    time    REAL    NOT NULL,
    amount  REAL    NOT NULL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS face_encodings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    image_path TEXT    NOT NULL,
    encoding   BLOB    NOT NULL   -- numpy float64 array (128 values) as raw bytes
);

CREATE TABLE IF NOT EXISTS admins (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT    NOT NULL,
    created_at    REAL    NOT NULL DEFAULT 0.0,
    user_id       INTEGER REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS device_tokens (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    token      TEXT    NOT NULL UNIQUE,
    platform   TEXT    NOT NULL DEFAULT 'android',
    label      TEXT    NOT NULL DEFAULT '',
    created_at REAL    NOT NULL DEFAULT 0.0
);

CREATE INDEX IF NOT EXISTS idx_pours_time    ON pours(time);
CREATE INDEX IF NOT EXISTS idx_pours_keg     ON pours(keg_id);
CREATE INDEX IF NOT EXISTS idx_pours_user    ON pours(user_id);
CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id);
CREATE INDEX IF NOT EXISTS idx_encodings_user ON face_encodings(user_id);
"""

_SEED = f"""
INSERT OR IGNORE INTO users (id, name) VALUES ({UNKNOWN_USER_ID}, 'Unknown');
INSERT OR IGNORE INTO tap_assignments (tap, keg_id) VALUES ('tap1', NULL);
INSERT OR IGNORE INTO tap_assignments (tap, keg_id) VALUES ('tap2', NULL);
INSERT OR IGNORE INTO tap_assignments (tap, keg_id) VALUES ('tap3', NULL);
INSERT OR IGNORE INTO tap_assignments (tap, keg_id) VALUES ('tap4', NULL);
"""


# ---------------------------------------------------------------------------
# Database class
# ---------------------------------------------------------------------------

class Database:
    def __init__(self, path: str) -> None:
        self._path = path
        self._local = threading.local()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn"):
            conn = sqlite3.connect(self._path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            self._local.conn = conn
        return self._local.conn

    @contextmanager
    def _cursor(self) -> Generator[sqlite3.Cursor, None, None]:
        conn = self._conn()
        cur = conn.cursor()
        try:
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()

    def _init_schema(self) -> None:
        with self._cursor() as cur:
            cur.executescript(_SCHEMA)
            cur.executescript(_SEED)
        self._migrate()

    def _migrate(self) -> None:
        """Schema migrations — safe to re-run on every startup."""
        # Beer columns added after initial release
        new_columns = [
            "ALTER TABLE beers ADD COLUMN description    TEXT    NOT NULL DEFAULT ''",
            "ALTER TABLE beers ADD COLUMN untappd_id     INTEGER",
            "ALTER TABLE beers ADD COLUMN untappd_rating REAL",
            "ALTER TABLE beers ADD COLUMN label_url      TEXT    NOT NULL DEFAULT ''",
        ]
        with self._cursor() as cur:
            for sql in new_columns:
                try:
                    cur.execute(sql)
                except sqlite3.OperationalError:
                    pass  # column already exists

        # Migrate tap_assignments: left/center/right → tap1/tap2/tap3
        # Also recreates table without the old CHECK constraint.
        with self._cursor() as cur:
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tap_assignments'")
            if cur.fetchone():
                cur.execute("SELECT tap FROM tap_assignments LIMIT 1")
                row = cur.fetchone()
                if row and row["tap"] in ("left", "center", "right"):
                    cur.executescript("""
                        CREATE TABLE IF NOT EXISTS _tap_assignments_new (
                            tap    TEXT PRIMARY KEY,
                            keg_id INTEGER REFERENCES kegs(id)
                        );
                        INSERT OR IGNORE INTO _tap_assignments_new (tap, keg_id)
                            SELECT CASE tap
                                WHEN 'left'   THEN 'tap1'
                                WHEN 'center' THEN 'tap2'
                                WHEN 'right'  THEN 'tap3'
                                ELSE tap
                            END, keg_id
                            FROM tap_assignments;
                        DROP TABLE tap_assignments;
                        ALTER TABLE _tap_assignments_new RENAME TO tap_assignments;
                    """)
        # Ensure all four tap rows exist after migration
        with self._cursor() as cur:
            for tap in ("tap1", "tap2", "tap3", "tap4"):
                cur.execute(
                    "INSERT OR IGNORE INTO tap_assignments (tap, keg_id) VALUES (?, NULL)", (tap,)
                )

        # Add password_hash column to users (standard-user self-login)
        try:
            with self._cursor() as cur:
                cur.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
        except sqlite3.OperationalError:
            pass  # column already exists

        # Add user_id column to admins table (links admin → drinking user)
        try:
            with self._cursor() as cur:
                cur.execute("ALTER TABLE admins ADD COLUMN user_id INTEGER REFERENCES users(id)")
        except sqlite3.OperationalError:
            pass  # column already exists

        # For existing admins with no linked user, create a user record for each
        with self._cursor() as cur:
            cur.execute("SELECT id, username FROM admins WHERE user_id IS NULL")
            orphans = cur.fetchall()
        for row in orphans:
            with self._cursor() as cur:
                cur.execute("INSERT INTO users (name) VALUES (?)", (row["username"],))
                uid = cur.lastrowid
                cur.execute("UPDATE admins SET user_id = ? WHERE id = ?", (uid, row["id"]))

    # ------------------------------------------------------------------
    # Beer
    # ------------------------------------------------------------------

    def get_all_beers(self) -> list[Beer]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM beers ORDER BY name")
            return [_row_to_beer(r) for r in cur.fetchall()]

    def get_beer(self, beer_id: int) -> Optional[Beer]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM beers WHERE id = ?", (beer_id,))
            row = cur.fetchone()
            return _row_to_beer(row) if row else None

    def save_beer(self, beer: Beer) -> Beer:
        with self._cursor() as cur:
            if beer.id is None:
                cur.execute(
                    "INSERT INTO beers "
                    "(name, company, location, style, abv, ibu, description, untappd_id, untappd_rating, label_url) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (beer.name, beer.company, beer.location, beer.style, beer.abv, beer.ibu,
                     beer.description, beer.untappd_id, beer.untappd_rating, beer.label_url),
                )
                beer.id = cur.lastrowid
            else:
                cur.execute(
                    "INSERT OR REPLACE INTO beers "
                    "(id, name, company, location, style, abv, ibu, description, untappd_id, untappd_rating, label_url) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (beer.id, beer.name, beer.company, beer.location, beer.style, beer.abv, beer.ibu,
                     beer.description, beer.untappd_id, beer.untappd_rating, beer.label_url),
                )
        return beer

    def delete_beer(self, beer_id: int) -> None:
        """Cascade: clears tap assignments, deletes pours, kegs, then the beer."""
        with self._cursor() as cur:
            cur.execute("SELECT id FROM kegs WHERE beer_id = ?", (beer_id,))
            keg_ids = [r["id"] for r in cur.fetchall()]
            for kid in keg_ids:
                cur.execute("UPDATE tap_assignments SET keg_id = NULL WHERE keg_id = ?", (kid,))
                cur.execute("DELETE FROM pours WHERE keg_id = ?", (kid,))
            if keg_ids:
                placeholders = ",".join("?" * len(keg_ids))
                cur.execute(f"DELETE FROM kegs WHERE id IN ({placeholders})", keg_ids)
            cur.execute("DELETE FROM beers WHERE id = ?", (beer_id,))

    # ------------------------------------------------------------------
    # Settings (key/value store for runtime config — never in source code)
    # ------------------------------------------------------------------

    def get_setting(self, key: str, default: str = "") -> str:
        with self._cursor() as cur:
            cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cur.fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def get_all_settings(self) -> dict[str, str]:
        with self._cursor() as cur:
            cur.execute("SELECT key, value FROM settings")
            return {row["key"]: row["value"] for row in cur.fetchall()}

    # ------------------------------------------------------------------
    # Keg
    # ------------------------------------------------------------------

    def get_all_kegs(self) -> list[Keg]:
        with self._cursor() as cur:
            cur.execute("""
                SELECT k.*,
                       COALESCE(SUM(p.ounces) / 33.814, 0.0) AS liters_poured
                FROM kegs k
                LEFT JOIN pours p ON p.keg_id = k.id
                GROUP BY k.id
                ORDER BY k.id
            """)
            return [_row_to_keg(r) for r in cur.fetchall()]

    def get_keg(self, keg_id: int) -> Optional[Keg]:
        with self._cursor() as cur:
            cur.execute("""
                SELECT k.*,
                       COALESCE(SUM(p.ounces) / 33.814, 0.0) AS liters_poured
                FROM kegs k
                LEFT JOIN pours p ON p.keg_id = k.id
                WHERE k.id = ?
                GROUP BY k.id
            """, (keg_id,))
            row = cur.fetchone()
            return _row_to_keg(row) if row else None

    def save_keg(self, keg: Keg) -> Keg:
        date_str = keg.date_bought.strftime("%Y-%m-%d")
        with self._cursor() as cur:
            if keg.id is None:
                cur.execute(
                    "INSERT INTO kegs (beer_id, date_bought, liters_capacity, price, warmest_temp) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (keg.beer_id, date_str, keg.liters_capacity, keg.price, keg.warmest_temp),
                )
                keg.id = cur.lastrowid
            else:
                cur.execute(
                    "INSERT OR REPLACE INTO kegs (id, beer_id, date_bought, liters_capacity, price, warmest_temp) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (keg.id, keg.beer_id, date_str, keg.liters_capacity, keg.price, keg.warmest_temp),
                )
        return keg

    def delete_keg(self, keg_id: int) -> None:
        """Cascade: clears tap assignment and deletes pours before removing keg."""
        with self._cursor() as cur:
            cur.execute("UPDATE tap_assignments SET keg_id = NULL WHERE keg_id = ?", (keg_id,))
            cur.execute("DELETE FROM pours WHERE keg_id = ?", (keg_id,))
            cur.execute("DELETE FROM kegs WHERE id = ?", (keg_id,))

    # ------------------------------------------------------------------
    # Tap assignments
    # ------------------------------------------------------------------

    def get_tap_assignments(self) -> TapAssignment:
        with self._cursor() as cur:
            cur.execute("SELECT tap, keg_id FROM tap_assignments")
            return TapAssignment(taps={r["tap"]: r["keg_id"] for r in cur.fetchall()})

    def set_tap(self, tap: str, keg_id: Optional[int]) -> None:
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO tap_assignments (tap, keg_id) VALUES (?, ?) "
                "ON CONFLICT(tap) DO UPDATE SET keg_id = excluded.keg_id",
                (tap, keg_id),
            )

    # ------------------------------------------------------------------
    # User
    # ------------------------------------------------------------------

    def get_all_users(self) -> list[User]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM users ORDER BY name")
            users = [_row_to_user(r) for r in cur.fetchall()]
        for user in users:
            user.image_paths = self._get_image_paths(user.id)
        return users

    def get_user(self, user_id: int) -> Optional[User]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
            row = cur.fetchone()
            if not row:
                return None
            user = _row_to_user(row)
        user.image_paths = self._get_image_paths(user_id)
        return user

    def save_user(self, user: User) -> User:
        with self._cursor() as cur:
            if user.id is None:
                cur.execute("INSERT INTO users (name) VALUES (?)", (user.name,))
                user.id = cur.lastrowid
            else:
                cur.execute(
                    "INSERT OR REPLACE INTO users (id, name) VALUES (?, ?)",
                    (user.id, user.name),
                )
            cur.execute("DELETE FROM user_images WHERE user_id = ?", (user.id,))
            cur.executemany(
                "INSERT INTO user_images (user_id, path) VALUES (?, ?)",
                [(user.id, p) for p in user.image_paths],
            )
        return user

    def add_user_image(self, user_id: int, path: str) -> None:
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO user_images (user_id, path) VALUES (?, ?)",
                (user_id, path),
            )

    def delete_user(self, user_id: int) -> None:
        with self._cursor() as cur:
            cur.execute("DELETE FROM users WHERE id = ?", (user_id,))

    def register_user(self, name: str) -> Optional["User"]:
        """Create a user profile (no password — identity via face recognition).

        Returns the new User, or None if the display name is already taken.
        """
        with self._cursor() as cur:
            cur.execute(
                "SELECT id FROM users WHERE name = ? AND id != ?",
                (name, UNKNOWN_USER_ID),
            )
            if cur.fetchone():
                return None  # name already taken
            cur.execute("INSERT INTO users (name) VALUES (?)", (name,))
            user_id = cur.lastrowid
        return self.get_user(user_id)

    def _get_image_paths(self, user_id: int) -> list[str]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT path FROM user_images WHERE user_id = ? ORDER BY id",
                (user_id,),
            )
            return [r["path"] for r in cur.fetchall()]

    # ------------------------------------------------------------------
    # Pour
    # ------------------------------------------------------------------

    def get_all_pours(self) -> list[Pour]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM pours ORDER BY time")
            return [_row_to_pour(r) for r in cur.fetchall()]

    def get_pours_for_keg(self, keg_id: int) -> list[Pour]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM pours WHERE keg_id = ? ORDER BY time", (keg_id,))
            return [_row_to_pour(r) for r in cur.fetchall()]

    def get_pours_for_user(self, user_id: int) -> list[Pour]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM pours WHERE user_id = ? ORDER BY time", (user_id,))
            return [_row_to_pour(r) for r in cur.fetchall()]

    def get_pours_since(self, since: float) -> list[Pour]:
        """Return all pours with time >= since (unix timestamp)."""
        with self._cursor() as cur:
            cur.execute("SELECT * FROM pours WHERE time >= ? ORDER BY time", (since,))
            return [_row_to_pour(r) for r in cur.fetchall()]

    def add_pour(self, pour: Pour) -> Pour:
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO pours (time, keg_id, user_id, ticks, ounces, price, price_modifier) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (pour.time, pour.keg_id, pour.user_id, pour.ticks,
                 pour.ounces, pour.price, pour.price_modifier),
            )
            pour.id = cur.lastrowid
        return pour

    def delete_pour(self, pour_id: int) -> None:
        with self._cursor() as cur:
            cur.execute("DELETE FROM pours WHERE id = ?", (pour_id,))

    # ------------------------------------------------------------------
    # Payment
    # ------------------------------------------------------------------

    def get_all_payments(self) -> list[Payment]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM payments ORDER BY time")
            return [_row_to_payment(r) for r in cur.fetchall()]

    def get_payments_for_user(self, user_id: int) -> list[Payment]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM payments WHERE user_id = ? ORDER BY time", (user_id,)
            )
            return [_row_to_payment(r) for r in cur.fetchall()]

    def add_payment(self, user_id: int, amount: float) -> Payment:
        now = time.time()
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO payments (user_id, time, amount) VALUES (?, ?, ?)",
                (user_id, now, amount),
            )
            payment_id = cur.lastrowid
        return Payment(id=payment_id, user_id=user_id, time=now, amount=amount)

    def balance_for_user(self, user_id: int) -> float:
        """Total pours charged minus total payments made (positive = owes money)."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT COALESCE(SUM(price), 0.0) FROM pours WHERE user_id = ?",
                (user_id,),
            )
            charged = cur.fetchone()[0]
            cur.execute(
                "SELECT COALESCE(SUM(amount), 0.0) FROM payments WHERE user_id = ?",
                (user_id,),
            )
            paid = cur.fetchone()[0]
        return charged - paid

    # ------------------------------------------------------------------
    # Admin accounts
    # ------------------------------------------------------------------

    def is_user_admin(self, user_id: int) -> bool:
        """Return True if user_id has a linked admin account."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT 1 FROM admins WHERE user_id = ? LIMIT 1", (user_id,)
            )
            return cur.fetchone() is not None

    def has_any_admin(self) -> bool:
        with self._cursor() as cur:
            cur.execute("SELECT 1 FROM admins LIMIT 1")
            return cur.fetchone() is not None

    def admin_count(self) -> int:
        with self._cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM admins")
            return cur.fetchone()[0]

    def get_all_admins(self) -> list[dict]:
        with self._cursor() as cur:
            cur.execute("""
                SELECT a.id, a.username, a.created_at, a.user_id,
                       u.name AS display_name
                FROM admins a
                LEFT JOIN users u ON u.id = a.user_id
                ORDER BY a.created_at
            """)
            return [dict(r) for r in cur.fetchall()]

    def get_admin_user_ids(self) -> set:
        """Return set of user_ids that have admin accounts."""
        with self._cursor() as cur:
            cur.execute("SELECT user_id FROM admins WHERE user_id IS NOT NULL")
            return {r["user_id"] for r in cur.fetchall()}

    def get_admin_by_username(self, username: str) -> Optional[dict]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT id, username, password_hash, user_id FROM admins WHERE username = ?",
                (username,)
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def add_admin(self, username: str, password_hash: str, display_name: str = "") -> int:
        """Create an admin account and link it to a drinking-user record.

        If a user with the given display_name already exists that user is
        reused; otherwise a new one is created.  Returns the new admin id.
        """
        name = display_name.strip() or username.strip()
        # Find or create the linked user
        with self._cursor() as cur:
            cur.execute("SELECT id FROM users WHERE name = ? AND id != ?",
                        (name, UNKNOWN_USER_ID))
            row = cur.fetchone()
            if row:
                user_id = row["id"]
            else:
                cur.execute("INSERT INTO users (name) VALUES (?)", (name,))
                user_id = cur.lastrowid
        # Create the admin record
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO admins (username, password_hash, created_at, user_id) VALUES (?, ?, ?, ?)",
                (username, password_hash, time.time(), user_id),
            )
            return cur.lastrowid

    def delete_admin(self, admin_id: int) -> None:
        with self._cursor() as cur:
            cur.execute("DELETE FROM admins WHERE id = ?", (admin_id,))

    def change_admin_password(self, admin_id: int, password_hash: str) -> None:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE admins SET password_hash = ? WHERE id = ?",
                (password_hash, admin_id),
            )

    # ------------------------------------------------------------------
    # Face encodings
    # ------------------------------------------------------------------

    def get_all_face_encodings(self) -> list[tuple[int, np.ndarray]]:
        """Return [(user_id, encoding_array), ...] for every stored encoding."""
        with self._cursor() as cur:
            cur.execute("SELECT user_id, encoding FROM face_encodings")
            return [
                (row["user_id"], np.frombuffer(row["encoding"], dtype=np.float64))
                for row in cur.fetchall()
            ]

    def get_face_encodings_for_user(self, user_id: int) -> list[np.ndarray]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT encoding FROM face_encodings WHERE user_id = ?", (user_id,)
            )
            return [
                np.frombuffer(row["encoding"], dtype=np.float64)
                for row in cur.fetchall()
            ]

    def save_face_encodings(
        self, user_id: int, encodings: list[tuple[str, np.ndarray]]
    ) -> None:
        """Replace all stored encodings for a user. encodings = [(image_path, array), ...]"""
        with self._cursor() as cur:
            cur.execute("DELETE FROM face_encodings WHERE user_id = ?", (user_id,))
            cur.executemany(
                "INSERT INTO face_encodings (user_id, image_path, encoding) VALUES (?, ?, ?)",
                [
                    (user_id, path, enc.astype(np.float64).tobytes())
                    for path, enc in encodings
                ],
            )

    def delete_face_encodings_for_user(self, user_id: int) -> None:
        with self._cursor() as cur:
            cur.execute("DELETE FROM face_encodings WHERE user_id = ?", (user_id,))

    # ------------------------------------------------------------------
    # Device tokens (FCM push notifications)
    # ------------------------------------------------------------------

    def add_device_token(self, token: str, platform: str = "android", label: str = "") -> None:
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO device_tokens (token, platform, label, created_at) VALUES (?, ?, ?, ?)"
                " ON CONFLICT(token) DO UPDATE SET label = excluded.label, created_at = excluded.created_at",
                (token, platform, label, time.time()),
            )

    def remove_device_token(self, token: str) -> None:
        with self._cursor() as cur:
            cur.execute("DELETE FROM device_tokens WHERE token = ?", (token,))

    def get_device_tokens(self) -> list[str]:
        with self._cursor() as cur:
            cur.execute("SELECT token FROM device_tokens ORDER BY created_at")
            return [r["token"] for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Row → model helpers
# ---------------------------------------------------------------------------

def _row_to_beer(row: sqlite3.Row) -> Beer:
    keys = row.keys()
    return Beer(
        id=row["id"],
        name=row["name"],
        company=row["company"],
        location=row["location"],
        style=row["style"],
        abv=row["abv"],
        ibu=row["ibu"],
        description=row["description"] if "description" in keys else "",
        untappd_id=row["untappd_id"] if "untappd_id" in keys else None,
        untappd_rating=row["untappd_rating"] if "untappd_rating" in keys else None,
        label_url=row["label_url"] if "label_url" in keys else "",
    )


def _row_to_keg(row: sqlite3.Row) -> Keg:
    return Keg(
        id=row["id"],
        beer_id=row["beer_id"],
        date_bought=datetime.fromisoformat(row["date_bought"]),
        liters_capacity=row["liters_capacity"],
        price=row["price"],
        warmest_temp=row["warmest_temp"],
        liters_poured=row["liters_poured"],
    )


def _row_to_user(row: sqlite3.Row) -> User:
    return User(id=row["id"], name=row["name"])


def _row_to_pour(row: sqlite3.Row) -> Pour:
    return Pour(
        id=row["id"],
        time=row["time"],
        keg_id=row["keg_id"],
        user_id=row["user_id"],
        ticks=row["ticks"],
        ounces=row["ounces"],
        price=row["price"],
        price_modifier=row["price_modifier"],
    )


def _row_to_payment(row: sqlite3.Row) -> Payment:
    return Payment(
        id=row["id"],
        user_id=row["user_id"],
        time=row["time"],
        amount=row["amount"],
    )
