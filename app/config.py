import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    apify_token: str
    apify_actor: str
    free_mvp_mode: bool
    check_interval_seconds: int
    max_lots_per_check: int
    bid_cars_extra_query: str
    autoria_api_key: str
    autoria_comparables_limit: int
    market_cache_hours: int
    market_negotiation_discount_pct: float
    target_profit_margin_pct: float
    target_profit_min_usd: float
    database_path: str
    default_ocean_shipping_usd: float
    default_inland_shipping_usd: float
    service_fee_usd: float
    broker_fee_usd: float


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer, got {value!r}") from exc


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number, got {value!r}") from exc


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise RuntimeError(f"{name} must be true/false, got {value!r}")


def load_settings() -> Settings:
    load_dotenv(Path(".env"))

    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    apify_token = os.getenv("APIFY_TOKEN", "").strip()

    missing = []
    if not telegram_token:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not apify_token:
        missing.append("APIFY_TOKEN")
    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(f"Missing required environment variable(s): {joined}. Copy .env.example to .env and fill them.")

    free_mvp_mode = _bool_env("FREE_MVP_MODE", True)
    check_interval_seconds = _int_env("CHECK_INTERVAL_SECONDS", 14400)
    max_lots_per_check = _int_env("MAX_LOTS_PER_CHECK", 10)
    autoria_comparables_limit = _int_env("AUTORIA_COMPARABLES_LIMIT", 5)
    market_cache_hours = _int_env("MARKET_CACHE_HOURS", 24)
    if free_mvp_mode:
        # 10 results every 4 hours is about 1,800 paid results per month.
        check_interval_seconds = max(check_interval_seconds, 14400)
        max_lots_per_check = min(max(max_lots_per_check, 1), 10)
        autoria_comparables_limit = min(max(autoria_comparables_limit, 3), 5)
        market_cache_hours = max(market_cache_hours, 24)

    return Settings(
        telegram_bot_token=telegram_token,
        apify_token=apify_token,
        apify_actor=os.getenv("APIFY_ACTOR", "shahidirfan~bid-cars-scraper").strip(),
        free_mvp_mode=free_mvp_mode,
        check_interval_seconds=check_interval_seconds,
        max_lots_per_check=max_lots_per_check,
        bid_cars_extra_query=os.getenv("BID_CARS_EXTRA_QUERY", "").strip(),
        autoria_api_key=os.getenv("AUTORIA_API_KEY", "").strip(),
        autoria_comparables_limit=autoria_comparables_limit,
        market_cache_hours=market_cache_hours,
        market_negotiation_discount_pct=_float_env("MARKET_NEGOTIATION_DISCOUNT_PCT", 7),
        target_profit_margin_pct=_float_env("TARGET_PROFIT_MARGIN_PCT", 15),
        target_profit_min_usd=_float_env("TARGET_PROFIT_MIN_USD", 1500),
        database_path=os.getenv("DATABASE_PATH", "autoscout.sqlite3").strip(),
        default_ocean_shipping_usd=_float_env("DEFAULT_OCEAN_SHIPPING_USD", 1200),
        default_inland_shipping_usd=_float_env("DEFAULT_INLAND_SHIPPING_USD", 600),
        service_fee_usd=_float_env("SERVICE_FEE_USD", 500),
        broker_fee_usd=_float_env("BROKER_FEE_USD", 250),
    )
