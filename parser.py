import httpx
from bs4 import BeautifulSoup
import re


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def parse_engine_cc(text: str) -> int:
    """Вытаскивает объём двигателя в куб.см из строки типа '2.3L' или '2300cc'."""
    if not text:
        return 2000  # дефолт

    # Формат "2.3L" → переводим в cc
    match = re.search(r"(\d+\.?\d*)\s*[Ll]", text)
    if match:
        liters = float(match.group(1))
        return int(liters * 1000)

    # Формат "2300cc"
    match = re.search(r"(\d{3,5})\s*cc", text, re.IGNORECASE)
    if match:
        return int(match.group(1))

    return 2000


# ─────────────────────────────────────────────
#  SalvageReseller — бесплатный агрегатор лотов
# ─────────────────────────────────────────────

def fetch_salvagereseller(make: str = None, year_from: int = None,
                          year_to: int = None, price_max: float = None) -> list[dict]:
    """
    Парсит SalvageReseller.com и возвращает список лотов.
    Каждый лот — словарь с полями:
      lot_id, title, year, make, damage, engine_cc, price, url, image_url
    """
    url = "https://www.salvagereseller.com/cars"
    params = {}

    if make:
        params["make"] = make.upper()
    if year_from:
        params["year_from"] = year_from
    if year_to:
        params["year_to"] = year_to
    if price_max:
        params["price_to"] = int(price_max)

    try:
        resp = httpx.get(url, params=params, headers=HEADERS, timeout=20, follow_redirects=True)
        resp.raise_for_status()
    except Exception as e:
        print(f"[parser] Ошибка запроса SalvageReseller: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    lots = []

    # SalvageReseller: карточки лотов в .vehicle-card или аналог
    cards = soup.select(".vehicle-card, .listing-item, article.car-item")

    for card in cards:
        try:
            lot_id = card.get("data-id") or card.get("id") or ""

            title_el = card.select_one(".vehicle-title, h2, h3, .title")
            title = title_el.get_text(strip=True) if title_el else "Неизвестно"

            year_el = card.select_one(".year, [data-year]")
            year = int(year_el.get_text(strip=True)) if year_el else 0

            damage_el = card.select_one(".damage, .primary-damage, [data-damage]")
            damage = damage_el.get_text(strip=True) if damage_el else "UNKNOWN"

            price_el = card.select_one(".price, .current-bid, [data-price]")
            price_text = price_el.get_text(strip=True) if price_el else "0"
            price = float(re.sub(r"[^\d.]", "", price_text) or 0)

            engine_el = card.select_one(".engine, [data-engine]")
            engine_text = engine_el.get_text(strip=True) if engine_el else ""
            engine_cc = parse_engine_cc(engine_text)

            link_el = card.select_one("a[href]")
            href = link_el["href"] if link_el else ""
            lot_url = href if href.startswith("http") else f"https://www.salvagereseller.com{href}"

            img_el = card.select_one("img")
            image_url = img_el.get("src") or img_el.get("data-src") if img_el else ""

            lots.append({
                "lot_id":    lot_id or lot_url,
                "title":     title,
                "year":      year,
                "make":      make or title.split()[0] if title else "",
                "damage":    damage,
                "engine_cc": engine_cc,
                "price":     price,
                "url":       lot_url,
                "image_url": image_url,
            })
        except Exception as e:
            print(f"[parser] Ошибка парсинга карточки: {e}")
            continue

    return lots


# ─────────────────────────────────────────────
#  Главная функция — с учётом фильтров
# ─────────────────────────────────────────────

def fetch_lots(filters: dict | None = None) -> list[dict]:
    """
    Получает лоты с учётом фильтров пользователя.
    filters: {make, year_from, year_to, price_max, damage}
    """
    f = filters or {}
    lots = fetch_salvagereseller(
        make=f.get("make"),
        year_from=f.get("year_from"),
        year_to=f.get("year_to"),
        price_max=f.get("price_max"),
    )

    # Фильтр по типу повреждения (если задан)
    if f.get("damage"):
        wanted = f["damage"].upper()
        lots = [l for l in lots if wanted in l["damage"].upper()]

    return lots
