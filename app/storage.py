from __future__ import annotations

import sqlite3
import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.models import SearchFilters


class Storage:
    def __init__(self, path: str) -> None:
        self.path = Path(path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        if self.path.parent != Path("."):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS filters (
                    chat_id INTEGER PRIMARY KEY,
                    make TEXT,
                    model TEXT,
                    year_from INTEGER,
                    year_to INTEGER,
                    price_max REAL,
                    damage TEXT,
                    run_and_drive_only INTEGER NOT NULL DEFAULT 0,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cache_entries (
                    namespace TEXT NOT NULL,
                    cache_key TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (namespace, cache_key)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS seen_lots (
                    chat_id INTEGER NOT NULL,
                    lot_id TEXT NOT NULL,
                    seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (chat_id, lot_id)
                )
                """
            )

    def save_filter(self, chat_id: int, filters: SearchFilters) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO filters (
                    chat_id, make, model, year_from, year_to, price_max,
                    damage, run_and_drive_only, enabled, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
                ON CONFLICT(chat_id) DO UPDATE SET
                    make = excluded.make,
                    model = excluded.model,
                    year_from = excluded.year_from,
                    year_to = excluded.year_to,
                    price_max = excluded.price_max,
                    damage = excluded.damage,
                    run_and_drive_only = excluded.run_and_drive_only,
                    enabled = 1,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    chat_id,
                    filters.make,
                    filters.model,
                    filters.year_from,
                    filters.year_to,
                    filters.price_max,
                    filters.damage,
                    int(filters.run_and_drive_only),
                ),
            )

    def get_filter(self, chat_id: int) -> SearchFilters | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM filters WHERE chat_id = ?", (chat_id,)).fetchone()
        if not row:
            return None
        return SearchFilters(
            make=row["make"],
            model=row["model"],
            year_from=row["year_from"],
            year_to=row["year_to"],
            price_max=row["price_max"],
            damage=row["damage"],
            run_and_drive_only=bool(row["run_and_drive_only"]),
        )

    def set_enabled(self, chat_id: int, enabled: bool) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE filters SET enabled = ?, updated_at = CURRENT_TIMESTAMP WHERE chat_id = ?",
                (int(enabled), chat_id),
            )

    def active_chat_ids(self) -> list[int]:
        with self.connect() as conn:
            rows = conn.execute("SELECT chat_id FROM filters WHERE enabled = 1").fetchall()
        return [int(row["chat_id"]) for row in rows]

    def is_seen(self, chat_id: int, lot_id: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM seen_lots WHERE chat_id = ? AND lot_id = ?",
                (chat_id, lot_id),
            ).fetchone()
        return row is not None

    def mark_seen(self, chat_id: int, lot_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO seen_lots (chat_id, lot_id) VALUES (?, ?)",
                (chat_id, lot_id),
            )

    def seen_count(self, chat_id: int) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM seen_lots WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
        return int(row["count"])

    def clear_seen(self, chat_id: int) -> int:
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM seen_lots WHERE chat_id = ?", (chat_id,))
        return int(cursor.rowcount)

    def get_cache(self, namespace: str, cache_key: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT payload
                FROM cache_entries
                WHERE namespace = ? AND cache_key = ? AND expires_at > ?
                """,
                (namespace, cache_key, int(time.time())),
            ).fetchone()
        if not row:
            return None
        try:
            value = json.loads(row["payload"])
        except (TypeError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def set_cache(self, namespace: str, cache_key: str, payload: dict, ttl_hours: int) -> None:
        expires_at = int(time.time()) + max(1, ttl_hours) * 3600
        encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO cache_entries (namespace, cache_key, payload, expires_at, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(namespace, cache_key) DO UPDATE SET
                    payload = excluded.payload,
                    expires_at = excluded.expires_at,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (namespace, cache_key, encoded, expires_at),
            )
