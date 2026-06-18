"""SQLite database connection + initialization."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


@dataclass(frozen=True)
class Database:
    db_path: Path
    schema_path: Path

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path.as_posix())
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return any(r[1] == column for r in rows)

    def migrate(self, conn: sqlite3.Connection) -> None:
        """Best-effort, additive migrations for live trading safety.

        Keep this strictly additive (ALTER TABLE ... ADD COLUMN) so existing
        databases can be upgraded in-place.
        """

        # Order-id linkage for fill-accurate journaling.
        if not self._has_column(conn, "trades", "entry_order_id"):
            conn.execute("ALTER TABLE trades ADD COLUMN entry_order_id TEXT")
        if not self._has_column(conn, "trade_closures", "exit_order_id"):
            conn.execute("ALTER TABLE trade_closures ADD COLUMN exit_order_id TEXT")

        # Optional TP/target price for transparency in the dashboard/journal.
        if not self._has_column(conn, "trades", "tp_price"):
            conn.execute("ALTER TABLE trades ADD COLUMN tp_price REAL")

        # Link TP/SL plan order ids for auditability.
        if not self._has_column(conn, "trades", "tp_order_id"):
            conn.execute("ALTER TABLE trades ADD COLUMN tp_order_id TEXT")
        if not self._has_column(conn, "trades", "sl_order_id"):
            conn.execute("ALTER TABLE trades ADD COLUMN sl_order_id TEXT")

        # Record entry fee from exchange fills when available.
        if not self._has_column(conn, "trades", "entry_fee"):
            conn.execute("ALTER TABLE trades ADD COLUMN entry_fee REAL")

        try:
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_trade_closures_trade_id_unique
                ON trade_closures(trade_id)
                WHERE trade_id IS NOT NULL
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_trade_closures_exit_order_id_unique
                ON trade_closures(exit_order_id)
                WHERE exit_order_id IS NOT NULL AND TRIM(exit_order_id) != ''
                """
            )
        except sqlite3.IntegrityError:
            # Older DBs may already contain duplicate closure rows. Runtime upsert
            # still keeps new writes idempotent; cleanup can be done separately.
            pass

    def initialize(self) -> None:
        schema = self.schema_path.read_text(encoding="utf-8")
        with self.connect() as conn:
            conn.executescript(schema)
            self.migrate(conn)
            conn.commit()
