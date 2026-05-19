"""Shared calculation helpers used across web routes."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Request

from data.database import Database
from data.models import Beer, Keg, UNKNOWN_USER_ID

OUNCES_PER_LITER = 33.814

# Touchscreen GUI writes gui_heartbeat_ts periodically; web treats stale after 90 s.
GUI_HEARTBEAT_KEY = "gui_heartbeat_ts"
GUI_HEARTBEAT_STALE_SECS = 90


def is_admin_session(request: Request) -> bool:
    try:
        return bool(request.session.get("admin_username"))
    except Exception:
        return False


def require_login_for_read(config: dict) -> bool:
    return bool(config.get("web", {}).get("require_login_for_read", False))


def kiosk_status(db: Database) -> dict:
    """Return touchscreen app online state from the last GUI heartbeat."""
    raw = db.get_setting(GUI_HEARTBEAT_KEY, "")
    try:
        ts = float(raw) if raw else 0.0
    except ValueError:
        ts = 0.0
    now = time.time()
    online = ts > 0 and (now - ts) <= GUI_HEARTBEAT_STALE_SECS
    return {
        "online":       online,
        "last_seen":    datetime.fromtimestamp(ts) if ts > 0 else None,
        "stale_seconds": int(now - ts) if ts > 0 else None,
    }
PINT_OZ          = 16.0
RATE_LOOKBACK_DAYS = 14   # days of history used to estimate pour rate


@dataclass
class KegStats:
    keg:              Keg
    beer:             Optional[Beer]
    tap:              Optional[str]          # "left" / "center" / "right" / None
    cost_per_oz:      float
    cost_per_pint:    float
    oz_remaining:     float
    oz_poured_total:  float
    pour_rate_oz_day: float                  # oz/day based on recent history
    days_remaining:   Optional[float]
    est_empty_date:   Optional[datetime]
    pours_today:      int
    pours_this_week:  int


def keg_stats(db: Database, keg: Keg, tap: Optional[str] = None) -> KegStats:
    beer       = db.get_beer(keg.beer_id)
    all_pours  = db.get_pours_for_keg(keg.id)

    now        = time.time()
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    week_start  = now - 7 * 86400
    lookback    = now - RATE_LOOKBACK_DAYS * 86400

    oz_poured_total = sum(p.ounces for p in all_pours)
    oz_remaining    = max(0.0, keg.liters_capacity * OUNCES_PER_LITER - oz_poured_total)
    pours_today     = sum(1 for p in all_pours if p.time >= today_start)
    pours_week      = sum(1 for p in all_pours if p.time >= week_start)

    # Pour rate from recent history
    recent_oz = sum(p.ounces for p in all_pours if p.time >= lookback)
    pour_rate = recent_oz / RATE_LOOKBACK_DAYS   # oz/day

    days_remaining: Optional[float]  = None
    est_empty:      Optional[datetime] = None
    if pour_rate > 0.5:   # at least half an oz per day average
        days_remaining = oz_remaining / pour_rate
        est_empty      = datetime.now() + timedelta(days=days_remaining)

    cost_per_oz   = keg.price / (keg.liters_capacity * OUNCES_PER_LITER) if keg.liters_capacity > 0 else 0.0
    cost_per_pint = cost_per_oz * PINT_OZ

    return KegStats(
        keg=keg,
        beer=beer,
        tap=tap,
        cost_per_oz=cost_per_oz,
        cost_per_pint=cost_per_pint,
        oz_remaining=oz_remaining,
        oz_poured_total=oz_poured_total,
        pour_rate_oz_day=pour_rate,
        days_remaining=days_remaining,
        est_empty_date=est_empty,
        pours_today=pours_today,
        pours_this_week=pours_week,
    )


@dataclass
class UserStats:
    user_id:        int
    name:           str
    photo_url:      Optional[str]
    total_charged:  float
    total_paid:     float
    balance:        float
    pour_count:     int
    oz_total:       float
    favorite_beer:  Optional[str]
    last_pour_at:   Optional[datetime]


def user_stats(db: Database, user_id: int, photos_url_prefix: str = "/users/photos") -> UserStats:
    user   = db.get_user(user_id)
    pours  = db.get_pours_for_user(user_id)
    balance = db.balance_for_user(user_id)

    oz_total      = sum(p.ounces for p in pours)
    total_charged = sum(p.price  for p in pours)
    payments      = db.get_payments_for_user(user_id)
    total_paid    = sum(pay.amount for pay in payments)

    # Favorite beer: most-poured keg's beer
    keg_counts: dict[int, float] = {}
    for p in pours:
        keg_counts[p.keg_id] = keg_counts.get(p.keg_id, 0.0) + p.ounces
    favorite_beer: Optional[str] = None
    if keg_counts:
        top_keg_id = max(keg_counts, key=keg_counts.get)
        keg = db.get_keg(top_keg_id)
        if keg:
            beer = db.get_beer(keg.beer_id)
            favorite_beer = beer.name if beer else None

    last_pour_at: Optional[datetime] = None
    if pours:
        last_pour_at = datetime.fromtimestamp(max(p.time for p in pours))

    # Find first photo
    photo_url: Optional[str] = None
    if user and user.image_paths:
        p = user.image_paths[0]
        # Convert absolute path to URL: /users/photos/{user_id}/{filename}
        photo_url = f"{photos_url_prefix}/{user_id}/{__import__('pathlib').Path(p).name}"

    return UserStats(
        user_id=user_id,
        name=user.name if user else "Unknown",
        photo_url=photo_url,
        total_charged=total_charged,
        total_paid=total_paid,
        balance=balance,
        pour_count=len(pours),
        oz_total=oz_total,
        favorite_beer=favorite_beer,
        last_pour_at=last_pour_at,
    )
