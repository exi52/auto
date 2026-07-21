from __future__ import annotations

import asyncio
import re
from dataclasses import asdict
from math import floor
from statistics import median
from typing import Any

import httpx

from app.models import Lot, MarketComparable, MarketEstimate
from app.storage import Storage


AUTORIA_API_BASE = "https://developers.ria.com"
AUTORIA_SITE_BASE = "https://auto.ria.com"
CACHE_NAMESPACE = "autoria_market_v1"


class AutoRiaMarketSource:
    def __init__(
        self,
        api_key: str,
        storage: Storage,
        comparables_limit: int = 5,
        cache_hours: int = 24,
        negotiation_discount_pct: float = 7,
    ) -> None:
        self.api_key = api_key.strip()
        self.storage = storage
        self.comparables_limit = max(3, min(comparables_limit, 10))
        self.cache_hours = max(1, cache_hours)
        self.negotiation_discount_pct = max(0.0, min(20.0, negotiation_discount_pct))
        self._marks: list[dict[str, Any]] | None = None
        self._models: dict[int, list[dict[str, Any]]] = {}
        self.last_status = "disabled" if not self.api_key else "ready"

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def estimate_market(self, lot: Lot) -> MarketEstimate | None:
        if not self.enabled:
            self.last_status = "disabled"
            return None
        if not lot.year or not lot.title:
            self.last_status = "missing vehicle data"
            return None

        async with httpx.AsyncClient(base_url=AUTORIA_API_BASE, timeout=20) as client:
            marks = await self._get_marks(client)
            mark = resolve_catalog_item(marks, lot.make, lot.title)
            if not mark:
                self.last_status = "make not mapped"
                return None

            mark_id = int(mark["value"])
            models = await self._get_models(client, mark_id)
            model = resolve_catalog_item(models, lot.model, lot.title)
            if not model:
                self.last_status = "model not mapped"
                return None

            model_id = int(model["value"])
            cache_key = build_market_cache_key(mark_id, model_id, lot.year, lot.engine_cc)
            cached = self.storage.get_cache(CACHE_NAMESPACE, cache_key)
            if cached:
                if cached.get("not_found"):
                    self.last_status = "cached: no comparables"
                    return None
                estimate = market_from_payload(cached)
                if estimate:
                    self.last_status = "cached"
                    return estimate

            search_params = build_search_params(lot, mark_id, model_id, self.comparables_limit)
            search_data = await self._request_json(client, "/auto/search", search_params)
            listing_ids = extract_listing_ids(search_data)
            if not listing_ids:
                self._cache_not_found(cache_key)
                self.last_status = "no listings"
                return None

            fetch_limit = min(len(listing_ids), max(8, self.comparables_limit * 2))
            tasks = [
                self._request_json(client, "/auto/info", {"auto_id": listing_id})
                for listing_id in listing_ids[:fetch_limit]
            ]
            details = await asyncio.gather(*tasks, return_exceptions=True)

        comparables: list[MarketComparable] = []
        hard_error: AutoRiaSourceError | None = None
        for listing_id, detail in zip(listing_ids[:fetch_limit], details):
            if isinstance(detail, AutoRiaSourceError):
                hard_error = hard_error or detail
                continue
            if isinstance(detail, BaseException) or not isinstance(detail, dict):
                continue
            comparable = normalize_comparable(str(listing_id), detail)
            if comparable:
                comparables.append(comparable)

        if not comparables and hard_error:
            raise hard_error

        estimate = calculate_market_estimate(
            lot=lot,
            make=str(mark["name"]),
            model=str(model["name"]),
            comparables=comparables,
            negotiation_discount_pct=self.negotiation_discount_pct,
        )
        if not estimate:
            self._cache_not_found(cache_key)
            self.last_status = "not enough comparable listings"
            return None

        self.storage.set_cache(CACHE_NAMESPACE, cache_key, asdict(estimate), self.cache_hours)
        self.last_status = "fetched"
        return estimate

    async def _get_marks(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        if self._marks is None:
            data = await self._request_json(client, "/auto/categories/1/marks")
            self._marks = catalog_items(data)
        return self._marks

    async def _get_models(self, client: httpx.AsyncClient, mark_id: int) -> list[dict[str, Any]]:
        if mark_id not in self._models:
            data = await self._request_json(client, f"/auto/categories/1/marks/{mark_id}/models")
            self._models[mark_id] = catalog_items(data)
        return self._models[mark_id]

    async def _request_json(
        self,
        client: httpx.AsyncClient,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        safe_params = dict(params or {})
        safe_params["api_key"] = self.api_key
        try:
            response = await client.get(path, params=safe_params)
        except httpx.TimeoutException as exc:
            raise AutoRiaSourceError("AUTO.RIA API timed out.") from exc
        except httpx.HTTPError as exc:
            raise AutoRiaSourceError("AUTO.RIA API network error.") from exc

        if response.status_code == 403:
            raise AutoRiaSourceError("AUTO.RIA rejected AUTORIA_API_KEY or this API is not enabled for the key.")
        if response.status_code == 429:
            raise AutoRiaSourceError("AUTO.RIA freemium request limit reached. Cached results will still work.")
        if response.status_code == 404:
            return {}
        if response.status_code >= 400:
            raise AutoRiaSourceError(f"AUTO.RIA API failed with HTTP {response.status_code}.")
        try:
            return response.json()
        except ValueError as exc:
            raise AutoRiaSourceError("AUTO.RIA returned invalid JSON.") from exc

    def _cache_not_found(self, cache_key: str) -> None:
        self.storage.set_cache(
            CACHE_NAMESPACE,
            cache_key,
            {"not_found": True},
            min(self.cache_hours, 6),
        )


class AutoRiaSourceError(RuntimeError):
    pass


def build_search_params(lot: Lot, mark_id: int, model_id: int, limit: int) -> dict[str, Any]:
    params: dict[str, Any] = {
        "category_id": 1,
        "marka_id[0]": mark_id,
        "model_id[0]": model_id,
        "s_yers[0]": max(1950, (lot.year or 2000) - 1),
        "po_yers[0]": min(2100, (lot.year or 2000) + 1),
        "currency": 1,
        "abroad": 2,
        "custom": 1,
        "status_id": 0,
        "searchType": 4,
        "countpage": min(20, max(8, limit * 2)),
        "page": 0,
        "order_by": 7,
    }
    if lot.engine_cc:
        liters = lot.engine_cc / 1000
        params["engineVolumeFrom"] = round(max(0.1, liters - 0.3), 1)
        params["engineVolumeTo"] = round(liters + 0.3, 1)
    return params


def extract_listing_ids(data: Any) -> list[str]:
    if not isinstance(data, dict):
        return []
    result = data.get("result")
    if not isinstance(result, dict):
        return []
    search_result = result.get("search_result")
    if not isinstance(search_result, dict):
        return []
    ids = search_result.get("ids")
    if not isinstance(ids, list):
        return []
    return [str(value) for value in ids if value not in (None, "")]


def normalize_comparable(listing_id: str, raw: dict[str, Any]) -> MarketComparable | None:
    auto_data = raw.get("autoData") if isinstance(raw.get("autoData"), dict) else {}
    if auto_data.get("active") is False or auto_data.get("isSold") is True or auto_data.get("fromArchive") is True:
        return None
    if raw.get("moderatedAbroad") is True or auto_data.get("custom") not in (None, 0, "0"):
        return None
    condition = raw.get("technicalCondition")
    if isinstance(condition, dict) and condition.get("id") in (3, 4, "3", "4"):
        return None

    price = parse_number(raw.get("USD"))
    if not price:
        prices = raw.get("prices")
        if isinstance(prices, list) and prices and isinstance(prices[0], dict):
            price = parse_number(prices[0].get("USD"))
    if price is None or price < 1500 or price > 250000:
        return None

    race = parse_number(auto_data.get("raceInt"))
    mileage_km = None if race is None else int(race * 1000 if race < 1000 else race)
    link = str(raw.get("linkToView") or "").strip()
    if link.startswith("/"):
        link = AUTORIA_SITE_BASE + link
    if not link:
        link = f"{AUTORIA_SITE_BASE}/auto_{listing_id}.html"

    year = parse_number(auto_data.get("year"))
    return MarketComparable(
        listing_id=listing_id,
        title=str(raw.get("title") or f"{raw.get('markName', '')} {raw.get('modelName', '')}").strip(),
        year=int(year) if year else None,
        price_usd=float(price),
        mileage_km=mileage_km,
        url=link,
    )


def calculate_market_estimate(
    lot: Lot,
    make: str,
    model: str,
    comparables: list[MarketComparable],
    negotiation_discount_pct: float,
) -> MarketEstimate | None:
    if len(comparables) < 3:
        return None

    selected = list(comparables)
    target_mileage_km = int(lot.odometer_miles * 1.60934) if lot.odometer_miles else None
    if target_mileage_km:
        tolerance = max(75000, int(target_mileage_km * 0.6))
        mileage_matches = [
            item
            for item in selected
            if item.mileage_km is None or abs(item.mileage_km - target_mileage_km) <= tolerance
        ]
        if len(mileage_matches) >= 3:
            selected = mileage_matches

    prices = sorted(item.price_usd for item in selected)
    if len(prices) >= 4:
        q1 = percentile(prices, 0.25)
        q3 = percentile(prices, 0.75)
        iqr = q3 - q1
        lower_bound = q1 - 1.5 * iqr
        upper_bound = q3 + 1.5 * iqr
        inliers = [item for item in selected if lower_bound <= item.price_usd <= upper_bound]
        if len(inliers) >= 3:
            selected = inliers
            prices = sorted(item.price_usd for item in selected)

    middle = float(median(prices))
    low = percentile(prices, 0.25)
    high = percentile(prices, 0.75)
    spread = (high - low) / middle if middle else 1.0
    if len(prices) >= 5 and spread <= 0.25:
        confidence = "high"
    elif len(prices) >= 4 and spread <= 0.40:
        confidence = "medium"
    else:
        confidence = "low"

    discount = max(0.0, min(20.0, negotiation_discount_pct)) / 100
    expected_sale = middle * (1 - discount)
    selected.sort(key=lambda item: (abs((item.year or lot.year or 0) - (lot.year or 0)), abs(item.price_usd - middle)))
    return MarketEstimate(
        source="AUTO.RIA",
        make=make,
        model=model,
        sample_size=len(prices),
        median_usd=round(middle, 2),
        low_usd=round(low, 2),
        high_usd=round(high, 2),
        expected_sale_usd=round(expected_sale, 2),
        confidence=confidence,
        comparables=selected[:5],
    )


def resolve_catalog_item(
    items: list[dict[str, Any]],
    hint: str | None,
    title: str,
) -> dict[str, Any] | None:
    valid = [item for item in items if item.get("name") and item.get("value") is not None]
    normalized_hint = normalize_name(hint or "")
    if normalized_hint:
        exact = [item for item in valid if normalize_name(str(item["name"])) == normalized_hint]
        if exact:
            return exact[0]

    normalized_title = normalize_name(title)
    matches = [
        item
        for item in valid
        if contains_normalized_name(normalized_title, normalize_name(str(item["name"])))
    ]
    if not matches:
        return None
    return max(matches, key=lambda item: len(normalize_name(str(item["name"]))))


def catalog_items(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def normalize_name(value: str) -> str:
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", value.upper()).split())


def contains_normalized_name(haystack: str, needle: str) -> bool:
    if not needle:
        return False
    return re.search(rf"(?:^| ){re.escape(needle)}(?: |$)", haystack) is not None


def parse_number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value).replace(" ", "").replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    return float(match.group(0)) if match else None


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * fraction
    lower = floor(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return float(ordered[lower] * (1 - weight) + ordered[upper] * weight)


def build_market_cache_key(mark_id: int, model_id: int, year: int, engine_cc: int | None) -> str:
    engine_bucket = round((engine_cc or 0) / 100) * 100
    return f"{mark_id}:{model_id}:{year}:{engine_bucket}"


def market_from_payload(payload: dict[str, Any]) -> MarketEstimate | None:
    try:
        comparable_rows = payload.get("comparables") or []
        comparables = [MarketComparable(**row) for row in comparable_rows if isinstance(row, dict)]
        return MarketEstimate(
            source=str(payload["source"]),
            make=str(payload["make"]),
            model=str(payload["model"]),
            sample_size=int(payload["sample_size"]),
            median_usd=float(payload["median_usd"]),
            low_usd=float(payload["low_usd"]),
            high_usd=float(payload["high_usd"]),
            expected_sale_usd=float(payload["expected_sale_usd"]),
            confidence=str(payload["confidence"]),
            comparables=comparables,
        )
    except (KeyError, TypeError, ValueError):
        return None
