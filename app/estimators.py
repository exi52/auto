from __future__ import annotations

from datetime import date
from math import floor
import re

from app.config import Settings
from app.models import CostEstimate, Lot, MarketEstimate


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


def estimate_lot(lot: Lot, settings: Settings, market: MarketEstimate | None = None) -> CostEstimate:
    bid = lot.current_bid
    auction_fee = get_auction_fee(bid)
    inland = settings.default_inland_shipping_usd
    ocean = settings.default_ocean_shipping_usd
    repair_low, repair_base, repair_high, parts = get_repair_profile(lot.damage, lot.run_and_drive)
    electric = is_electric_lot(lot)
    customs_base = estimate_ukraine_customs(
        bid=bid,
        auction_fee=auction_fee,
        shipping=inland + ocean,
        engine_cc=lot.engine_cc or 2000,
        year=lot.year,
        electric=electric,
        battery_kwh=estimate_battery_kwh(lot) if electric else None,
    )
    customs_low = customs_base * 0.9
    customs_high = customs_base * 1.15

    fixed = bid + auction_fee + inland + ocean + settings.broker_fee_usd + settings.service_fee_usd
    total_low = fixed + customs_low + repair_low
    total_base = fixed + customs_base + repair_base
    total_high = fixed + customs_high + repair_high

    risk_notes = build_risk_notes(lot, market)
    potential_profit_low = None
    potential_profit_base = None
    potential_profit_high = None
    roi_pct = None
    max_profitable_bid = None
    deal_rating = "UNKNOWN"

    if market:
        max_profitable_bid = calculate_max_profitable_bid(
            lot=lot,
            market=market,
            settings=settings,
            repair_base=repair_base,
        )
        recommended_high = floor(max_profitable_bid / 100) * 100
        recommended_low = max(0.0, recommended_high - 500)
        if bid <= recommended_high:
            recommended_low = max(bid, recommended_low)
        else:
            recommended_low = recommended_high

        sale_low = market.low_usd * (1 - settings.market_negotiation_discount_pct / 100)
        sale_high = market.high_usd * (1 - settings.market_negotiation_discount_pct / 100)
        potential_profit_low = sale_low - total_high
        potential_profit_base = market.expected_sale_usd - total_base
        potential_profit_high = sale_high - total_low
        roi_pct = (potential_profit_base / total_base * 100) if total_base else None
        deal_rating = rate_deal(
            current_bid=bid,
            max_profitable_bid=max_profitable_bid,
            profit=potential_profit_base,
            roi_pct=roi_pct or 0.0,
            expected_sale=market.expected_sale_usd,
            settings=settings,
        )
    else:
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
        market=market,
        potential_profit_low=potential_profit_low,
        potential_profit_base=potential_profit_base,
        potential_profit_high=potential_profit_high,
        roi_pct=roi_pct,
        max_profitable_bid=max_profitable_bid,
        deal_rating=deal_rating,
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


def estimate_ukraine_customs(
    bid: float,
    auction_fee: float,
    shipping: float,
    engine_cc: int,
    year: int | None,
    electric: bool = False,
    battery_kwh: float | None = None,
) -> float:
    customs_value = bid + auction_fee + shipping
    if electric:
        # In 2026 EV import duty is 0%, excise is EUR 1/kWh, and standard 20% VAT applies.
        excise = (battery_kwh or 75) * EUR_TO_USD
        vat = (customs_value + excise) * 0.20
        return excise + vat

    vehicle_age = max(1, min(15, date.today().year - year)) if year else 7
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


def calculate_max_profitable_bid(
    lot: Lot,
    market: MarketEstimate,
    settings: Settings,
    repair_base: float,
) -> float:
    target_profit = max(
        settings.target_profit_min_usd,
        market.expected_sale_usd * settings.target_profit_margin_pct / 100,
    )
    risk_reserve = estimate_risk_reserve(lot, market)
    max_total_cost = market.expected_sale_usd - target_profit - risk_reserve
    if max_total_cost <= 0:
        return 0.0

    low = 0.0
    high = market.expected_sale_usd
    for _ in range(40):
        candidate = (low + high) / 2
        total = estimate_total_at_bid(candidate, lot, settings, repair_base)
        if total <= max_total_cost:
            low = candidate
        else:
            high = candidate
    return max(0.0, floor(low / 100) * 100.0)


def estimate_total_at_bid(bid: float, lot: Lot, settings: Settings, repair_base: float) -> float:
    auction_fee = get_auction_fee(bid)
    shipping = settings.default_inland_shipping_usd + settings.default_ocean_shipping_usd
    customs = estimate_ukraine_customs(
        bid=bid,
        auction_fee=auction_fee,
        shipping=shipping,
        engine_cc=lot.engine_cc or 2000,
        year=lot.year,
        electric=is_electric_lot(lot),
        battery_kwh=estimate_battery_kwh(lot) if is_electric_lot(lot) else None,
    )
    return (
        bid
        + auction_fee
        + shipping
        + customs
        + repair_base
        + settings.broker_fee_usd
        + settings.service_fee_usd
    )


def estimate_risk_reserve(lot: Lot, market: MarketEstimate) -> float:
    reserve = 0.0
    if market.confidence == "low":
        reserve += 800
    elif market.confidence == "medium":
        reserve += 350

    damage = (lot.damage or "").upper()
    if any(key in damage for key in ("FLOOD", "FIRE", "ROLLOVER", "MECHANICAL")):
        reserve += 1500
    if lot.run_and_drive is False:
        reserve += 700
    elif lot.run_and_drive is None:
        reserve += 300
    if not lot.engine_cc:
        reserve += 400
    if not lot.vin:
        reserve += 300
    return reserve


def is_electric_lot(lot: Lot) -> bool:
    text = " ".join(
        str(value)
        for value in (
            lot.make,
            lot.model,
            lot.title,
            lot.engine,
            lot.raw.get("fuel"),
            lot.raw.get("fuel_type"),
        )
        if value
    ).upper()
    if any(marker in text for marker in ("ELECTRIC", "BATTERY EV", " BEV")):
        return True
    make = (lot.make or "").upper()
    if make in {"TESLA", "RIVIAN", "LUCID", "POLESTAR"}:
        return True
    electric_models = (
        "NISSAN LEAF",
        "CHEVROLET BOLT",
        "FORD MUSTANG MACH E",
        "FORD F 150 LIGHTNING",
        "HYUNDAI IONIQ 5",
        "HYUNDAI IONIQ 6",
        "KIA EV6",
        "KIA EV9",
        "VOLKSWAGEN ID 4",
        "AUDI E TRON",
        "BMW I3",
        "BMW I4",
        "BMW I5",
        "BMW I7",
        "BMW IX",
        "MERCEDES BENZ EQ",
    )
    normalized = re.sub(r"[^A-Z0-9]+", " ", text)
    return any(model in normalized for model in electric_models)


def estimate_battery_kwh(lot: Lot) -> float:
    text = " ".join(str(value) for value in (lot.title, lot.engine) if value)
    match = re.search(r"(\d+(?:\.\d+)?)\s*KWH", text, re.IGNORECASE)
    return float(match.group(1)) if match else 75.0


def rate_deal(
    current_bid: float,
    max_profitable_bid: float,
    profit: float,
    roi_pct: float,
    expected_sale: float,
    settings: Settings,
) -> str:
    target_profit = max(settings.target_profit_min_usd, expected_sale * settings.target_profit_margin_pct / 100)
    if current_bid > max_profitable_bid or profit <= 0:
        return "SKIP"
    if profit >= target_profit * 1.5 and roi_pct >= 20:
        return "STRONG"
    if profit >= target_profit and roi_pct >= 12:
        return "GOOD"
    return "MARGINAL"


def build_risk_notes(lot: Lot, market: MarketEstimate | None = None) -> list[str]:
    notes: list[str] = []
    damage = (lot.damage or "").upper()
    if any(key in damage for key in ("FLOOD", "FIRE", "ROLLOVER")):
        notes.append("high-risk damage type")
    if lot.run_and_drive is False:
        notes.append("not marked as run and drive")
    if not lot.vin:
        notes.append("VIN missing, decode/spec check unavailable")
    if not lot.engine_cc and not is_electric_lot(lot):
        notes.append("engine size missing, customs estimate uses 2.0L fallback")
    if is_electric_lot(lot) and not re.search(r"\d+(?:\.\d+)?\s*KWH", " ".join((lot.title, lot.engine or "")), re.IGNORECASE):
        notes.append("battery capacity missing, EV customs estimate uses 75 kWh")
    if lot.current_bid <= 0:
        notes.append("current bid not found")
    if market is None:
        notes.append("Ukraine market unavailable; bid cap is fallback-only")
    elif market.confidence == "low":
        notes.append("low market confidence; extra reserve added")
    return notes
