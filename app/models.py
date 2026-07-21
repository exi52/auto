from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SearchFilters:
    make: str | None = None
    model: str | None = None
    year_from: int | None = None
    year_to: int | None = None
    price_max: float | None = None
    damage: str | None = None
    run_and_drive_only: bool = False


@dataclass
class Lot:
    lot_id: str
    source: str
    title: str
    year: int | None
    make: str | None
    model: str | None
    trim: str | None
    vin: str | None
    engine: str | None
    engine_cc: int | None
    odometer_miles: int | None
    damage: str | None
    secondary_damage: str | None
    run_and_drive: bool | None
    current_bid: float
    location: str | None
    sale_date: str | None
    url: str
    image_url: str | None
    raw: dict[str, Any] = field(repr=False, default_factory=dict)


@dataclass
class MarketComparable:
    listing_id: str
    title: str
    year: int | None
    price_usd: float
    mileage_km: int | None
    url: str


@dataclass
class MarketEstimate:
    source: str
    make: str
    model: str
    sample_size: int
    median_usd: float
    low_usd: float
    high_usd: float
    expected_sale_usd: float
    confidence: str
    comparables: list[MarketComparable] = field(default_factory=list)


@dataclass
class CostEstimate:
    bid: float
    recommended_bid_low: float
    recommended_bid_high: float
    auction_fee: float
    inland_shipping: float
    ocean_shipping: float
    customs_low: float
    customs_base: float
    customs_high: float
    repair_low: float
    repair_base: float
    repair_high: float
    broker_fee: float
    service_fee: float
    total_low: float
    total_base: float
    total_high: float
    parts_hint: list[str]
    risk_notes: list[str]
    market: MarketEstimate | None = None
    potential_profit_low: float | None = None
    potential_profit_base: float | None = None
    potential_profit_high: float | None = None
    roi_pct: float | None = None
    max_profitable_bid: float | None = None
    deal_rating: str = "UNKNOWN"
