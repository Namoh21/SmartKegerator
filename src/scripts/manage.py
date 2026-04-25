"""
SmartKegerator management CLI.

Use this to set up beers, kegs, and tap assignments from a terminal
before the touchscreen app is running — or any time you want to manage
data without touching the UI.

Usage (run from the src/ directory):
    python -m scripts.manage <command> [options]

Commands:
    beer list
    beer add   --name NAME --company CO --abv 5.2 --ibu 52
               --style "Amber Ale" --location "Redmond, WA"
    beer delete --id ID

    keg  list
    keg  add   --beer-id ID --capacity 19.5 --price 120
               [--date YYYY-MM-DD] [--warmest-temp 40]
    keg  delete --id ID

    tap  status
    tap  set   left|center|right --keg-id ID
    tap  clear left|center|right

    user list
    user delete --id ID

    stats              summary of recent pours
    payment add --user-id ID --amount 10.00
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# Allow running as: python -m scripts.manage   from src/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml

from data.database import Database
from data.models import Beer, Keg, UNKNOWN_USER_ID


# ---------------------------------------------------------------------------
# Config / DB loader
# ---------------------------------------------------------------------------

def _load_db(config_path: Optional[str] = None) -> Database:
    if config_path is None:
        # Walk up from here looking for config.yaml
        here = Path(__file__).resolve()
        for parent in here.parents:
            candidate = parent / "config.yaml"
            if candidate.exists():
                config_path = str(candidate)
                break
        if config_path is None:
            print("ERROR: config.yaml not found. Pass --config /path/to/config.yaml")
            sys.exit(1)

    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    db_path = config["data"]["database_path"]
    print(f"Database: {db_path}\n")
    return Database(db_path)


# ---------------------------------------------------------------------------
# Beer commands
# ---------------------------------------------------------------------------

def cmd_beer_list(db: Database, _args) -> None:
    beers = db.get_all_beers()
    if not beers:
        print("No beers in database.")
        return
    print(f"{'ID':>4}  {'Name':<28}  {'Company':<22}  {'Style':<18}  {'ABV':>5}  {'IBU':>4}")
    print("─" * 92)
    for b in beers:
        print(f"{b.id:>4}  {b.name:<28}  {b.company:<22}  {b.style:<18}  {b.abv:>5.1f}  {b.ibu:>4}")


def cmd_beer_add(db: Database, args) -> None:
    beer = Beer(
        id=None,
        name=args.name,
        company=args.company or "",
        location=args.location or "",
        style=args.style or "",
        abv=args.abv or 0.0,
        ibu=args.ibu or 0,
    )
    db.save_beer(beer)
    print(f"Added beer #{beer.id}: {beer.name}")


def cmd_beer_delete(db: Database, args) -> None:
    beer = db.get_beer(args.id)
    if not beer:
        print(f"Beer #{args.id} not found.")
        return
    confirm = input(f"Delete '{beer.name}'? [y/N] ").strip().lower()
    if confirm == "y":
        db.delete_beer(args.id)
        print(f"Deleted beer #{args.id}.")


# ---------------------------------------------------------------------------
# Keg commands
# ---------------------------------------------------------------------------

def cmd_keg_list(db: Database, _args) -> None:
    kegs  = db.get_all_kegs()
    taps  = db.get_tap_assignments()
    tap_map = {
        taps.left_keg_id:   "LEFT",
        taps.center_keg_id: "CENTER",
        taps.right_keg_id:  "RIGHT",
    }

    if not kegs:
        print("No kegs in database.")
        return

    print(f"{'ID':>4}  {'Beer':<28}  {'Bought':<12}  {'Cap L':>6}  {'Poured':>8}  {'Left%':>6}  {'Price':>7}  {'Tap':<7}")
    print("─" * 100)
    for k in kegs:
        beer = db.get_beer(k.beer_id)
        beer_name = beer.name if beer else f"(beer #{k.beer_id})"
        tap  = tap_map.get(k.id, "")
        print(
            f"{k.id:>4}  {beer_name:<28}  {k.date_bought.strftime('%Y-%m-%d'):<12}  "
            f"{k.liters_capacity:>6.1f}  {k.liters_poured:>8.2f}  {k.percent_remaining:>5.0f}%  "
            f"${k.price:>6.2f}  {tap:<7}"
        )


def cmd_keg_add(db: Database, args) -> None:
    beer = db.get_beer(args.beer_id)
    if not beer:
        print(f"Beer #{args.beer_id} not found. Add it first with:  manage beer add ...")
        sys.exit(1)

    date_bought = datetime.today()
    if args.date:
        try:
            date_bought = datetime.strptime(args.date, "%Y-%m-%d")
        except ValueError:
            print("Date must be YYYY-MM-DD format.")
            sys.exit(1)

    keg = Keg(
        id=None,
        beer_id=args.beer_id,
        date_bought=date_bought,
        liters_capacity=args.capacity,
        price=args.price,
        warmest_temp=args.warmest_temp or 0.0,
    )
    db.save_keg(keg)
    print(f"Added keg #{keg.id}: {beer.name}  ({args.capacity}L @ ${args.price:.2f})")
    print(f"  Assign to a tap with:  manage tap set left --keg-id {keg.id}")


def cmd_keg_delete(db: Database, args) -> None:
    keg = db.get_keg(args.id)
    if not keg:
        print(f"Keg #{args.id} not found.")
        return
    beer = db.get_beer(keg.beer_id)
    confirm = input(f"Delete keg #{args.id} ({beer.name if beer else '?'})? [y/N] ").strip().lower()
    if confirm == "y":
        db.delete_keg(args.id)
        print(f"Deleted keg #{args.id}.")


# ---------------------------------------------------------------------------
# Tap commands
# ---------------------------------------------------------------------------

def cmd_tap_status(db: Database, _args) -> None:
    taps = db.get_tap_assignments()
    for tap_name, keg_id in [
        ("left",   taps.left_keg_id),
        ("center", taps.center_keg_id),
        ("right",  taps.right_keg_id),
    ]:
        if keg_id is None:
            print(f"  {tap_name.upper():<8}  — empty —")
        else:
            keg  = db.get_keg(keg_id)
            beer = db.get_beer(keg.beer_id) if keg else None
            name = beer.name if beer else f"(beer #{keg.beer_id if keg else '?'})"
            pct  = f"{keg.percent_remaining:.0f}%" if keg else "?"
            print(f"  {tap_name.upper():<8}  keg #{keg_id}  {name}  [{pct} remaining]")


def cmd_tap_set(db: Database, args) -> None:
    tap = args.tap.lower()
    if tap not in ("left", "center", "right"):
        print("Tap must be: left, center, or right")
        sys.exit(1)
    keg = db.get_keg(args.keg_id)
    if not keg:
        print(f"Keg #{args.keg_id} not found.")
        sys.exit(1)
    beer = db.get_beer(keg.beer_id)
    db.set_tap(tap, args.keg_id)
    print(f"  {tap.upper()} tap → keg #{args.keg_id} ({beer.name if beer else '?'})")


def cmd_tap_clear(db: Database, args) -> None:
    tap = args.tap.lower()
    if tap not in ("left", "center", "right"):
        print("Tap must be: left, center, or right")
        sys.exit(1)
    db.set_tap(tap, None)
    print(f"  {tap.upper()} tap cleared.")


# ---------------------------------------------------------------------------
# User commands
# ---------------------------------------------------------------------------

def cmd_user_list(db: Database, _args) -> None:
    users = db.get_all_users()
    print(f"{'ID':>5}  {'Name':<28}  {'Photos':>7}  {'Encodings':>10}  {'Balance':>9}")
    print("─" * 70)
    for u in users:
        encodings = len(db.get_face_encodings_for_user(u.id))
        balance   = db.balance_for_user(u.id)
        bal_str   = f"${balance:+.2f}"
        print(f"{u.id:>5}  {u.name:<28}  {len(u.image_paths):>7}  {encodings:>10}  {bal_str:>9}")


def cmd_user_delete(db: Database, args) -> None:
    if args.id == UNKNOWN_USER_ID:
        print("Cannot delete the Unknown user.")
        return
    user = db.get_user(args.id)
    if not user:
        print(f"User #{args.id} not found.")
        return
    confirm = input(f"Delete user '{user.name}'? [y/N] ").strip().lower()
    if confirm == "y":
        db.delete_face_encodings_for_user(args.id)
        db.delete_user(args.id)
        print(f"Deleted user #{args.id}.")


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def cmd_stats(db: Database, _args) -> None:
    import time
    week_ago = time.time() - 7 * 86400

    all_pours   = db.get_all_pours()
    week_pours  = db.get_pours_since(week_ago)
    all_users   = db.get_all_users()
    real_users  = [u for u in all_users if u.id != UNKNOWN_USER_ID]
    taps        = db.get_tap_assignments()

    print("── SmartKegerator Stats ──────────────────────────────")
    print(f"  Total pours (all time): {len(all_pours)}")
    print(f"  Pours this week:        {len(week_pours)}")
    if all_pours:
        total_oz = sum(p.ounces for p in all_pours)
        total_$  = sum(p.price  for p in all_pours)
        print(f"  Total volume:           {total_oz:.1f} oz  ({total_oz/33.814:.2f} L)")
        print(f"  Total charged:          ${total_$:.2f}")
    print(f"  Registered users:       {len(real_users)}")
    print("")
    print("── Taps ──────────────────────────────────────────────")
    cmd_tap_status(db, None)
    print("")
    print("── Balances ──────────────────────────────────────────")
    for u in real_users:
        bal = db.balance_for_user(u.id)
        indicator = "←" if bal > 0 else " "
        print(f"  {u.name:<28}  ${bal:+.2f}  {indicator}")


# ---------------------------------------------------------------------------
# Payment commands
# ---------------------------------------------------------------------------

def cmd_payment_add(db: Database, args) -> None:
    user = db.get_user(args.user_id)
    if not user:
        print(f"User #{args.user_id} not found.")
        sys.exit(1)
    payment = db.add_payment(args.user_id, args.amount)
    balance = db.balance_for_user(args.user_id)
    print(f"Recorded ${args.amount:.2f} payment for {user.name}.")
    print(f"New balance: ${balance:+.2f}")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="manage",
        description="SmartKegerator management CLI",
    )
    parser.add_argument("--config", help="Path to config.yaml (auto-detected if omitted)")

    sub = parser.add_subparsers(dest="command", required=True)

    # ── beer ─────────────────────────────────────────────────────────────
    beer_p  = sub.add_parser("beer", help="Manage beers")
    beer_s  = beer_p.add_subparsers(dest="subcommand", required=True)

    beer_s.add_parser("list", help="List all beers")

    beer_add = beer_s.add_parser("add", help="Add a beer")
    beer_add.add_argument("--name",     required=True)
    beer_add.add_argument("--company",  default="")
    beer_add.add_argument("--location", default="")
    beer_add.add_argument("--style",    default="")
    beer_add.add_argument("--abv",      type=float, default=0.0)
    beer_add.add_argument("--ibu",      type=int,   default=0)

    beer_del = beer_s.add_parser("delete", help="Delete a beer")
    beer_del.add_argument("--id", type=int, required=True)

    # ── keg ──────────────────────────────────────────────────────────────
    keg_p = sub.add_parser("keg", help="Manage kegs")
    keg_s = keg_p.add_subparsers(dest="subcommand", required=True)

    keg_s.add_parser("list", help="List all kegs")

    keg_add = keg_s.add_parser("add", help="Add a keg")
    keg_add.add_argument("--beer-id",     type=int,   required=True,  dest="beer_id")
    keg_add.add_argument("--capacity",    type=float, required=True,  help="Liters (e.g. 19.5 for 1/6 bbl)")
    keg_add.add_argument("--price",       type=float, required=True,  help="Total cost in dollars")
    keg_add.add_argument("--date",        default=None,               help="Date tapped (YYYY-MM-DD, default: today)")
    keg_add.add_argument("--warmest-temp",type=float, default=0.0,    dest="warmest_temp")

    keg_del = keg_s.add_parser("delete", help="Delete a keg")
    keg_del.add_argument("--id", type=int, required=True)

    # ── tap ──────────────────────────────────────────────────────────────
    tap_p = sub.add_parser("tap", help="Manage tap assignments")
    tap_s = tap_p.add_subparsers(dest="subcommand", required=True)

    tap_s.add_parser("status", help="Show current tap assignments")

    tap_set = tap_s.add_parser("set", help="Assign a keg to a tap")
    tap_set.add_argument("tap", choices=["left", "center", "right"])
    tap_set.add_argument("--keg-id", type=int, required=True, dest="keg_id")

    tap_clr = tap_s.add_parser("clear", help="Remove a keg from a tap")
    tap_clr.add_argument("tap", choices=["left", "center", "right"])

    # ── user ─────────────────────────────────────────────────────────────
    user_p = sub.add_parser("user", help="Manage users")
    user_s = user_p.add_subparsers(dest="subcommand", required=True)

    user_s.add_parser("list", help="List all users with balances")

    user_del = user_s.add_parser("delete", help="Delete a user")
    user_del.add_argument("--id", type=int, required=True)

    # ── payment ──────────────────────────────────────────────────────────
    pay_p = sub.add_parser("payment", help="Record a payment")
    pay_s = pay_p.add_subparsers(dest="subcommand", required=True)

    pay_add = pay_s.add_parser("add", help="Record a payment from a user")
    pay_add.add_argument("--user-id", type=int,   required=True, dest="user_id")
    pay_add.add_argument("--amount",  type=float, required=True)

    # ── stats ─────────────────────────────────────────────────────────────
    sub.add_parser("stats", help="Show summary statistics")

    return parser


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

_DISPATCH = {
    ("beer",    "list"):   cmd_beer_list,
    ("beer",    "add"):    cmd_beer_add,
    ("beer",    "delete"): cmd_beer_delete,
    ("keg",     "list"):   cmd_keg_list,
    ("keg",     "add"):    cmd_keg_add,
    ("keg",     "delete"): cmd_keg_delete,
    ("tap",     "status"): cmd_tap_status,
    ("tap",     "set"):    cmd_tap_set,
    ("tap",     "clear"):  cmd_tap_clear,
    ("user",    "list"):   cmd_user_list,
    ("user",    "delete"): cmd_user_delete,
    ("payment", "add"):    cmd_payment_add,
    ("stats",   None):     cmd_stats,
}


def main() -> None:
    parser = build_parser()
    args   = parser.parse_args()
    db     = _load_db(args.config)

    subcommand = getattr(args, "subcommand", None)
    handler    = _DISPATCH.get((args.command, subcommand))

    if handler is None:
        parser.print_help()
        sys.exit(1)

    handler(db, args)


if __name__ == "__main__":
    main()
