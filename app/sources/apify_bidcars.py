from __future__ import annotations

import re
from datetime import date
from math import ceil
from typing import Any
from urllib.parse import urlencode

import httpx

from app.models import Lot, SearchFilters


BID_CARS_BASE = "https://bid.cars/en/search/results"


class ApifyBidCarsSource:
    def __init__(self, token: str, actor: str, extra_query: str = "") -> None:
        self.token = token
        self.actor = actor
        self.extra_query = extra_query
        self.run_url = f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"

    async def fetch_lots(self, filters: SearchFilters, max_items: int = 20) -> list[Lot]:
        search_url = build_search_url(filters, self.extra_query)
        max_items = max(1, min(int(max_items), 100))
        payload = build_actor_input(self.actor, search_url, max_items)
        headers = {"Authorization": f"Bearer {self.token}"}

        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(self.run_url, json=payload, headers=headers)
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise ApifySourceError(describe_apify_error(exc.response.status_code)) from exc
            try:
                data = response.json()
            except ValueError as exc:
                raise ApifySourceError("Apify returned an invalid JSON response.") from exc

        if isinstance(data, dict):
            raw_items = data.get("items") or data.get("data") or []
        elif isinstance(data, list):
            raw_items = data
        else:
            raw_items = []

        lots: list[Lot] = []
        lot_ids: set[str] = set()
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            lot = normalize_lot(raw)
            if lot and lot.lot_id not in lot_ids and matches_filters(lot, filters):
                lots.append(lot)
                lot_ids.add(lot.lot_id)
        return lots


class ApifySourceError(RuntimeError):
    pass


def describe_apify_error(status_code: int) -> str:
    if status_code in (401, 403):
        return (
            "Apify denied access to the actor. Check that APIFY_TOKEN is valid, "
            "the actor is available on your Apify account, and the actor subscription/payment is enabled."
        )
    if status_code == 404:
        return "Apify actor was not found. Check APIFY_ACTOR."
    if status_code == 408:
        return "Apify actor timed out. Try a smaller MAX_LOTS_PER_CHECK or another actor."
    return f"Apify request failed with HTTP {status_code}."


def build_actor_input(actor: str, search_url: str, max_items: int) -> dict[str, Any]:
    if actor == "shahidirfan~bid-cars-scraper":
        return {
            "url": search_url,
            "results_wanted": max_items,
            "max_pages": max(1, min(5, ceil(max_items / 20))),
            "proxyConfiguration": {
                "useApifyProxy": False,
                "apifyProxyGroups": [],
            },
        }
    return {
        "startUrls": [{"url": search_url}],
        "maxItems": max_items,
    }


def build_search_url(filters: SearchFilters, extra_query: str = "") -> str:
    params = {
        "search-type": "filters",
        "status": "All",
        "type": "Automobile",
        "make": _title_or_all(filters.make),
        "model": _title_or_all(filters.model),
        "year-from": filters.year_from or 1990,
        "year-to": filters.year_to or date.today().year + 1,
        "auction-type": "All",
    }
    query = urlencode(params)
    if extra_query:
        query += "&" + extra_query.lstrip("&?")
    return f"{BID_CARS_BASE}?{query}"


def normalize_lot(raw: dict[str, Any]) -> Lot | None:
    title = _pick_str(raw, "title", "title_short", "name", "vehicleName", "vehicle", "description")
    year = _pick_int(raw, "year", "modelYear", "model_year") or _year_from_title(title)
    make = _pick_str(raw, "make", "brand", "manufacturer")
    model = _pick_str(raw, "model")
    trim = _pick_str(raw, "trim", "series")

    if title and (not make or not model):
        guessed_make, guessed_model = _guess_make_model(title, year)
        make = make or guessed_make
        model = model or guessed_model

    damage = _pick_str(raw, "primaryDamage", "primary_damage", "damage", "damageType")
    secondary_damage = _pick_str(raw, "secondaryDamage", "secondary_damage")
    url = _pick_str(raw, "detailUrl", "lotUrl", "lot_url", "url", "link")
    if url and url.startswith("/"):
        url = "https://bid.cars" + url

    lot_id = _pick_str(raw, "lot", "lotId", "lot_id", "id", "stockNumber")
    if not lot_id and url:
        lot_id = url

    if not title:
        title = " ".join(part for part in [str(year or ""), make or "", model or "", trim or ""] if part).strip()
    if not title or not url or not lot_id:
        return None

    engine = _pick_str(raw, "engine", "engineSize", "engine_size") or _pick_nested_str(raw, "specs", "engine")
    return Lot(
        lot_id=str(lot_id),
        source="bid.cars/apify",
        title=title,
        year=year,
        make=make,
        model=model,
        trim=trim,
        vin=_pick_str(raw, "vin", "VIN"),
        engine=engine,
        engine_cc=parse_engine_cc(engine),
        odometer_miles=_pick_int(raw, "odometer", "odometerMiles", "mileage", "miles"),
        damage=damage.upper() if damage else None,
        secondary_damage=secondary_damage.upper() if secondary_damage else None,
        run_and_drive=parse_run_and_drive(raw),
        current_bid=_pick_money(
            raw,
            "currentBid",
            "current_bid",
            "prebidPrice",
            "prebid_price",
            "final_bid",
            "buy_now_price",
            "salePrice",
            "price",
            "bid",
        ),
        location=_pick_str(raw, "location", "yard", "auctionLocation"),
        sale_date=_pick_str(raw, "saleDate", "sale_date", "auctionDate", "prebid_close_time"),
        url=url,
        image_url=_pick_image(raw),
        raw=raw,
    )


def matches_filters(lot: Lot, filters: SearchFilters) -> bool:
    vehicle_text = " ".join(part for part in (lot.title, lot.make, lot.model, lot.trim) if part).lower()
    if filters.make and filters.make.lower() not in vehicle_text:
        return False
    if filters.model and filters.model.lower() not in vehicle_text:
        return False
    if filters.year_from and (lot.year is None or lot.year < filters.year_from):
        return False
    if filters.year_to and (lot.year is None or lot.year > filters.year_to):
        return False
    if filters.price_max and lot.current_bid and lot.current_bid > filters.price_max:
        return False
    if filters.damage and (not lot.damage or filters.damage.upper() not in lot.damage.upper()):
        return False
    if filters.run_and_drive_only and lot.run_and_drive is not True:
        return False
    return True


def parse_engine_cc(text: str | None) -> int | None:
    if not text:
        return None
    liter = re.search(r"(\d+(?:\.\d+)?)\s*[Ll]", text)
    if liter:
        return int(float(liter.group(1)) * 1000)
    cc = re.search(r"(\d{3,5})\s*cc", text, re.IGNORECASE)
    if cc:
        return int(cc.group(1))
    return None


def parse_run_and_drive(raw: dict[str, Any]) -> bool | None:
    direct = raw.get("runAndDrive", raw.get("runsDrives"))
    if isinstance(direct, bool):
        return direct
    text = " ".join(
        str(raw.get(key, ""))
        for key in ("highlights", "condition", "startCode", "start_code", "status")
    )
    upper = text.upper()
    if "RUN" in upper and "DRIVE" in upper:
        return True
    if "ENGINE START" in upper:
        return False
    return None


def _pick_nested_str(raw: dict[str, Any], parent: str, key: str) -> str | None:
    nested = raw.get(parent)
    if not isinstance(nested, dict):
        return None
    return _pick_str(nested, key)


def _pick_str(raw: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = raw.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned:
                return cleaned
        elif isinstance(value, (int, float)):
            return str(value)
    return None


def _pick_int(raw: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = raw.get(key)
        if value in (None, ""):
            continue
        if isinstance(value, int):
            return value
        match = re.search(r"\d+", str(value).replace(",", ""))
        if match:
            return int(match.group(0))
    return None


def _pick_money(raw: dict[str, Any], *keys: str) -> float:
    for key in keys:
        value = raw.get(key)
        if value in (None, ""):
            continue
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).replace(",", "")
        match = re.search(r"-?\d+(?:\.\d+)?", text)
        if match:
            return float(match.group(0))
    return 0.0


def _pick_image(raw: dict[str, Any]) -> str | None:
    direct = _pick_str(raw, "imageUrl", "image_url", "thumbnail", "photo")
    if direct:
        return direct
    images = raw.get("images") or raw.get("photos")
    if isinstance(images, list) and images:
        first = images[0]
        if isinstance(first, str):
            return first
        if isinstance(first, dict):
            return _pick_str(first, "url", "src", "imageUrl")
    return None


def _title_or_all(value: str | None) -> str:
    return value.strip().title() if value else "All"


def _year_from_title(title: str | None) -> int | None:
    if not title:
        return None
    match = re.search(r"\b(19|20)\d{2}\b", title)
    return int(match.group(0)) if match else None


def _guess_make_model(title: str, year: int | None) -> tuple[str | None, str | None]:
    words = re.sub(r"[^A-Za-z0-9 ]+", " ", title).split()
    if words and year and words[0] == str(year):
        words = words[1:]
    make = words[0] if len(words) >= 1 else None
    model = words[1] if len(words) >= 2 else None
    return make, model
