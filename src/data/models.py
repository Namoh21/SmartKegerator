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
    liters_poured: float = 0.0   # populated by DB from pours table on load

    @property
    def price_per_liter(self) -> float:
        return self.price / self.liters_capacity if self.liters_capacity > 0 else 0.0

    @property
    def liters_remaining(self) -> float:
        return max(0.0, self.liters_capacity - self.liters_poured)

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
    left_keg_id: Optional[int] = None
    center_keg_id: Optional[int] = None
    right_keg_id: Optional[int] = None
