from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

UNKNOWN_USER_ID = -1
OUNCES_PER_LITER = 33.814


@dataclass
class Beer:
    id: int
    name: str
    company: str
    location: str
    style: str      # "type" in the original — renamed to avoid Python keyword
    abv: float
    ibu: int
    description: str = ""
    catalog_id: Optional[str] = None
    label_url: str = ""

    @property
    def logo_filename(self) -> str:
        return f"{self.name}.png"


@dataclass
class Keg:
    id: int
    beer_id: int
    date_bought: datetime
    liters_capacity: float
    price: float
    warmest_temp: float
    liters_poured:   float = 0.0    # populated by DB from pours table on load
    initial_fill_pct: float = 100.0  # % full when first tapped (0–100)

    @property
    def liters_offset(self) -> float:
        """Liters already consumed before tracking started (from initial fill < 100%)."""
        return self.liters_capacity * (1.0 - max(0.0, min(100.0, self.initial_fill_pct)) / 100.0)

    @property
    def price_per_liter(self) -> float:
        return self.price / self.liters_capacity if self.liters_capacity > 0 else 0.0

    @property
    def liters_remaining(self) -> float:
        return max(0.0, self.liters_capacity - self.liters_offset - self.liters_poured)

    @property
    def percent_remaining(self) -> float:
        if self.liters_capacity <= 0:
            return 0.0
        return (self.liters_remaining / self.liters_capacity) * 100.0

    def price_for_ounces(self, ounces: float) -> float:
        liters = ounces / OUNCES_PER_LITER
        return liters * self.price_per_liter


@dataclass
class User:
    id: int
    name: str
    image_paths: list[str] = field(default_factory=list)


@dataclass
class Pour:
    id: int
    time: float             # unix timestamp
    keg_id: int
    user_id: int
    ticks: int
    ounces: float
    price: float
    price_modifier: float = 1.0

    @property
    def poured_at(self) -> datetime:
        return datetime.fromtimestamp(self.time)

    @property
    def liters(self) -> float:
        return self.ounces / OUNCES_PER_LITER


@dataclass
class Payment:
    id: int
    user_id: int
    time: float             # unix timestamp
    amount: float

    @property
    def paid_at(self) -> datetime:
        return datetime.fromtimestamp(self.time)


@dataclass
class TapAssignment:
    """Maps tap IDs (tap1–tap4) to keg IDs."""
    taps: dict[str, Optional[int]] = field(default_factory=dict)

    def get_keg_id(self, tap: str) -> Optional[int]:
        return self.taps.get(tap)

    def items(self):
        return self.taps.items()


def get_configured_taps(config: dict) -> list[tuple[str, str]]:
    """Return [(tap_id, display_name), ...] for all configured taps."""
    taps_cfg = config.get("taps", {})
    count    = min(int(taps_cfg.get("count", 3)), 4)
    result   = []
    for i in range(count):
        tap_id   = f"tap{i + 1}"
        tap_info = taps_cfg.get(tap_id, {})
        name     = tap_info.get("name", f"Tap {i + 1}") if isinstance(tap_info, dict) else f"Tap {i + 1}"
        result.append((tap_id, name))
    return result
