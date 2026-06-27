import httpx
import re

# ─────────────────────────────────────────────
#  Apify — скрапер bid.cars (Copart + IAAI)
#  Actor: lexis-solutions/bid-cars-scraper
# ─────────────────────────────────────────────

APIFY_ACTOR = "lexis-solutions~bid-cars-scraper"
APIFY_RUN_URL = f"https://api.apify.com/v2/acts/{APIFY_ACTOR}/run-sync-get-dataset-items"

# Базовый URL поиска на bid.cars — фильтры вшиваются в него
BID_CARS_BASE = "https://bid.cars/en/search/results?search-type=filters&status=All&type=Automobile"


def parse_engine_cc(text: str) -> int:
    """Объём двигателя: '2.3L' или '2300cc' → куб.см."""
    if not text:
        return 2000
    match = re.search(r"(\d+\.?\d*)\s*[Ll]", text)
    if match:
        return int(float(match.group(1)) * 1000)
    match = re.search(r"(\d{3,5})\s*cc", text, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return 2000


def build_search_url(make=None, year_from=None, year_to=None, price_max=None) -> str:
    """Строит URL поиска bid.cars с нужными фильтрами."""
    url = BID_CARS_BASE
    url += f"&make={make.capitalize() if make else 'All'}"
    url += f"&model=All"
    url += f"&year-from={year_from or 1990}"
    url += f"&year-to={year_to or 2026}"
    url += "&auction-type=All"
    return url


def fetch_from_apify(apify_token: str, search_url: str, max_lots: int = 20) -> list[dict]:
    """
    Запускает Apify актор и получает лоты в JSON.
    Возвращает сырые данные от Apify.
    """
    payload = {
        "startUrls": [{"url": search_url}],
        "maxItems": max_lots,
    }
    params = {"token": apify_token}

    try:
        resp = httpx.post(
            APIFY_RUN_URL,
            json=payload,
            params=params,
            timeout=120,  # Apify может работать до 2 минут
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.TimeoutException:
        print("[parser] Apify timeout — попробуй позже")
        return []
    except Exception as e:
        print(f"[parser] Ошибка Apify: {e}")
        return []


def normalize_lot(raw: dict) -> dict | None:
    """
    Приводит сырой лот от Apify к единому формату бота.
    Возвращает None если лот невалидный.
    """
    try:
        # bid.cars scraper отдаёт эти поля
        title = raw.get("title") or raw.get("name") or ""
        year  = raw.get("year") or raw.get("model_year") or 0
        make  = raw.get("make") or raw.get("brand") or title.split()[0] if title else ""
        damage = (
            raw.get("damage") or
            raw.get("primary_damage") or
            raw.get("damageType") or
            "UNKNOWN"
        )
        price = float(
            raw.get("currentBid") or
            raw.get("current_bid") or
            raw.get("price") or 0
        )
        engine_text = (
            raw.get("engine") or
            raw.get("engineSize") or
            raw.get("engine_size") or ""
        )
        engine_cc = parse_engine_cc(str(engine_text))

        lot_id = (
            str(raw.get("lotId") or raw.get("lot_id") or raw.get("id") or "")
        )
        url = raw.get("url") or raw.get("lotUrl") or raw.get("lot_url") or ""
        image_url = (
            raw.get("imageUrl") or
            raw.get("image_url") or
            raw.get("thumbnail") or ""
        )

        if not title or not url:
            return None

        return {
            "lot_id":    lot_id or url,
            "title":     title,
            "year":      int(year) if year else 0,
            "make":      make,
            "damage":    damage.upper(),
            "engine_cc": engine_cc,
            "price":     price,
            "url":       url,
            "image_url": image_url,
        }
    except Exception as e:
        print(f"[parser] Ошибка нормализации лота: {e}")
        return None


def fetch_lots(filters: dict | None = None, apify_token: str = "") -> list[dict]:
    """
    Главная функция. Получает лоты с bid.cars через Apify.
    filters: {make, year_from, year_to, price_max, damage}
    """
    if not apify_token:
        print("[parser] APIFY_TOKEN не задан!")
        return []

    f = filters or {}

    search_url = build_search_url(
        make=f.get("make"),
        year_from=f.get("year_from"),
        year_to=f.get("year_to"),
        price_max=f.get("price_max"),
    )

    print(f"[parser] Запрос к Apify: {search_url}")
    raw_lots = fetch_from_apify(apify_token, search_url, max_lots=20)
    print(f"[parser] Получено сырых лотов: {len(raw_lots)}")

    lots = []
    for raw in raw_lots:
        lot = normalize_lot(raw)
        if lot is None:
            continue

        # Фильтр по цене
        if f.get("price_max") and lot["price"] > f["price_max"]:
            continue

        # Фильтр по типу повреждения
        if f.get("damage") and f["damage"].upper() not in lot["damage"]:
            continue

        lots.append(lot)

    print(f"[parser] После фильтров: {len(lots)} лотов")
    return lots
