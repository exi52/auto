from __future__ import annotations

import html

from app.models import CostEstimate, Lot, SearchFilters


def money(value: float) -> str:
    return f"${value:,.0f}"


def signed_money(value: float) -> str:
    sign = "+" if value >= 0 else "-"
    return f"{sign}${abs(value):,.0f}"


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
    sale_date = html.escape(maybe(lot.sale_date))
    parts = ", ".join(estimate.parts_hint[:5])
    risks = "; ".join(estimate.risk_notes) if estimate.risk_notes else "standard auction risk"
    if estimate.market:
        market = estimate.market
        market_block = (
            f"<b>Ukraine market ({html.escape(market.source)})</b>\n"
            f"Comparable ads: <b>{market.sample_size}</b> | Confidence: <b>{html.escape(market.confidence)}</b>\n"
            f"Listing range: <b>{money(market.low_usd)} - {money(market.high_usd)}</b>\n"
            f"Median asking price: <b>{money(market.median_usd)}</b>\n"
            f"Likely sale after negotiation: <b>{money(market.expected_sale_usd)}</b>\n"
            f"Profit at current bid: <b>{signed_money(estimate.potential_profit_base or 0)}</b>"
            f" ({estimate.roi_pct or 0:.0f}% ROI)\n"
            f"Profit range: {signed_money(estimate.potential_profit_low or 0)} to "
            f"{signed_money(estimate.potential_profit_high or 0)}\n"
            f"Deal rating: <b>{html.escape(estimate.deal_rating)}</b>\n\n"
        )
        if estimate.bid > (estimate.max_profitable_bid or 0):
            bid_guidance = (
                f"Current bid: <b>{money(estimate.bid)}</b>\n"
                f"Smart maximum bid: <b>{money(estimate.max_profitable_bid or 0)}</b>\n"
                f"Decision: <b>SKIP - current bid is already above the safe cap</b>\n\n"
            )
        else:
            bid_guidance = (
                f"Current bid: <b>{money(estimate.bid)}</b>\n"
                f"Suggested bidding zone: <b>{money(estimate.recommended_bid_low)} - "
                f"{money(estimate.recommended_bid_high)}</b>\n"
                f"Smart maximum bid: <b>{money(estimate.max_profitable_bid or 0)}</b>\n\n"
            )
    else:
        market_block = ""
        bid_guidance = (
            f"Current bid: <b>{money(estimate.bid)}</b>\n"
            f"Fallback cap (no UA market): <b>{money(estimate.recommended_bid_low)} - "
            f"{money(estimate.recommended_bid_high)}</b>\n\n"
        )

    return (
        f"<b>{title}</b>\n"
        f"Damage: <b>{damage}</b> | Run & Drive: <b>{run_drive}</b>\n"
        f"Engine: <b>{engine}</b> | Odometer: <b>{odometer}</b>\n"
        f"Location: <b>{html.escape(maybe(lot.location))}</b>\n"
        f"Auction closes: <b>{sale_date}</b>\n\n"
        f"{market_block}"
        f"<b>Bid guidance</b>\n"
        f"{bid_guidance}"
        f"<b>Estimated landed cost</b>\n"
        f"Auction fee: {money(estimate.auction_fee)}\n"
        f"Shipping: {money(estimate.inland_shipping + estimate.ocean_shipping)}\n"
        f"Customs UA: {money(estimate.customs_low)} - {money(estimate.customs_high)}\n"
        f"Repair: {money(estimate.repair_low)} - {money(estimate.repair_high)}\n"
        f"Broker/service: {money(estimate.broker_fee + estimate.service_fee)}\n"
        f"<b>Total: {money(estimate.total_low)} - {money(estimate.total_high)}</b>\n\n"
        f"Likely parts: {html.escape(parts)}\n"
        f"Risks: {html.escape(risks)}\n"
        f"<i>Market prices are asking prices; customs and repair remain estimates.</i>"
    )
