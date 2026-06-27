from config import AUCTION_FEE_TIERS, SHIPPING_COST, SERVICE_FEE, CUSTOMS_BY_ENGINE, MARKET_MULTIPLIER

# Шаблоны деталей под замену по типу повреждения
DAMAGE_PARTS = {
    "FRONT END": ["Бампер передний", "Капот", "Фара левая", "Фара правая", "Радиатор", "Решётка радиатора"],
    "REAR END":  ["Бампер задний", "Крышка багажника", "Фонарь левый", "Фонарь правый", "Панель задняя"],
    "SIDE":      ["Дверь передняя", "Дверь задняя", "Крыло", "Порог", "Стекло боковое"],
    "ROLLOVER":  ["Крыша", "Стойки кузова", "Стёкла", "Подушки безопасности"],
    "FIRE":      ["Моторный отсек", "Проводка", "Пластик салона", "Двигатель (возможно)"],
    "FLOOD":     ["Электроника", "Ковры салона", "Блоки управления", "Двигатель (проверить)"],
    "HAIL":      ["Кузовные панели", "Стёкла (возможно)", "Лакокрасочное покрытие"],
    "MECHANICAL":["Двигатель / КПП", "Ходовая (диагностика)"],
    "VANDALISM": ["Стёкла", "Кузов", "Салон"],
    "MINOR DENT":["Кузовные панели", "Покраска"],
}

# Примерная стоимость ремонта по типу повреждения (USD)
REPAIR_COST = {
    "FRONT END":  1500,
    "REAR END":   1200,
    "SIDE":       900,
    "ROLLOVER":   3500,
    "FIRE":       4000,
    "FLOOD":      3000,
    "HAIL":       1800,
    "MECHANICAL": 2000,
    "VANDALISM":  1000,
    "MINOR DENT": 500,
}


def get_auction_fee(bid: float) -> float:
    """Рассчитывает сбор аукциона по размеру ставки."""
    for low, high, fee in AUCTION_FEE_TIERS:
        if low <= bid <= high:
            return fee
    return 600  # максимальный сбор


def get_customs(engine_cc: int) -> float:
    """Рассчитывает растаможку по объёму двигателя."""
    for low, high, cost in CUSTOMS_BY_ENGINE:
        if low <= engine_cc <= high:
            return cost
    return 3000  # дефолт если не определён объём


def get_damage_parts(damage_type: str) -> list[str]:
    """Возвращает список деталей под замену."""
    damage_upper = damage_type.upper()
    for key in DAMAGE_PARTS:
        if key in damage_upper:
            return DAMAGE_PARTS[key]
    return ["Нет данных — осмотрите вручную"]


def get_repair_cost(damage_type: str) -> int:
    """Возвращает примерную стоимость ремонта."""
    damage_upper = damage_type.upper()
    for key in REPAIR_COST:
        if key in damage_upper:
            return REPAIR_COST[key]
    return 1500  # дефолт


def calculate(bid: float, engine_cc: int, damage_type: str) -> dict:
    """
    Главная функция расчёта.
    Возвращает словарь со всеми цифрами.
    """
    auction_fee  = get_auction_fee(bid)
    repair       = get_repair_cost(damage_type)
    customs      = get_customs(engine_cc)
    parts        = get_damage_parts(damage_type)

    total = bid + auction_fee + SHIPPING_COST + repair + customs + SERVICE_FEE
    market_price = round(total * MARKET_MULTIPLIER / 100) * 100
    profit = market_price - total

    return {
        "bid":          bid,
        "auction_fee":  auction_fee,
        "shipping":     SHIPPING_COST,
        "repair":       repair,
        "customs":      customs,
        "service_fee":  SERVICE_FEE,
        "total":        round(total),
        "market_price": market_price,
        "profit":       round(profit),
        "parts":        parts,
    }


def format_report(lot: dict, calc: dict) -> str:
    """
    Форматирует итоговое сообщение для Telegram.
    lot  — данные лота (title, year, damage, engine_cc, url, image_url)
    calc — результат calculate()
    """
    parts_str = "\n".join(f"  • {p}" for p in calc["parts"])
    profit_emoji = "✅" if calc["profit"] > 2000 else "⚠️"

    return (
        f"🚗 *{lot.get('title', 'Авто')} {lot.get('year', '')}*\n"
        f"📍 Повреждение: `{lot.get('damage', '—')}`\n"
        f"🔩 Что под замену:\n{parts_str}\n\n"
        f"💰 *Расчёт под ключ:*\n"
        f"  Ставка:         `${calc['bid']:,.0f}`\n"
        f"  Сбор аукциона:  `${calc['auction_fee']:,.0f}`\n"
        f"  Доставка:       `${calc['shipping']:,.0f}`\n"
        f"  Ремонт:         `~${calc['repair']:,.0f}`\n"
        f"  Растаможка:     `~${calc['customs']:,.0f}`\n"
        f"  Услуги:         `${calc['service_fee']:,.0f}`\n"
        f"  ─────────────────────\n"
        f"  *ИТОГО:* `~${calc['total']:,.0f}`\n"
        f"  Рынок UA:       `~${calc['market_price']:,.0f}`\n"
        f"  {profit_emoji} *Выгода: ~${calc['profit']:,.0f}*\n\n"
        f"🔗 [Открыть лот]({lot.get('url', '#')})"
    )
