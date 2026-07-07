from __future__ import annotations

import html

from app.models import CostEstimate, Lot, SearchFilters


def money(value: float) -> str:
    return f"${value:,.0f}"


def maybe(value: object, fallback: str = "-") -> str:
    return str(value) if value not in (None, "") else fallback


def format_filter(filters: SearchFilters) -> str:
    lines = [
        f"Make: <b>{html.escape(maybe(filters.make, 'Any'))}</b>",
        f"Model: <b>{html.escape(maybe(filters.model, 'Any'))}</b>",
        f"Year: <b>{maybe(filters.year_from, 'Any')} - {maybe(filters.year_to, 'Any')}</b>",
        f"Max bid: <b>{money(filters.price_max) if filters.price_max else 'Any'}</b>",
        f"Damage: <b>{html.escape(maybe(filters.damage, 'Any'))}</b>",
        f"Run & Drive only: <b>{'yes' if filters.run_and_drive_only else 'no'}</b>",
    ]
    return "\n".join(lines)


def format_lot_report(lot: Lot, estimate: CostEstimate) -> str:
    title = html.escape(lot.title)
    damage = html.escape(maybe(lot.damage))
    engine = html.escape(maybe(lot.engine or (f"{lot.engine_cc}cc" if lot.engine_cc else None)))
    odometer = f"{lot.odometer_miles:,} mi" if lot.odometer_miles else "-"
    run_drive = "yes" if lot.run_and_drive is True else "no" if lot.run_and_drive is False else "unknown"
    parts = ", ".join(estimate.parts_hint[:5])
    risks = "; ".join(estimate.risk_notes) if estimate.risk_notes else "standard auction risk"

    return (
        f"<b>{title}</b>\n"
        f"Damage: <b>{damage}</b> | Run & Drive: <b>{run_drive}</b>\n"
        f"Engine: <b>{engine}</b> | Odometer: <b>{odometer}</b>\n"
        f"Location: <b>{html.escape(maybe(lot.location))}</b>\n\n"
        f"<b>Bid guidance</b>\n"
        f"Current bid: <b>{money(estimate.bid)}</b>\n"
        f"Recommended next cap: <b>{money(estimate.recommended_bid_low)} - {money(estimate.recommended_bid_high)}</b>\n\n"
        f"<b>Estimated landed cost</b>\n"
        f"Auction fee: {money(estimate.auction_fee)}\n"
        f"Shipping: {money(estimate.inland_shipping + estimate.ocean_shipping)}\n"
        f"Customs UA: {money(estimate.customs_low)} - {money(estimate.customs_high)}\n"
        f"Repair: {money(estimate.repair_low)} - {money(estimate.repair_high)}\n"
        f"Broker/service: {money(estimate.broker_fee + estimate.service_fee)}\n"
        f"<b>Total: {money(estimate.total_low)} - {money(estimate.total_high)}</b>\n\n"
        f"Likely parts: {html.escape(parts)}\n"
        f"Risks: {html.escape(risks)}"
    )
