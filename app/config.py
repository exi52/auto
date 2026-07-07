import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    apify_token: str
    apify_actor: str
    check_interval_seconds: int
    max_lots_per_check: int
    bid_cars_extra_query: str
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

    return Settings(
        telegram_bot_token=telegram_token,
        apify_token=apify_token,
        apify_actor=os.getenv("APIFY_ACTOR", "lexis-solutions~bid-cars-scraper").strip(),
        check_interval_seconds=_int_env("CHECK_INTERVAL_SECONDS", 300),
        max_lots_per_check=_int_env("MAX_LOTS_PER_CHECK", 50),
        bid_cars_extra_query=os.getenv("BID_CARS_EXTRA_QUERY", "").strip(),
        database_path=os.getenv("DATABASE_PATH", "autoscout.sqlite3").strip(),
        default_ocean_shipping_usd=_float_env("DEFAULT_OCEAN_SHIPPING_USD", 1200),
        default_inland_shipping_usd=_float_env("DEFAULT_INLAND_SHIPPING_USD", 600),
        service_fee_usd=_float_env("SERVICE_FEE_USD", 500),
        broker_fee_usd=_float_env("BROKER_FEE_USD", 250),
    )
