"""
One-time migration from the original SmartKegerator flat-file format into SQLite.

Usage (run from the src/ directory):
    python -m scripts.migrate_data \
        --beers    /path/to/logs/beers.txt \
        --kegs     /path/to/logs/kegs.txt \
        --users    /path/to/logs/users.txt \
        --pours    /path/to/logs/pours.txt \
        --payments /path/to/logs/payments.txt \
        --db       /home/pi/smartkegerator/smartkegerator.db

All flags are optional; omit any file you don't have.
The target database is created (with full schema) if it doesn't exist.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# Allow running as: python -m scripts.migrate_data from src/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.database import Database
from data.models import Beer, Keg, Payment, Pour, User, UNKNOWN_USER_ID


# ---------------------------------------------------------------------------
# Flat-file parser
# ---------------------------------------------------------------------------

def parse_records(text: str) -> list[dict[str, str]]:
    """
    Parse the original SmartKegerator flat-file format into a list of dicts.

    Each record is delimited by { ... } and contains lines of the form:
        Key:Value
    Values may themselves contain colons (e.g. image paths), so we only split
    on the *first* colon.
    """
    records: list[dict[str, str]] = []
    depth = 0
    current: dict[str, str] = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line == "{":
            depth += 1
            current = {}
        elif line == "}":
            depth -= 1
            if depth == 0 and current:
                records.append(current)
        elif depth > 0 and ":" in line:
            key, _, value = line.partition(":")
            current[key.strip()] = value.strip()

    return records


def _read(path: Optional[str]) -> list[dict[str, str]]:
    if not path:
        return []
    p = Path(path)
    if not p.exists():
        print(f"  [skip] {path} not found")
        return []
    return parse_records(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Field helpers
# ---------------------------------------------------------------------------

def _int(d: dict, key: str, default: int = 0) -> int:
    try:
        return int(float(d.get(key, default)))
    except (ValueError, TypeError):
        return default


def _float(d: dict, key: str, default: float = 0.0) -> float:
    try:
        return float(d.get(key, default))
    except (ValueError, TypeError):
        return default


def _str(d: dict, key: str, default: str = "") -> str:
    return str(d.get(key, default)).strip()


def _parse_date(s: str) -> datetime:
    """
    Parse the original M/D/YY date format (e.g. '7/31/15') into a datetime.
    Falls back to today on parse failure.
    """
    for fmt in ("%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue
    print(f"  [warn] could not parse date '{s}', using today")
    return datetime.today()


# ---------------------------------------------------------------------------
# Migration steps
# ---------------------------------------------------------------------------

def migrate_beers(db: Database, path: Optional[str]) -> dict[int, int]:
    """Returns mapping of old beer ID -> new beer ID."""
    records = _read(path)
    if not records:
        return {}

    id_map: dict[int, int] = {}
    print(f"Migrating {len(records)} beer(s)...")

    for rec in records:
        old_id = _int(rec, "Id", -99)
        beer = Beer(
            id=None,
            name=_str(rec, "Name"),
            company=_str(rec, "Company"),
            location=_str(rec, "Location"),
            style=_str(rec, "Type"),
            abv=_float(rec, "ABV"),
            ibu=_int(rec, "IBU"),
        )
        db.save_beer(beer)
        id_map[old_id] = beer.id
        print(f"  Beer {old_id} -> {beer.id}: {beer.name}")

    return id_map


def migrate_kegs(
    db: Database, path: Optional[str], beer_id_map: dict[int, int]
) -> tuple[dict[int, int], dict[str, Optional[int]]]:
    """
    Returns:
        keg_id_map  — old keg ID -> new keg ID
        tap_map     — {'left': keg_id, 'center': keg_id, 'right': keg_id}
    """
    records = _read(path)
    if not records:
        return {}, {"left": None, "center": None, "right": None}

    # First record is always the tap assignment in the original format
    tap_rec = records[0]
    tap_map: dict[str, Optional[int]] = {
        "left": None,
        "center": None,
        "right": None,
    }

    def _tap_keg(old_id: int) -> Optional[int]:
        return None if old_id < 0 else old_id   # resolved after kegs are inserted

    old_left   = _int(tap_rec, "LeftKegId",   -1)
    old_center = _int(tap_rec, "CenterKegId", -1)
    old_right  = _int(tap_rec, "RightKegId",  -1)

    keg_records = records[1:]
    print(f"Migrating {len(keg_records)} keg(s)...")

    id_map: dict[int, int] = {}

    for rec in keg_records:
        old_id   = _int(rec, "Id", -99)
        old_beer = _int(rec, "BeerId", -1)
        new_beer = beer_id_map.get(old_beer)

        if new_beer is None:
            print(f"  [warn] keg {old_id} references unknown beer {old_beer}, skipping")
            continue

        keg = Keg(
            id=None,
            beer_id=new_beer,
            date_bought=_parse_date(_str(rec, "DateBought", "1/1/00")),
            liters_capacity=_float(rec, "LitersCapacity"),
            price=_float(rec, "Price"),
            warmest_temp=_float(rec, "WarmestTemp"),
        )
        db.save_keg(keg)
        id_map[old_id] = keg.id
        print(f"  Keg {old_id} -> {keg.id} (beer {new_beer})")

    # Resolve tap assignments using the new IDs
    if old_left   >= 0: tap_map["left"]   = id_map.get(old_left)
    if old_center >= 0: tap_map["center"] = id_map.get(old_center)
    if old_right  >= 0: tap_map["right"]  = id_map.get(old_right)

    for tap, keg_id in tap_map.items():
        db.set_tap(tap, keg_id)
        print(f"  Tap '{tap}' -> keg {keg_id}")

    return id_map, tap_map


def migrate_users(db: Database, path: Optional[str]) -> dict[int, int]:
    """Returns mapping of old user ID -> new user ID."""
    records = _read(path)
    if not records:
        return {}

    id_map: dict[int, int] = {}
    print(f"Migrating {len(records)} user(s)...")

    for rec in records:
        old_id = _int(rec, "Id", -99)

        # The original unknown user (id=-1) is seeded into the DB at init time
        if old_id == UNKNOWN_USER_ID:
            id_map[UNKNOWN_USER_ID] = UNKNOWN_USER_ID
            continue

        raw_paths = _str(rec, "ImagePaths")
        image_paths = [p for p in raw_paths.split(",") if p.strip()] if raw_paths else []

        user = User(
            id=None,
            name=_str(rec, "Name"),
            image_paths=image_paths,
        )
        db.save_user(user)
        id_map[old_id] = user.id
        print(f"  User {old_id} -> {user.id}: {user.name} ({len(image_paths)} photos)")

    return id_map


def migrate_pours(
    db: Database,
    path: Optional[str],
    keg_id_map: dict[int, int],
    user_id_map: dict[int, int],
    ticks_per_liter: int = 500,
) -> int:
    records = _read(path)
    if not records:
        return 0

    ounces_per_liter = 33.814
    count = 0
    skipped = 0

    print(f"Migrating {len(records)} pour(s)...")

    for rec in records:
        old_keg  = _int(rec, "KegId",  -1)
        old_user = _int(rec, "UserId", UNKNOWN_USER_ID)

        new_keg  = keg_id_map.get(old_keg)
        new_user = user_id_map.get(old_user, UNKNOWN_USER_ID)

        if new_keg is None:
            skipped += 1
            continue

        ticks  = _int(rec, "Ticks")
        ounces = _float(rec, "Ounces")

        # If ounces weren't stored, compute from ticks
        if ounces == 0.0 and ticks > 0 and ticks_per_liter > 0:
            liters = ticks / ticks_per_liter
            ounces = liters * ounces_per_liter

        pour = Pour(
            id=_int(rec, "Id") or None,
            time=_float(rec, "Time") or 0.0,
            keg_id=new_keg,
            user_id=new_user,
            ticks=ticks,
            ounces=ounces,
            price=_float(rec, "Price"),
            price_modifier=_float(rec, "PriceModifier") or 1.0,
        )
        db.add_pour(pour)
        count += 1

    print(f"  Migrated {count} pour(s), skipped {skipped}")
    return count


def migrate_payments(
    db: Database, path: Optional[str], user_id_map: dict[int, int]
) -> int:
    records = _read(path)
    if not records:
        return 0

    count = 0
    skipped = 0

    print(f"Migrating {len(records)} payment(s)...")

    for rec in records:
        # Legacy payments.txt sometimes has stale user-snapshot fields mixed in;
        # only process records that have an Amount field.
        if "Amount" not in rec:
            skipped += 1
            continue

        old_user = _int(rec, "UserId", UNKNOWN_USER_ID)
        new_user = user_id_map.get(old_user, UNKNOWN_USER_ID)

        import sqlite3
        conn_path = db._path
        payment = Payment(
            id=_int(rec, "Id") or None,
            user_id=new_user,
            time=_float(rec, "Time") or 0.0,
            amount=_float(rec, "Amount"),
        )

        # Use low-level insert so we can preserve original IDs
        import sqlite3 as _sq
        conn = _sq.connect(conn_path)
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute(
                "INSERT OR IGNORE INTO payments (id, user_id, time, amount) VALUES (?, ?, ?, ?)",
                (payment.id, payment.user_id, payment.time, payment.amount),
            )
            conn.commit()
        finally:
            conn.close()

        count += 1

    print(f"  Migrated {count} payment(s), skipped {skipped}")
    return count


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate SmartKegerator flat files to SQLite")
    parser.add_argument("--beers",    help="Path to beers.txt")
    parser.add_argument("--kegs",     help="Path to kegs.txt")
    parser.add_argument("--users",    help="Path to users.txt")
    parser.add_argument("--pours",    help="Path to pours.txt")
    parser.add_argument("--payments", help="Path to payments.txt")
    parser.add_argument("--db",       required=True, help="Path for the output SQLite database")
    parser.add_argument("--ticks-per-liter", type=int, default=500,
                        help="Flow meter ticks per liter (default: 500)")
    args = parser.parse_args()

    print(f"\nSmartKegerator Data Migration")
    print(f"Target database: {args.db}\n")

    db = Database(args.db)

    beer_id_map = migrate_beers(db, args.beers)
    keg_id_map, _ = migrate_kegs(db, args.kegs, beer_id_map)
    user_id_map = migrate_users(db, args.users)

    # Always map the unknown user to itself
    user_id_map.setdefault(UNKNOWN_USER_ID, UNKNOWN_USER_ID)

    migrate_pours(db, args.pours, keg_id_map, user_id_map, args.ticks_per_liter)
    migrate_payments(db, args.payments, user_id_map)

    print("\nMigration complete.")


if __name__ == "__main__":
    main()
