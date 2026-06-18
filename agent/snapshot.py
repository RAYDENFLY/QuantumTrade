"""
agent/snapshot.py — Ambil snapshot kondisi sistem dari API dashboard + SQLite.

Snapshot ini dikirim ke LLM (setelah di-sanitize: tanpa secret).
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests

from agent.schema import AccountSnapshot, AgentSnapshot, PositionSnapshot, SurvivalMode, AgentMode

log = logging.getLogger("agent.snapshot")


def fetch_snapshot(
    dashboard_base_url: str,
    db_path: str,
    treasury_usdt: float,
    survival_mode: SurvivalMode,
    agent_mode: AgentMode,
    llm_cost_today_usd: float = 0.0,
    runner_error_count: int = 0,
    timeout: int = 10,
) -> AgentSnapshot:
    """
    Build AgentSnapshot dari:
    - GET /api/account          (equity, available, unrealized_pnl, drawdown)
    - GET /api/open-positions   (posisi + leverage)
    - SQLite trade_closures     (realized PnL 7d / 30d, win rate)
    - SQLite runner_state       (last candle timestamps, error count)
    """
    now = datetime.now(tz=timezone.utc)

    # ── Account ──────────────────────────────────────────────────────────────
    acct_data = _get_json(f"{dashboard_base_url}/api/account", timeout=timeout) or {}
    equity      = float(acct_data.get("equity", 0.0) or 0.0)
    available   = float(acct_data.get("available", 0.0) or 0.0)
    unrealized  = float(acct_data.get("unrealized_pnl", 0.0) or 0.0)

    # Drawdown: dari peak equity; dashboard seharusnya expose ini, kalau tidak ada hitung dari equity
    drawdown_pct = float(acct_data.get("drawdown_pct", 0.0) or 0.0)
    if drawdown_pct == 0.0:
        peak = float(acct_data.get("peak_equity", equity) or equity)
        if peak > 0:
            drawdown_pct = ((equity - peak) / peak) * 100.0

    # ── Positions ─────────────────────────────────────────────────────────────
    pos_data: List[Dict[str, Any]] = _get_json(f"{dashboard_base_url}/api/open-positions", timeout=timeout) or []
    positions: List[PositionSnapshot] = []
    total_notional = 0.0
    for p in pos_data:
        try:
            size      = float(p.get("size", 0) or 0)
            entry_px  = float(p.get("entry_price", 0) or 0)
            lev       = float(p.get("leverage", 1) or 1)
            notional  = abs(size * entry_px)
            total_notional += notional
            positions.append(PositionSnapshot(
                contract     = str(p.get("contract", "")),
                side         = str(p.get("side", "LONG")).upper(),
                size         = size,
                entry_price  = entry_px,
                unrealized_pnl = float(p.get("unrealized_pnl", 0) or 0),
                leverage     = lev,
                tp_price     = _opt_float(p.get("tp_price")),
                sl_price     = _opt_float(p.get("sl_price")),
            ))
        except Exception:
            log.exception("Error parsing position snapshot: %s", p)

    exposure_x = (total_notional / equity) if equity > 0 else 0.0

    # ── Order rate 4H (dari runner_state atau SQLite trades) ──────────────────
    order_rate_4h = _count_orders_4h(db_path)

    acct = AccountSnapshot(
        equity          = equity,
        available       = available,
        unrealized_pnl  = unrealized,
        drawdown_pct    = drawdown_pct,
        exposure_x      = exposure_x,
        open_positions  = len(positions),
        order_rate_4h   = order_rate_4h,
    )

    # ── Realized PnL stats dari SQLite ────────────────────────────────────────
    pnl_7d, pnl_30d, wr_30d = _pnl_stats(db_path)

    # ── Last candle timestamps dari runner_state ──────────────────────────────
    last_candle_ts = _last_candle_ts(db_path)

    # ── Runner error count dari runner_state (kalau disimpan) ────────────────
    if runner_error_count == 0:
        runner_error_count = _runner_error_count(db_path)

    return AgentSnapshot(
        ts                  = now,
        account             = acct,
        positions           = positions,
        last_candle_ts      = last_candle_ts,
        runner_error_count  = runner_error_count,
        treasury_usdt       = treasury_usdt,
        survival_mode       = survival_mode,
        agent_mode          = agent_mode,
        llm_cost_today_usd  = llm_cost_today_usd,
        realized_pnl_7d     = pnl_7d,
        realized_pnl_30d    = pnl_30d,
        win_rate_30d        = wr_30d,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_json(url: str, timeout: int = 10) -> Any:
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        log.warning("fetch_snapshot: GET %s failed: %s", url, e)
        return None


def _opt_float(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except Exception:
        return None


def _pnl_stats(db_path: str) -> tuple[float, float, float]:
    """(pnl_7d, pnl_30d, win_rate_30d)"""
    try:
        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        now = datetime.now(tz=timezone.utc)
        ts_7d  = (now - timedelta(days=7)).isoformat()
        ts_30d = (now - timedelta(days=30)).isoformat()

        row7 = cur.execute(
            "SELECT COALESCE(SUM(pnl),0) FROM trade_closures WHERE timestamp >= ?", (ts_7d,)
        ).fetchone()
        row30 = cur.execute(
            "SELECT COALESCE(SUM(pnl),0), COUNT(*), SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END) "
            "FROM trade_closures WHERE timestamp >= ?", (ts_30d,)
        ).fetchone()
        con.close()

        pnl_7d  = float(row7[0] or 0.0)
        pnl_30d = float(row30[0] or 0.0)
        total   = int(row30[1] or 0)
        wins    = int(row30[2] or 0)
        wr_30d  = (wins / total) if total > 0 else 0.0
        return pnl_7d, pnl_30d, wr_30d
    except Exception:
        log.exception("Failed to read pnl stats from SQLite")
        return 0.0, 0.0, 0.0


def _count_orders_4h(db_path: str) -> int:
    """Hitung order dalam 4 jam terakhir dari tabel trades."""
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        cutoff = (datetime.now(tz=timezone.utc) - timedelta(hours=4)).isoformat()
        row = cur.execute(
            "SELECT COUNT(*) FROM trades WHERE timestamp >= ?", (cutoff,)
        ).fetchone()
        con.close()
        return int(row[0] or 0)
    except Exception:
        return 0


def _last_candle_ts(db_path: str) -> Dict[str, str]:
    """Baca last_candle_<asset> dari runner_state."""
    result: Dict[str, str] = {}
    try:
        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT key, value FROM runner_state WHERE key LIKE 'last_candle_%'"
        ).fetchall()
        con.close()
        for r in rows:
            asset = str(r["key"]).replace("last_candle_", "")
            result[asset] = str(r["value"])
    except Exception:
        log.exception("Failed to read last_candle_ts from runner_state")
    return result


def _runner_error_count(db_path: str) -> int:
    """Baca runner_error_count dari runner_state."""
    try:
        con = sqlite3.connect(db_path)
        row = con.execute(
            "SELECT value FROM runner_state WHERE key='runner_error_count'"
        ).fetchone()
        con.close()
        return int(row[0]) if row else 0
    except Exception:
        return 0
