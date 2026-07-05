from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from app.config import Settings, load_settings
from app.estimators import estimate_lot
from app.formatting import format_filter, format_lot_report
from app.models import SearchFilters
from app.sources.apify_bidcars import ApifyBidCarsSource
from app.storage import Storage


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("auto-scout")

MAKE, MODEL, YEAR_FROM, YEAR_TO, PRICE_MAX, DAMAGE, RUN_DRIVE = range(7)
SKIP_WORDS = {"", "-", "any", "all", "все", "всё", "любой", "любая", "нет"}


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "<b>Auto Scout</b>\n\n"
        "Я мониторю аукционные лоты, считаю ориентировочную стоимость под ключ и присылаю новые варианты.\n\n"
        "/filter - настроить поиск\n"
        "/myfilter - показать фильтр\n"
        "/check - проверить сейчас\n"
        "/pause - остановить авто-уведомления\n"
        "/resume - включить авто-уведомления\n"
        "/health - проверить конфиг"
    )
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_health(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    storage: Storage = context.application.bot_data["storage"]
    active_count = len(storage.active_chat_ids())
    text = (
        "<b>Health</b>\n"
        f"Apify actor: <code>{settings.apify_actor}</code>\n"
        f"Check interval: <code>{settings.check_interval_seconds}s</code>\n"
        f"Max lots/check: <code>{settings.max_lots_per_check}</code>\n"
        f"Active subscriptions: <code>{active_count}</code>"
    )
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_filter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.effective_message.reply_text("Make? Example: BMW, Toyota, Ford. Send '-' for any.")
    return MAKE


async def filter_make(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["make"] = clean_text(update.effective_message.text)
    await update.effective_message.reply_text("Model? Example: X5, Camry, Mustang. Send '-' for any.")
    return MODEL


async def filter_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["model"] = clean_text(update.effective_message.text)
    await update.effective_message.reply_text("Year from? Example: 2018. Send '-' for any.")
    return YEAR_FROM


async def filter_year_from(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["year_from"] = parse_int_or_none(update.effective_message.text)
    await update.effective_message.reply_text("Year to? Example: 2023. Send '-' for any.")
    return YEAR_TO


async def filter_year_to(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["year_to"] = parse_int_or_none(update.effective_message.text)
    await update.effective_message.reply_text("Max current bid in USD? Example: 8000. Send '-' for any.")
    return PRICE_MAX


async def filter_price_max(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["price_max"] = parse_float_or_none(update.effective_message.text)
    await update.effective_message.reply_text("Damage filter? Example: FRONT END, SIDE, HAIL. Send '-' for any.")
    return DAMAGE


async def filter_damage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["damage"] = clean_text(update.effective_message.text)
    await update.effective_message.reply_text("Only Run & Drive lots? Send yes/no.")
    return RUN_DRIVE


async def filter_run_drive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    storage: Storage = context.application.bot_data["storage"]
    chat_id = update.effective_chat.id
    filters_obj = SearchFilters(
        make=context.user_data.get("make"),
        model=context.user_data.get("model"),
        year_from=context.user_data.get("year_from"),
        year_to=context.user_data.get("year_to"),
        price_max=context.user_data.get("price_max"),
        damage=context.user_data.get("damage"),
        run_and_drive_only=is_yes(update.effective_message.text),
    )
    storage.save_filter(chat_id, filters_obj)
    await update.effective_message.reply_text(
        "<b>Filter saved. Auto alerts enabled.</b>\n\n" + format_filter(filters_obj),
        parse_mode=ParseMode.HTML,
    )
    return ConversationHandler.END


async def filter_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.effective_message.reply_text("Filter setup cancelled.")
    return ConversationHandler.END


async def cmd_myfilter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    storage: Storage = context.application.bot_data["storage"]
    filters_obj = storage.get_filter(update.effective_chat.id)
    if not filters_obj:
        await update.effective_message.reply_text("No saved filter yet. Use /filter.")
        return
    await update.effective_message.reply_text(format_filter(filters_obj), parse_mode=ParseMode.HTML)


async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    storage: Storage = context.application.bot_data["storage"]
    storage.set_enabled(update.effective_chat.id, False)
    await update.effective_message.reply_text("Auto alerts paused. Use /resume to enable them again.")


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    storage: Storage = context.application.bot_data["storage"]
    storage.set_enabled(update.effective_chat.id, True)
    await update.effective_message.reply_text("Auto alerts enabled.")


async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    storage: Storage = context.application.bot_data["storage"]
    filters_obj = storage.get_filter(update.effective_chat.id) or SearchFilters()
    msg = await update.effective_message.reply_text("Checking auction lots...")
    count = await send_lots_to_chat(context, update.effective_chat.id, filters_obj, skip_seen=False)
    if count:
        await msg.delete()
    else:
        await msg.edit_text("No matching lots found right now.")


async def check_all_subscriptions(context: ContextTypes.DEFAULT_TYPE) -> None:
    storage: Storage = context.application.bot_data["storage"]
    for chat_id in storage.active_chat_ids():
        filters_obj = storage.get_filter(chat_id)
        if not filters_obj:
            continue
        try:
            await send_lots_to_chat(context, chat_id, filters_obj, skip_seen=True)
            await asyncio.sleep(0.5)
        except Exception:
            log.exception("Background check failed for chat_id=%s", chat_id)


async def send_lots_to_chat(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    filters_obj: SearchFilters,
    skip_seen: bool,
) -> int:
    settings: Settings = context.application.bot_data["settings"]
    storage: Storage = context.application.bot_data["storage"]
    source: ApifyBidCarsSource = context.application.bot_data["source"]

    lots = await source.fetch_lots(filters_obj, max_items=settings.max_lots_per_check)
    sent = 0
    for lot in lots[:10]:
        if skip_seen and storage.is_seen(chat_id, lot.lot_id):
            continue

        estimate = estimate_lot(lot, settings)
        text = format_lot_report(lot, estimate)
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Open lot", url=lot.url)]])

        try:
            if lot.image_url:
                await context.bot.send_photo(chat_id=chat_id, photo=lot.image_url)
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard,
                    disable_web_page_preview=True,
                )
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard,
                    disable_web_page_preview=False,
                )
            storage.mark_seen(chat_id, lot.lot_id)
            sent += 1
            await asyncio.sleep(0.5)
        except Exception:
            log.exception("Failed to send lot %s: %s", lot.lot_id, asdict(lot))
    return sent


def clean_text(text: str | None) -> str | None:
    value = (text or "").strip()
    return None if value.lower() in SKIP_WORDS else value


def parse_int_or_none(text: str | None) -> int | None:
    value = clean_text(text)
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def parse_float_or_none(text: str | None) -> float | None:
    value = clean_text(text)
    if not value:
        return None
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None


def is_yes(text: str | None) -> bool:
    return (text or "").strip().lower() in {"y", "yes", "да", "д", "+", "true", "1"}


def build_app(settings: Settings) -> Application:
    storage = Storage(settings.database_path)
    storage.init()
    source = ApifyBidCarsSource(settings.apify_token, settings.apify_actor)

    app = Application.builder().token(settings.telegram_bot_token).build()
    app.bot_data["settings"] = settings
    app.bot_data["storage"] = storage
    app.bot_data["source"] = source

    filter_conv = ConversationHandler(
        entry_points=[CommandHandler("filter", cmd_filter)],
        states={
            MAKE: [MessageHandler(filters.TEXT & ~filters.COMMAND, filter_make)],
            MODEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, filter_model)],
            YEAR_FROM: [MessageHandler(filters.TEXT & ~filters.COMMAND, filter_year_from)],
            YEAR_TO: [MessageHandler(filters.TEXT & ~filters.COMMAND, filter_year_to)],
            PRICE_MAX: [MessageHandler(filters.TEXT & ~filters.COMMAND, filter_price_max)],
            DAMAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, filter_damage)],
            RUN_DRIVE: [MessageHandler(filters.TEXT & ~filters.COMMAND, filter_run_drive)],
        },
        fallbacks=[CommandHandler("cancel", filter_cancel)],
    )

    app.add_handler(CommandHandler(["start", "help"], cmd_start))
    app.add_handler(CommandHandler("health", cmd_health))
    app.add_handler(CommandHandler("myfilter", cmd_myfilter))
    app.add_handler(CommandHandler("check", cmd_check))
    app.add_handler(CommandHandler("pause", cmd_pause))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(filter_conv)

    app.job_queue.run_repeating(
        check_all_subscriptions,
        interval=settings.check_interval_seconds,
        first=30,
        name="auction-subscription-check",
    )
    return app


def main() -> None:
    settings = load_settings()
    app = build_app(settings)
    log.info("Auto Scout bot started")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
