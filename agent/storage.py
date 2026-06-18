"""
agent/storage.py — AgentStorage abstraction: PostgresAgentStorage + SQLiteAgentStorage fallback.

Switch via env:
  AGENT_STORAGE=postgres   → PostgresAgentStorage (default kalau PG tersedia)
  AGENT_STORAGE=sqlite     → SQLiteAgentStorage

Koneksi PG via:
  AGENT_POSTGRES_DSN=postgresql://agent_user:agent_pass@localhost:5432/quant_agent
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

log = logging.getLogger("agent.storage")


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------

class AgentStorage(ABC):
    @abstractmethod
    def init_schema(self) -> None: ...

    @abstractmethod
    def save_plan(
        self,
        ts: datetime,
        input_snapshot: Dict[str, Any],
        plan: Dict[str, Any],
    ) -> int:
        """Returns plan_id."""
        ...

    @abstractmethod
    def save_action(
        self,
        plan_id: int,
        ts: datetime,
        action_type: str,
        action_params: Dict[str, Any],
        result: Dict[str, Any],
        success: bool,
    ) -> None: ...

    @abstractmethod
    def save_treasury(
        self,
        ts: datetime,
        treasury_usdt: float,
        cost_per_day_usd: float,
        llm_cost_usd: float,
        survival_mode: str,
    ) -> None: ...

    @abstractmethod
    def load_treasury(self) -> Optional[float]: ...

    @abstractmethod
    def get_recent_plans(self, limit: int = 10) -> List[Dict[str, Any]]: ...

    @abstractmethod
    def get_recent_actions(self, limit: int = 20) -> List[Dict[str, Any]]: ...


# ---------------------------------------------------------------------------
# PostgreSQL backend
# ---------------------------------------------------------------------------

PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_plans (
    id              SERIAL PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL,
    input_snapshot  JSONB,
    plan_json       JSONB,
    approved_by     TEXT DEFAULT 'auto',
    executed_at     TIMESTAMPTZ,
    status          TEXT DEFAULT 'pending'
);
CREATE INDEX IF NOT EXISTS idx_agent_plans_ts ON agent_plans(ts DESC);

CREATE TABLE IF NOT EXISTS agent_actions (
    id               SERIAL PRIMARY KEY,
    plan_id          INTEGER REFERENCES agent_plans(id),
    ts               TIMESTAMPTZ NOT NULL,
    action_type      TEXT NOT NULL,
    action_params    JSONB,
    result_json      JSONB,
    success          BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_agent_actions_ts ON agent_actions(ts DESC);
CREATE INDEX IF NOT EXISTS idx_agent_actions_type_ts ON agent_actions(action_type, ts DESC);

CREATE TABLE IF NOT EXISTS agent_treasury (
    id               SERIAL PRIMARY KEY,
    ts               TIMESTAMPTZ NOT NULL,
    treasury_usdt    DOUBLE PRECISION NOT NULL,
    cost_per_day_usd DOUBLE PRECISION NOT NULL,
    llm_cost_usd     DOUBLE PRECISION NOT NULL DEFAULT 0,
    survival_mode    TEXT NOT NULL DEFAULT 'NORMAL'
);
CREATE INDEX IF NOT EXISTS idx_agent_treasury_ts ON agent_treasury(ts DESC);
"""


class PostgresAgentStorage(AgentStorage):
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._conn = None

    def _get_conn(self):
        import psycopg2
        import psycopg2.extras
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(self._dsn)
            self._conn.autocommit = True
        return self._conn

    def init_schema(self) -> None:
        import psycopg2.extras
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(PG_SCHEMA)
        log.info("PostgresAgentStorage: schema initialized")

    def save_plan(
        self,
        ts: datetime,
        input_snapshot: Dict[str, Any],
        plan: Dict[str, Any],
    ) -> int:
        import psycopg2.extras
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO agent_plans (ts, input_snapshot, plan_json, status)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (ts, json.dumps(input_snapshot), json.dumps(plan), "executed"),
            )
            row = cur.fetchone()
        return int(row[0])

    def save_action(
        self,
        plan_id: int,
        ts: datetime,
        action_type: str,
        action_params: Dict[str, Any],
        result: Dict[str, Any],
        success: bool,
    ) -> None:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO agent_actions (plan_id, ts, action_type, action_params, result_json, success)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (plan_id, ts, action_type, json.dumps(action_params), json.dumps(result), success),
            )

    def save_treasury(self, ts, treasury_usdt, cost_per_day_usd, llm_cost_usd, survival_mode):
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO agent_treasury (ts, treasury_usdt, cost_per_day_usd, llm_cost_usd, survival_mode)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (ts, treasury_usdt, cost_per_day_usd, llm_cost_usd, survival_mode),
            )

    def load_treasury(self) -> Optional[float]:
        try:
            conn = self._get_conn()
            with conn.cursor() as cur:
                cur.execute("SELECT treasury_usdt FROM agent_treasury ORDER BY ts DESC LIMIT 1")
                row = cur.fetchone()
            return float(row[0]) if row else None
        except Exception:
            log.exception("load_treasury failed")
            return None

    def get_recent_plans(self, limit: int = 10) -> List[Dict[str, Any]]:
        try:
            conn = self._get_conn()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, ts, plan_json, status FROM agent_plans ORDER BY ts DESC LIMIT %s",
                    (limit,),
                )
                rows = cur.fetchall()
            return [{"id": r[0], "ts": str(r[1]), "plan": r[2], "status": r[3]} for r in rows]
        except Exception:
            log.exception("get_recent_plans failed")
            return []

    def get_recent_actions(self, limit: int = 20) -> List[Dict[str, Any]]:
        try:
            conn = self._get_conn()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, plan_id, ts, action_type, result_json, success "
                    "FROM agent_actions ORDER BY ts DESC LIMIT %s",
                    (limit,),
                )
                rows = cur.fetchall()
            return [
                {"id": r[0], "plan_id": r[1], "ts": str(r[2]),
                 "action_type": r[3], "result": r[4], "success": r[5]}
                for r in rows
            ]
        except Exception:
            log.exception("get_recent_actions failed")
            return []


# ---------------------------------------------------------------------------
# SQLite backend (fallback)
# ---------------------------------------------------------------------------

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_plans (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    input_snapshot  TEXT,
    plan_json       TEXT,
    approved_by     TEXT DEFAULT 'auto',
    executed_at     TEXT,
    status          TEXT DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS agent_actions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id         INTEGER REFERENCES agent_plans(id),
    ts              TEXT NOT NULL,
    action_type     TEXT NOT NULL,
    action_params   TEXT,
    result_json     TEXT,
    success         INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS agent_treasury (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    treasury_usdt   REAL NOT NULL,
    cost_per_day_usd REAL NOT NULL,
    llm_cost_usd    REAL NOT NULL DEFAULT 0,
    survival_mode   TEXT NOT NULL DEFAULT 'NORMAL'
);
"""


class SQLiteAgentStorage(AgentStorage):
    def __init__(self, db_path: str = "agent/agent.sqlite") -> None:
        self._db_path = db_path

    def _con(self) -> sqlite3.Connection:
        con = sqlite3.connect(self._db_path)
        con.execute("PRAGMA journal_mode=WAL")
        return con

    def init_schema(self) -> None:
        with self._con() as con:
            con.executescript(SQLITE_SCHEMA)
        log.info("SQLiteAgentStorage: schema initialized at %s", self._db_path)

    def save_plan(self, ts, input_snapshot, plan) -> int:
        with self._con() as con:
            cur = con.execute(
                "INSERT INTO agent_plans (ts, input_snapshot, plan_json, status) VALUES (?,?,?,?)",
                (ts.isoformat(), json.dumps(input_snapshot), json.dumps(plan), "executed"),
            )
            return int(cur.lastrowid)

    def save_action(self, plan_id, ts, action_type, action_params, result, success):
        with self._con() as con:
            con.execute(
                "INSERT INTO agent_actions (plan_id, ts, action_type, action_params, result_json, success) "
                "VALUES (?,?,?,?,?,?)",
                (plan_id, ts.isoformat(), action_type, json.dumps(action_params), json.dumps(result), int(success)),
            )

    def save_treasury(self, ts, treasury_usdt, cost_per_day_usd, llm_cost_usd, survival_mode):
        with self._con() as con:
            con.execute(
                "INSERT INTO agent_treasury (ts, treasury_usdt, cost_per_day_usd, llm_cost_usd, survival_mode) "
                "VALUES (?,?,?,?,?)",
                (ts.isoformat(), treasury_usdt, cost_per_day_usd, llm_cost_usd, survival_mode),
            )

    def load_treasury(self) -> Optional[float]:
        try:
            with self._con() as con:
                row = con.execute(
                    "SELECT treasury_usdt FROM agent_treasury ORDER BY ts DESC LIMIT 1"
                ).fetchone()
            return float(row[0]) if row else None
        except Exception:
            return None

    def get_recent_plans(self, limit: int = 10) -> List[Dict[str, Any]]:
        try:
            with self._con() as con:
                rows = con.execute(
                    "SELECT id, ts, plan_json, status FROM agent_plans ORDER BY ts DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [{"id": r[0], "ts": r[1], "plan": json.loads(r[2] or "{}"), "status": r[3]} for r in rows]
        except Exception:
            return []

    def get_recent_actions(self, limit: int = 20) -> List[Dict[str, Any]]:
        try:
            with self._con() as con:
                rows = con.execute(
                    "SELECT id, plan_id, ts, action_type, result_json, success "
                    "FROM agent_actions ORDER BY ts DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [
                {"id": r[0], "plan_id": r[1], "ts": r[2],
                 "action_type": r[3], "result": json.loads(r[4] or "{}"), "success": bool(r[5])}
                for r in rows
            ]
        except Exception:
            return []


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def make_storage() -> AgentStorage:
    """
    Buat storage instance berdasarkan env var AGENT_STORAGE.
    Default: postgres kalau DSN ada, sqlite kalau tidak.
    """
    mode = os.environ.get("AGENT_STORAGE", "auto").lower()
    dsn  = os.environ.get("AGENT_POSTGRES_DSN", "")

    if mode == "sqlite":
        log.info("AgentStorage: using SQLite")
        return SQLiteAgentStorage()

    if mode == "postgres" or (mode == "auto" and dsn):
        if not dsn:
            raise RuntimeError("AGENT_POSTGRES_DSN env var required for postgres storage")
        try:
            import psycopg2  # noqa: F401
            log.info("AgentStorage: using PostgreSQL")
            return PostgresAgentStorage(dsn)
        except ImportError:
            log.warning("psycopg2 not installed — falling back to SQLite storage")

    log.info("AgentStorage: using SQLite (fallback)")
    return SQLiteAgentStorage()
