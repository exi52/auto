import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ContextTypes,
    MessageHandler, filters, ConversationHandler
)
from telegram.constants import ParseMode

from config import TELEGRAM_BOT_TOKEN, CHECK_INTERVAL
from database import init_db, is_seen, mark_seen, save_filter, get_filter, get_all_chat_ids
from parser import fetch_lots
from calculator import calculate, format_report

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# Состояния диалога настройки фильтров
MAKE, YEAR_FROM, YEAR_TO, PRICE_MAX, DAMAGE = range(5)


# ─────────────────────────────────────────────
#  Команда /start
# ─────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 *Привет! Я бот-парсер аукционов авто.*\n\n"
        "Я слежу за новыми лотами на Copart/IAAI и присылаю тебе "
        "готовый расчёт под ключ — ставка, доставка, растаможка, ремонт.\n\n"
        "📋 *Команды:*\n"
        "/filter — настроить фильтры (марка, год, цена)\n"
        "/myfilter — посмотреть текущие фильтры\n"
        "/check — проверить лоты прямо сейчас\n"
        "/stop — остановить алерты\n"
        "/help — помощь"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# ─────────────────────────────────────────────
#  Настройка фильтров (диалог)
# ─────────────────────────────────────────────

async def cmd_filter(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔧 *Настройка фильтров*\n\nВведи марку авто (например: `BMW`, `Toyota`, `Ford`)\n"
        "Или напиши `любая` чтобы не фильтровать по марке.",
        parse_mode=ParseMode.MARKDOWN
    )
    return MAKE


async def filter_make(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    ctx.user_data["make"] = None if text.lower() in ("любая", "any", "-") else text
    await update.message.reply_text(
        "📅 Год выпуска *от* (например: `2018`) или `любой`:",
        parse_mode=ParseMode.MARKDOWN
    )
    return YEAR_FROM


async def filter_year_from(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        ctx.user_data["year_from"] = int(text) if text.lower() not in ("любой", "any", "-") else None
    except ValueError:
        ctx.user_data["year_from"] = None
    await update.message.reply_text(
        "📅 Год выпуска *до* (например: `2022`) или `любой`:",
        parse_mode=ParseMode.MARKDOWN
    )
    return YEAR_TO


async def filter_year_to(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        ctx.user_data["year_to"] = int(text) if text.lower() not in ("любой", "any", "-") else None
    except ValueError:
        ctx.user_data["year_to"] = None
    await update.message.reply_text(
        "💵 Максимальная ставка на аукционе в $ (например: `8000`) или `любая`:",
        parse_mode=ParseMode.MARKDOWN
    )
    return PRICE_MAX


async def filter_price_max(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        ctx.user_data["price_max"] = float(text) if text.lower() not in ("любая", "any", "-") else None
    except ValueError:
        ctx.user_data["price_max"] = None
    await update.message.reply_text(
        "💥 Тип повреждения (например: `FRONT END`, `REAR END`, `SIDE`, `FLOOD`)\n"
        "Или `любой` чтобы не фильтровать:",
        parse_mode=ParseMode.MARKDOWN
    )
    return DAMAGE


async def filter_damage(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    ctx.user_data["damage"] = None if text.lower() in ("любой", "any", "-") else text.upper()

    chat_id = update.effective_chat.id
    f = ctx.user_data

    save_filter(
        chat_id=chat_id,
        make=f.get("make"),
        year_from=f.get("year_from"),
        year_to=f.get("year_to"),
        price_max=f.get("price_max"),
        damage=f.get("damage"),
    )

    # Формируем сводку
    lines = [
        f"  Марка: `{f.get('make') or 'любая'}`",
        f"  Год: `{f.get('year_from') or '—'}` – `{f.get('year_to') or '—'}`",
        f"  Ставка до: `{'$' + str(int(f['price_max'])) if f.get('price_max') else 'любая'}`",
        f"  Повреждение: `{f.get('damage') or 'любое'}`",
    ]
    await update.message.reply_text(
        "✅ *Фильтры сохранены!*\n\n" + "\n".join(lines) +
        "\n\nЯ буду присылать новые лоты автоматически каждые 5 минут.\n"
        "Или нажми /check чтобы проверить прямо сейчас.",
        parse_mode=ParseMode.MARKDOWN
    )
    return ConversationHandler.END


async def filter_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Настройка фильтров отменена.")
    return ConversationHandler.END


# ─────────────────────────────────────────────
#  Показать текущие фильтры
# ─────────────────────────────────────────────

async def cmd_myfilter(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    f = get_filter(update.effective_chat.id)
    if not f:
        await update.message.reply_text("У тебя нет сохранённых фильтров. Используй /filter чтобы настроить.")
        return
    lines = [
        f"  Марка: `{f.get('make') or 'любая'}`",
        f"  Год от: `{f.get('year_from') or '—'}`",
        f"  Год до: `{f.get('year_to') or '—'}`",
        f"  Ставка до: `{'$' + str(int(f['price_max'])) if f.get('price_max') else 'любая'}`",
        f"  Повреждение: `{f.get('damage') or 'любое'}`",
    ]
    await update.message.reply_text(
        "🔍 *Твои фильтры:*\n\n" + "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN
    )


# ─────────────────────────────────────────────
#  Ручная проверка лотов /check
# ─────────────────────────────────────────────

async def cmd_check(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    f = get_filter(chat_id)
    msg = await update.message.reply_text("🔎 Ищу лоты...")
    sent = await send_lots_to_chat(ctx.bot, chat_id, f, skip_seen=False)
    if sent == 0:
        await msg.edit_text("😕 Лоты по твоим фильтрам не найдены. Попробуй расширить фильтры (/filter).")
    else:
        await msg.delete()


# ─────────────────────────────────────────────
#  Стоп
# ─────────────────────────────────────────────

async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⏸ Алерты приостановлены. Твои фильтры сохранены.\n"
        "Напиши /check чтобы проверить вручную, или /filter чтобы изменить настройки."
    )


# ─────────────────────────────────────────────
#  Отправка лотов в чат (используется и автоматически, и по /check)
# ─────────────────────────────────────────────

async def send_lots_to_chat(bot, chat_id: int, filters: dict | None, skip_seen: bool = True) -> int:
    """Возвращает количество отправленных лотов."""
    lots = fetch_lots(filters)
    sent = 0

    for lot in lots[:10]:  # максимум 10 лотов за раз
        lot_id = lot["lot_id"]

        if skip_seen and is_seen(lot_id):
            continue

        try:
            calc = calculate(
                bid=lot["price"],
                engine_cc=lot["engine_cc"],
                damage_type=lot["damage"],
            )
            text = format_report(lot, calc)

            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("🔗 Открыть лот", url=lot["url"]),
            ]])

            if lot.get("image_url"):
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=lot["image_url"],
                    caption=text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=keyboard,
                )
            else:
                await bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=keyboard,
                    disable_web_page_preview=False,
                )

            if skip_seen:
                mark_seen(lot_id)

            sent += 1
            await asyncio.sleep(0.5)  # пауза между сообщениями

        except Exception as e:
            log.error(f"Ошибка отправки лота {lot_id}: {e}")

    return sent


# ─────────────────────────────────────────────
#  Фоновая задача — автоматический мониторинг
# ─────────────────────────────────────────────

async def background_monitor(app: Application):
    """Запускается в фоне, проверяет лоты каждые CHECK_INTERVAL секунд."""
    await asyncio.sleep(10)  # небольшая пауза при старте
    while True:
        log.info("Фоновая проверка лотов...")
        chat_ids = get_all_chat_ids()
        for chat_id in chat_ids:
            f = get_filter(chat_id)
            try:
                await send_lots_to_chat(app.bot, chat_id, f, skip_seen=True)
            except Exception as e:
                log.error(f"Ошибка для chat_id {chat_id}: {e}")
        await asyncio.sleep(CHECK_INTERVAL)


# ─────────────────────────────────────────────
#  Запуск
# ─────────────────────────────────────────────

def main():
    init_db()
    log.info("База данных инициализирована")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Диалог настройки фильтров
    filter_conv = ConversationHandler(
        entry_points=[CommandHandler("filter", cmd_filter)],
        states={
            MAKE:       [MessageHandler(filters.TEXT & ~filters.COMMAND, filter_make)],
            YEAR_FROM:  [MessageHandler(filters.TEXT & ~filters.COMMAND, filter_year_from)],
            YEAR_TO:    [MessageHandler(filters.TEXT & ~filters.COMMAND, filter_year_to)],
            PRICE_MAX:  [MessageHandler(filters.TEXT & ~filters.COMMAND, filter_price_max)],
            DAMAGE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, filter_damage)],
        },
        fallbacks=[CommandHandler("cancel", filter_cancel)],
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("myfilter", cmd_myfilter))
    app.add_handler(CommandHandler("check", cmd_check))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(filter_conv)

    # Запускаем фоновый мониторинг
    app.job_queue.run_repeating(
        lambda ctx: asyncio.create_task(send_lots_to_chat(ctx.bot, None, None)),
        interval=CHECK_INTERVAL,
        first=15,
    )

    log.info("Бот запущен")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
