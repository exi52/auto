from __future__ import annotations

from datetime import date

from app.config import Settings
from app.models import CostEstimate, Lot


AUCTION_FEE_TIERS = [
    (0, 99, 25),
    (100, 499, 75),
    (500, 999, 125),
    (1000, 1499, 170),
    (1500, 1999, 195),
    (2000, 2999, 240),
    (3000, 3999, 290),
    (4000, 4999, 340),
    (5000, 7499, 440),
    (7500, 9999, 540),
    (10000, 14999, 650),
    (15000, 999999, 850),
]

REPAIR_PROFILES = {
    "FRONT END": (900, 1800, 3500, ["front bumper", "hood", "headlights", "radiator support"]),
    "REAR END": (700, 1500, 3000, ["rear bumper", "trunk lid", "tail lights", "rear panel"]),
    "SIDE": (700, 1600, 3200, ["door", "fender", "quarter panel", "side glass"]),
    "MINOR DENT": (250, 700, 1400, ["paintless dent repair", "paint work"]),
    "HAIL": (700, 1800, 3500, ["body panels", "glass check", "paint work"]),
    "MECHANICAL": (1200, 2800, 6000, ["engine/transmission diagnostics", "fluids", "labor"]),
    "FLOOD": (2500, 5500, 12000, ["electronics", "interior", "control modules"]),
    "FIRE": (3500, 7500, 15000, ["wiring", "engine bay parts", "interior plastics"]),
    "ROLLOVER": (3500, 8000, 18000, ["roof", "pillars", "airbags", "structural repair"]),
}

EUR_TO_USD = 1.09


def estimate_lot(lot: Lot, settings: Settings) -> CostEstimate:
    bid = lot.current_bid
    auction_fee = get_auction_fee(bid)
    inland = settings.default_inland_shipping_usd
    ocean = settings.default_ocean_shipping_usd
    repair_low, repair_base, repair_high, parts = get_repair_profile(lot.damage, lot.run_and_drive)
    customs_base = estimate_ukraine_customs(
        bid=bid,
        auction_fee=auction_fee,
        shipping=inland + ocean,
        engine_cc=lot.engine_cc or 2000,
        year=lot.year,
    )
    customs_low = customs_base * 0.9
    customs_high = customs_base * 1.15

    fixed = bid + auction_fee + inland + ocean + settings.broker_fee_usd + settings.service_fee_usd
    total_low = fixed + customs_low + repair_low
    total_base = fixed + customs_base + repair_base
    total_high = fixed + customs_high + repair_high

    risk_notes = build_risk_notes(lot)
    recommended_low, recommended_high = recommend_bid_range(bid, lot.damage)

    return CostEstimate(
        bid=bid,
        recommended_bid_low=recommended_low,
        recommended_bid_high=recommended_high,
        auction_fee=auction_fee,
        inland_shipping=inland,
        ocean_shipping=ocean,
        customs_low=customs_low,
        customs_base=customs_base,
        customs_high=customs_high,
        repair_low=repair_low,
        repair_base=repair_base,
        repair_high=repair_high,
        broker_fee=settings.broker_fee_usd,
        service_fee=settings.service_fee_usd,
        total_low=total_low,
        total_base=total_base,
        total_high=total_high,
        parts_hint=parts,
        risk_notes=risk_notes,
    )


def get_auction_fee(bid: float) -> float:
    for low, high, fee in AUCTION_FEE_TIERS:
        if low <= bid <= high:
            return float(fee)
    return 850.0


def get_repair_profile(damage: str | None, run_and_drive: bool | None) -> tuple[float, float, float, list[str]]:
    damage_upper = (damage or "").upper()
    for key, profile in REPAIR_PROFILES.items():
        if key in damage_upper:
            low, base, high, parts = profile
            if run_and_drive is True and key not in {"FLOOD", "FIRE", "ROLLOVER"}:
                return low * 0.85, base * 0.9, high, parts
            return float(low), float(base), float(high), parts
    return 700.0, 1600.0, 3500.0, ["manual inspection required"]


def estimate_ukraine_customs(bid: float, auction_fee: float, shipping: float, engine_cc: int, year: int | None) -> float:
    vehicle_age = max(1, min(15, date.today().year - year)) if year else 7
    customs_value = bid + auction_fee + shipping
    duty = customs_value * 0.10
    excise_base_eur = 50 if engine_cc <= 3000 else 100
    excise = excise_base_eur * (engine_cc / 1000) * vehicle_age * EUR_TO_USD
    vat = (customs_value + duty + excise) * 0.20
    return duty + excise + vat


def recommend_bid_range(current_bid: float, damage: str | None) -> tuple[float, float]:
    if current_bid <= 0:
        return 0.0, 0.0
    damage_upper = (damage or "").upper()
    multiplier = 1.12
    if any(key in damage_upper for key in ("FLOOD", "FIRE", "ROLLOVER", "MECHANICAL")):
        multiplier = 1.05
    high = round((current_bid * multiplier) / 100) * 100
    low = max(current_bid, high - 500)
    return low, high


def build_risk_notes(lot: Lot) -> list[str]:
    notes: list[str] = []
    damage = (lot.damage or "").upper()
    if any(key in damage for key in ("FLOOD", "FIRE", "ROLLOVER")):
        notes.append("high-risk damage type")
    if lot.run_and_drive is False:
        notes.append("not marked as run and drive")
    if not lot.vin:
        notes.append("VIN missing, decode/spec check unavailable")
    if not lot.engine_cc:
        notes.append("engine size missing, customs estimate uses 2.0L fallback")
    if lot.current_bid <= 0:
        notes.append("current bid not found")
    return notes
