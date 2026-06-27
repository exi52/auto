import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "lots.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Создаёт таблицы при первом запуске."""
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS seen_lots (
                lot_id TEXT PRIMARY KEY,
                seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS filters (
                chat_id   INTEGER PRIMARY KEY,
                make      TEXT,
                year_from INTEGER,
                year_to   INTEGER,
                price_max REAL,
                damage    TEXT
            );
        """)


def is_seen(lot_id: str) -> bool:
    """Проверяет, отправляли ли уже этот лот."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM seen_lots WHERE lot_id = ?", (lot_id,)
        ).fetchone()
    return row is not None


def mark_seen(lot_id: str):
    """Помечает лот как отправленный."""
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO seen_lots (lot_id) VALUES (?)", (lot_id,)
        )


def save_filter(chat_id: int, make: str = None, year_from: int = None,
                year_to: int = None, price_max: float = None, damage: str = None):
    """Сохраняет фильтры пользователя."""
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO filters (chat_id, make, year_from, year_to, price_max, damage)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                make      = excluded.make,
                year_from = excluded.year_from,
                year_to   = excluded.year_to,
                price_max = excluded.price_max,
                damage    = excluded.damage
        """, (chat_id, make, year_from, year_to, price_max, damage))


def get_filter(chat_id: int) -> dict | None:
    """Возвращает фильтры пользователя."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM filters WHERE chat_id = ?", (chat_id,)
        ).fetchone()
    return dict(row) if row else None


def get_all_chat_ids() -> list[int]:
    """Возвращает все chat_id у которых есть фильтры."""
    with get_conn() as conn:
        rows = conn.execute("SELECT chat_id FROM filters").fetchall()
    return [r["chat_id"] for r in rows]
