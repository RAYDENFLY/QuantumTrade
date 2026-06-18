"""Dedicated live execution runner for Gate.io USDT-margined perpetual futures.

Key constraints (by design):
- Runs continuously and checks every 60 seconds.
- Detects *new closed* 4H candle per asset (temporary: read from CSV).
- Generates signals only on candle close.
- Loads latest saved model + threshold.
- Uses RiskManager + GateExecutor + SQLite Journal.
- Uses real exchange positions; no mock exits and no bar-by-bar simulation.

Temporary candle source:
- CSVs in config.data.csv_dir, one per asset (same format as backtest CSV placeholders).

Operational notes:
- This script assumes a single net position per contract (Gate futures position size sign).
- Equity is tracked locally via SQLite updates from realized closures (best-effort).
- Kill switch triggers if drawdown exceeds 25% from starting_equity.

Run from repo root:
  python live_runner.py
"""

from __future__ import annotations

import logging
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import os

import numpy as np
import pandas as pd
import yaml

from quant_system.data.fetch_data import DataFetcher
from quant_system.database.db import Database
from quant_system.database.journal import Journal
from quant_system.execution.gate_executor import GateExecutor
from quant_system.features.build_features import FeatureBuilder
from quant_system.model.predict import Signal, SignalGenerator
from quant_system.risk.risk_manager import RiskManager


BREAKERS_DIR = Path(__file__).resolve().parent / "breakers"
PANIC_CLOSE_FILE = BREAKERS_DIR / "PANIC_CLOSE_ALL"


def _interval_from_timeframe(timeframe: str) -> str:
    tf = str(timeframe).upper()
    if tf == "4H":
        return "4h"
    raise ValueError(f"Unsupported timeframe: {timeframe}")


def _gate_candles_to_ohlcv_df(*, rows: List[Dict[str, Any]], asset: str) -> pd.DataFrame:
    """Convert Gate futures candlesticks payload rows to internal OHLCV DataFrame."""
    if not rows:
        return pd.DataFrame(columns=["timestamp", "asset", "open", "high", "low", "close", "volume"])

    out: List[Dict[str, Any]] = []
    for r in rows:
        try:
            ts = pd.to_datetime(int(r["t"]), unit="s", utc=True)
            out.append(
                {
                    "timestamp": ts,
                    "asset": asset,
                    "open": float(r.get("o")),
                    "high": float(r.get("h")),
                    "low": float(r.get("l")),
                    "close": float(r.get("c")),
                    "volume": float(r.get("v", 0.0)),
                }
            )
        except Exception:
            continue

    df = pd.DataFrame(out)
    if df.empty:
        return df
    df = df.sort_values("timestamp").drop_duplicates(subset=["timestamp"]).reset_index(drop=True)
    return df


def _latest_closed_candle_ts_from_gate(
    *,
    executor: GateExecutor,
    contract: str,
    timeframe: str,
) -> Optional[pd.Timestamp]:
    interval = _interval_from_timeframe(timeframe)
    rows = executor.get_futures_candlesticks(contract=contract, interval=interval, limit=50)
    df = _gate_candles_to_ohlcv_df(rows=rows, asset=contract)
    if df.empty:
        return None

    # Treat the last fully completed interval as closed.
    now = pd.Timestamp.utcnow()
    # pandas versions differ: utcnow() may return tz-naive or tz-aware.
    if now.tzinfo is None:
        now = now.tz_localize("UTC")
    else:
        now = now.tz_convert("UTC")
    if timeframe.upper() == "4H":
        closed_cutoff = now.floor("4h") - pd.Timedelta(hours=4)
    else:
        raise ValueError(f"Unsupported timeframe: {timeframe}")

    df = df[df["timestamp"] <= closed_cutoff]
    if df.empty:
        return None
    return pd.Timestamp(df["timestamp"].iloc[-1]).tz_convert("UTC")


def load_config(config_path: Path) -> Dict[str, Any]:
    with config_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def setup_logging(cfg: Dict[str, Any]) -> None:
    level_name = str(cfg.get("logging", {}).get("level", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)
    use_json = bool((cfg.get("logging") or {}).get("json", False))
    if not use_json:
        logging.basicConfig(
            level=level,
            format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        )
        return

    # Minimal JSON logging formatter (no external deps).
    class _JsonFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
            payload: Dict[str, Any] = {
                "ts": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S"),
                "level": record.levelname,
                "logger": record.name,
                "msg": record.getMessage(),
            }
            # Attach exception info if present.
            if record.exc_info:
                payload["exc"] = self.formatException(record.exc_info)
            # Include extra fields if present.
            for k, v in record.__dict__.items():
                if k.startswith("_"):
                    continue
                if k in {
                    "name",
                    "msg",
                    "args",
                    "levelname",
                    "levelno",
                    "pathname",
                    "filename",
                    "module",
                    "exc_info",
                    "exc_text",
                    "stack_info",
                    "lineno",
                    "funcName",
                    "created",
                    "msecs",
                    "relativeCreated",
                    "thread",
                    "threadName",
                    "processName",
                    "process",
                }:
                    continue
                # Keep JSON-serializable only.
                try:
                    json.dumps(v)
                    payload[k] = v
                except Exception:
                    payload[k] = str(v)
            return json.dumps(payload, ensure_ascii=False)

    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler()
    handler.setLevel(level)
    handler.setFormatter(_JsonFormatter())
    root.addHandler(handler)


def _latest_closed_candle_ts(asset_csv: Path, timeframe: str) -> pd.Timestamp:
    """Read CSV and return the latest *closed* candle timestamp for the timeframe.

    Closed candle definition:
    - We treat the last fully formed 4H bin as closed.
    - With CSV data, we approximate this by resampling and taking the second to last row
      if the last row might still be forming.

    In practice with a proper market data feed you'd use exchange timestamps and a
    'closed' flag.
    """
    df = pd.read_csv(asset_csv)
    df.columns = [c.strip().lower() for c in df.columns]
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp")

    rule = "4h" if timeframe.upper() == "4H" else timeframe
    ohlcv = df.set_index("timestamp").resample(rule, label="left", closed="left").agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    )
    ohlcv = ohlcv.dropna(subset=["open", "high", "low", "close"]).reset_index()
    if len(ohlcv) == 0:
        raise ValueError(f"No candles available in {asset_csv}")

    # Prefer second-to-last as "last closed".
    if len(ohlcv) >= 2:
        return pd.Timestamp(ohlcv["timestamp"].iloc[-2]).tz_convert("UTC")
    return pd.Timestamp(ohlcv["timestamp"].iloc[-1]).tz_convert("UTC")


def _compute_latest_features(cfg: Dict[str, Any], *, executor: GateExecutor) -> pd.DataFrame:
    """Build features from Gate candlesticks history and return the latest feature row per asset."""
    fb = FeatureBuilder(cfg)

    assets: List[str] = list(cfg["assets"])
    timeframe: str = str(cfg["system"]["timeframe"]).upper()
    interval = _interval_from_timeframe(timeframe)

    frames: List[pd.DataFrame] = []
    for asset in assets:
        contract = _gate_contract_for_asset(asset)
        try:
            rows = executor.get_futures_candlesticks(contract=contract, interval=interval, limit=400)
            df = _gate_candles_to_ohlcv_df(rows=rows, asset=asset)
        except Exception:
            df = pd.DataFrame()

        if df is None or df.empty:
            continue
        frames.append(df)

    # Fallback to CSV if exchange data couldn't be pulled at all.
    if not frames:
        fetcher = DataFetcher(cfg)
        ohlcv = fetcher.load_ohlcv()
    else:
        ohlcv = pd.concat(frames, ignore_index=True)
        ohlcv = ohlcv.sort_values(["timestamp", "asset"]).reset_index(drop=True)

    feats = fb.build(ohlcv)
    feats = feats.sort_values(["asset", "timestamp"]).reset_index(drop=True)
    latest = feats.groupby("asset", as_index=False).tail(1)
    latest = latest.sort_values(["timestamp", "asset"]).reset_index(drop=True)
    return latest


def _gate_contract_for_asset(asset: str) -> str:
    """Map internal asset symbol to Gate contract.

    Assumption (common): internal asset uses '_' like BTC_USDT; Gate usually uses e.g. BTC_USDT.
    If your naming differs, implement a mapping in config and use it here.
    """
    return asset

def _ensure_tpsl_for_position(
    *,
    executor: GateExecutor,
    contract: str,
    side: str,
    abs_size: int,
    tp_price: Optional[float],
    sl_price: Optional[float],
    trigger_rule: int,
    log: logging.Logger,
) -> Dict[str, Optional[str]]:
    """Best-effort: ensure TP/SL trigger orders exist on exchange for an open position.

    This addresses cases where:
      - trigger orders were never created,
      - size changed (scale-in/out) so reduce-only order doesn't cover full size,
      - trigger rule (mark/last) differs from expectation,
      - orders were canceled server-side.
    """

    replaced: Dict[str, Optional[str]] = {"tp_order_id": None, "sl_order_id": None}

    if abs_size <= 0:
        return replaced

    desired_close_side = "sell" if str(side).upper() == "LONG" else "buy"

    # ── helpers to extract fields from Gate plan-order schema ──────────────────
    # Gate /price_orders objects use the new schema where tag is in initial.text,
    # and size is in initial.size. Top-level `side` / `size` may be absent.

    def _tag(o: Dict[str, Any]) -> str:
        # New schema: tag is in initial.text
        initial = o.get("initial") or {}
        t = initial.get("text") or o.get("text") or (o.get("order") or {}).get("text") or ""
        return str(t)

    def _rule(o: Dict[str, Any]) -> Optional[int]:
        trig = o.get("trigger") or {}
        r = trig.get("rule")
        try:
            return int(r)
        except Exception:
            return None

    def _order_type(o: Dict[str, Any]) -> str:
        """Return 'close-long-order' or 'close-short-order' or empty."""
        return str(o.get("order_type") or "").lower()

    def _size(o: Dict[str, Any]) -> Optional[int]:
        # New schema: size lives in initial.size
        initial = o.get("initial") or {}
        raw = initial.get("size") or o.get("size")
        try:
            return abs(int(float(raw))) if raw is not None else None
        except Exception:
            return None

    expected_tp_rule = 1 if str(side).upper() == "LONG" else 2
    expected_sl_rule = 2 if str(side).upper() == "LONG" else 1

    def _is_ok(o: Dict[str, Any], *, expected_rule: int) -> bool:
        # Validate order_type matches desired side.
        ot = _order_type(o)
        if ot:
            # close-long-order means the position was LONG → close side = sell
            expected_ot = "close-long-order" if str(side).upper() == "LONG" else "close-short-order"
            if ot != expected_ot:
                return False
        osz = _size(o)
        if osz is None or osz != int(abs_size):
            return False
        r = _rule(o)
        if r is not None and int(r) != int(expected_rule):
            return False
        return True

    def _cancel_all(orders: List[Dict[str, Any]]) -> None:
        for o in orders:
            oid = o.get("id")
            if not oid:
                continue
            try:
                executor.cancel_trigger_order(str(oid))
                log.info("Cancelled stale trigger order id=%s contract=%s", oid, contract)
            except Exception as _ce:
                log.warning("Failed to cancel trigger order id=%s: %s", oid, _ce)

    # Pull open trigger orders for this contract.
    try:
        open_triggers = executor.get_open_trigger_orders(contract=contract)
    except Exception:
        log.exception("Failed to list trigger orders for %s", contract)
        return replaced

    log.info(
        "TPSL-resync contract=%s side=%s abs_size=%d tp=%.6g sl=%.6g open_triggers=%d",
        contract, side, abs_size,
        tp_price if tp_price is not None else float("nan"),
        sl_price if sl_price is not None else float("nan"),
        len(open_triggers),
    )

    tp_orders = [o for o in open_triggers if _tag(o) == "t-qt-tp"]
    sl_orders = [o for o in open_triggers if _tag(o) == "t-qt-sl"]

    if tp_orders or sl_orders:
        log.info(
            "TPSL-resync existing: tp_orders=%d sl_orders=%d details=%s",
            len(tp_orders), len(sl_orders),
            [{"id": o.get("id"), "tag": _tag(o), "order_type": _order_type(o), "size": _size(o)} for o in (tp_orders + sl_orders)],
        )

    # Replace TP if missing or mismatched.
    if tp_price is not None:
        keep = [o for o in tp_orders if _is_ok(o, expected_rule=expected_tp_rule)]
        if keep:
            log.info("TPSL-resync TP already OK for %s (order_id=%s)", contract, keep[0].get("id"))
        else:
            stale = [o for o in tp_orders if not _is_ok(o, expected_rule=expected_tp_rule)]
            if stale:
                log.warning(
                    "TPSL-resync cancelling stale TP orders for %s: %s",
                    contract,
                    [{"id": o.get("id"), "order_type": _order_type(o), "size": _size(o)} for o in stale],
                )
                _cancel_all(stale)
            try:
                res = executor.place_tpsl_orders(
                    contract=contract,
                    position_side=str(side).upper(),
                    size=float(abs_size),
                    take_profit=float(tp_price),
                    stop_loss=None,
                    trigger_rule=int(trigger_rule),
                )
                tp_resp = res.get("tp") or {}
                log.warning(
                    "TPSL-resync placed TP for %s: order_id=%s trigger_price=%.6g",
                    contract, tp_resp.get("id"), tp_price,
                )
                if tp_resp.get("id"):
                    replaced["tp_order_id"] = str(tp_resp.get("id"))
            except Exception:
                log.exception("Failed to (re)place TP trigger for %s", contract)

    # Replace SL if missing or mismatched.
    if sl_price is not None:
        keep = [o for o in sl_orders if _is_ok(o, expected_rule=expected_sl_rule)]
        if keep:
            log.info("TPSL-resync SL already OK for %s (order_id=%s)", contract, keep[0].get("id"))
        else:
            stale = [o for o in sl_orders if not _is_ok(o, expected_rule=expected_sl_rule)]
            if stale:
                log.warning(
                    "TPSL-resync cancelling stale SL orders for %s: %s",
                    contract,
                    [{"id": o.get("id"), "order_type": _order_type(o), "size": _size(o)} for o in stale],
                )
                _cancel_all(stale)
            try:
                res = executor.place_tpsl_orders(
                    contract=contract,
                    position_side=str(side).upper(),
                    size=float(abs_size),
                    take_profit=None,
                    stop_loss=float(sl_price),
                    trigger_rule=int(trigger_rule),
                )
                sl_resp = res.get("sl") or {}
                log.warning(
                    "TPSL-resync placed SL for %s: order_id=%s trigger_price=%.6g",
                    contract, sl_resp.get("id"), sl_price,
                )
                if sl_resp.get("id"):
                    replaced["sl_order_id"] = str(sl_resp.get("id"))
            except Exception:
                log.exception("Failed to (re)place SL trigger for %s", contract)

    return replaced


def _position_direction_for_contract(positions: List[Dict[str, Any]], contract: str) -> int:
    for p in positions:
        if str(p.get("contract")) != contract:
            continue
        try:
            size = int(float(p.get("size", 0)))
        except Exception:
            size = 0
        if size > 0:
            return 1
        if size < 0:
            return -1
        return 0
    return 0


def _signal_direction(sig: Optional[Signal]) -> int:
    if sig is None:
        return 0
    return 1 if sig.side == "LONG" else -1


def _mk_entry_journal_record(
    *,
    ts: pd.Timestamp,
    asset: str,
    side: str,
    qty: float,
    entry_price: float,
    stop_price: float,
    stop_distance: float,
    leverage_implied: float,
    prediction: float,
    risk_at_stop: float,
    tp_price: Optional[float] = None,
    entry_order_id: Optional[str] = None,
    tp_order_id: Optional[str] = None,
    sl_order_id: Optional[str] = None,
    entry_fee: Optional[float] = None,
) -> Dict[str, Any]:
    rec = {
        "timestamp": ts,
        "asset": asset,
        "side": side,
        "qty": float(qty),
        "entry_price": float(entry_price),
        "stop_price": float(stop_price),
        "stop_distance": float(stop_distance),
        "leverage_implied": float(leverage_implied),
        "prediction": float(prediction),
        "risk_at_stop": float(risk_at_stop),
        "tp_price": float(tp_price) if tp_price is not None else None,
        "status": "OPEN",
    }
    if entry_order_id:
        rec["entry_order_id"] = str(entry_order_id)
    if tp_order_id:
        rec["tp_order_id"] = str(tp_order_id)
    if sl_order_id:
        rec["sl_order_id"] = str(sl_order_id)
    if entry_fee is not None:
        rec["entry_fee"] = float(entry_fee)
    return rec


def _mk_exit_journal_record(
    *,
    ts: pd.Timestamp,
    asset: str,
    side: str,
    qty: float,
    entry_price: float,
    exit_price: float,
    exit_reason: str,
    fee_rate: float,
    exit_order_id: Optional[str] = None,
) -> Dict[str, Any]:
    # Best-effort PnL calculation; for production, use fills from Gate endpoints.
    if side == "LONG":
        gross_pnl = (exit_price - entry_price) * qty
    else:
        gross_pnl = (entry_price - exit_price) * qty

    fees = abs(entry_price * qty) * fee_rate + abs(exit_price * qty) * fee_rate
    pnl = gross_pnl - fees

    rec = {
        "timestamp": ts,
        "asset": asset,
        "side": side,
        "qty": float(qty),
        "entry_price": float(entry_price),
        "exit_price": float(exit_price),
        "exit_reason": exit_reason,
        "gross_pnl": float(gross_pnl),
        "fees": float(fees),
        "pnl": float(pnl),
    }
    if exit_order_id:
        rec["exit_order_id"] = str(exit_order_id)
    return rec


def _parse_fill_from_order(order: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    """Best-effort parse of avg fill price and fee from a Gate futures order object."""
    avg_px = None
    fee = None

    for k in ("fill_price", "avg_deal_price", "avg_price", "price_avg"):
        if k in order:
            try:
                avg_px = float(order[k])
                break
            except Exception:
                pass

    for k in ("fee", "fees", "fee_usdt", "fee_total"):
        if k in order:
            try:
                fee = float(order[k])
                break
            except Exception:
                pass

    return avg_px, fee


def _fills_summary_for_order(
    executor: GateExecutor,
    *,
    contract: str,
    order_id: str,
    center_ts: pd.Timestamp,
    window_sec: int = 600,
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """Compute (vwap_price, total_fee, realized_pnl) for a given order id from my_trades.

    Gate trade fill objects typically include an order id field. We aggregate fills for that order id.
    """
    center_ts = pd.Timestamp(center_ts).tz_convert("UTC")
    from_ts = int((center_ts - pd.Timedelta(seconds=window_sec)).timestamp())
    to_ts = int((center_ts + pd.Timedelta(seconds=window_sec)).timestamp())

    trades = executor.get_my_trades(contract=contract, from_ts=from_ts, to_ts=to_ts)
    time.sleep(0.2)

    matched: List[Dict[str, Any]] = []
    for t in trades:
        oid = str(t.get("order_id", t.get("order", t.get("id", ""))))
        if oid == str(order_id):
            matched.append(t)

    if not matched:
        return None, None, None

    qty_sum = 0.0
    px_qty_sum = 0.0
    fee_sum = 0.0
    pnl_sum: Optional[float] = 0.0

    for t in matched:
        # Common fill fields.
        try:
            size = float(t.get("size", t.get("qty", 0.0)))
        except Exception:
            size = 0.0
        try:
            price = float(t.get("price", t.get("fill_price", 0.0)))
        except Exception:
            price = 0.0
        try:
            fee = float(t.get("fee", t.get("fees", 0.0)))
        except Exception:
            fee = 0.0
        rpnl_raw = None
        for k in ("realized_pnl", "realised_pnl", "pnl", "profit", "realized_profit", "realised_profit"):
            if k in t and t.get(k) is not None:
                rpnl_raw = t.get(k)
                break
        if rpnl_raw is None:
            rpnl = None
        else:
            try:
                rpnl = float(rpnl_raw)
            except Exception:
                rpnl = None

        qty_sum += abs(size)
        px_qty_sum += abs(size) * price
        fee_sum += fee
        if rpnl is None:
            pnl_sum = None
        elif pnl_sum is not None:
            pnl_sum += rpnl

    vwap = (px_qty_sum / qty_sum) if qty_sum > 0 else None
    return vwap, fee_sum, pnl_sum


def _get_quanto_multiplier(executor: GateExecutor, *, contract: str) -> float:
    """Gate futures quantity multiplier.

    Some contracts represent multiple coin units per 1 `size`.
    Gate exposes this via `quanto_multiplier` in contract detail.

    We use this to store journal quantities in the same units as Gate UI.
    """
    try:
        meta = executor.get_contract_detail(contract)
        qm = meta.get("quanto_multiplier")
        if qm is None:
            return 1.0
        qmf = float(qm)
        return qmf if qmf > 0 else 1.0
    except Exception:
        return 1.0


def _utc_now() -> pd.Timestamp:
    ts = pd.Timestamp.utcnow()
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _as_utc_timestamp(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _gross_pnl_from_prices(*, side: str, qty: float, entry_price: float, exit_price: float) -> float:
    if str(side).upper() == "LONG":
        return float((exit_price - entry_price) * qty)
    return float((entry_price - exit_price) * qty)


def _repair_recent_closures_from_gate(
    *,
    journal: Journal,
    executor: GateExecutor,
    cfg: Dict[str, Any],
    log: logging.Logger,
    limit: int = 100,
) -> None:
    """Repair recent closure rows from Gate fills; Gate realized PnL wins when present."""
    try:
        rows = journal.get_recent_closures_for_repair(limit=limit)
    except Exception:
        log.exception("Closure repair: failed to read recent closures")
        return

    for r in rows:
        try:
            exit_order_id = str(r.get("exit_order_id") or "").strip()
            if not exit_order_id:
                continue

            contract = _gate_contract_for_asset(str(r.get("asset")))
            closure_ts = _as_utc_timestamp(r.get("timestamp"))
            exit_vwap, exit_fee, exchange_rpnl = _fills_summary_for_order(
                executor,
                contract=contract,
                order_id=exit_order_id,
                center_ts=closure_ts,
                window_sec=6 * 3600,
            )
            if exit_vwap is None:
                continue

            entry_price = float(r.get("entry_price") or 0.0)
            entry_fee = float(r.get("entry_fee") or 0.0)
            qty = float(r.get("qty") or 0.0)

            entry_order_id = str(r.get("entry_order_id") or "").strip()
            trade_id = r.get("trade_id")
            if entry_order_id:
                try:
                    entry_center = _as_utc_timestamp(r.get("entry_ts") or r.get("timestamp"))
                    entry_vwap, gate_entry_fee, _ = _fills_summary_for_order(
                        executor,
                        contract=contract,
                        order_id=entry_order_id,
                        center_ts=entry_center,
                        window_sec=12 * 3600,
                    )
                    if entry_vwap is not None:
                        entry_price = float(entry_vwap)
                    if gate_entry_fee is not None:
                        entry_fee = float(gate_entry_fee)
                    if trade_id is not None:
                        journal.update_trade_entry_fill(
                            int(trade_id),
                            entry_price=entry_price,
                            entry_fee=entry_fee,
                        )
                except Exception:
                    log.exception("Closure repair: failed entry-fill lookup contract=%s order_id=%s", contract, entry_order_id)

            total_fees = float(entry_fee + float(exit_fee or 0.0))
            gross_pnl = _gross_pnl_from_prices(
                side=str(r.get("side") or "LONG"),
                qty=qty,
                entry_price=entry_price,
                exit_price=float(exit_vwap),
            )
            pnl = float(gross_pnl - total_fees)

            if exchange_rpnl is not None:
                pnl = float(exchange_rpnl)
                gross_pnl = float(pnl + total_fees)

            journal.log_trade_exit(
                {
                    "trade_id": int(trade_id) if trade_id is not None else None,
                    "timestamp": closure_ts,
                    "asset": r.get("asset"),
                    "side": r.get("side"),
                    "qty": qty,
                    "exit_order_id": exit_order_id,
                    "entry_price": entry_price,
                    "exit_price": float(exit_vwap),
                    "exit_reason": r.get("exit_reason") or "EXCHANGE_CLOSE",
                    "gross_pnl": gross_pnl,
                    "fees": total_fees,
                    "pnl": pnl,
                }
            )
        except Exception:
            log.exception("Closure repair failed for row=%s", r)


def _reconcile_journal_with_exchange(
    *,
    journal: Journal,
    executor: GateExecutor,
    positions: List[Dict[str, Any]],
    equity: float,
    cfg: Dict[str, Any],
    close_on_signal_change: bool,
    log: logging.Logger,
) -> None:
    """Close OPEN journal rows when the exchange position is already flat."""
    try:
        open_trades = journal.get_open_trades()
    except Exception:
        open_trades = []

    pos_size_by_contract: Dict[str, float] = {}
    for p in positions:
        try:
            c = str(p.get("contract", ""))
            if not c:
                continue
            pos_size_by_contract[c] = float(p.get("size", 0) or 0)
        except Exception:
            continue

    journal_contracts = set()
    for t in open_trades:
        try:
            journal_contracts.add(_gate_contract_for_asset(str(t.get("asset"))))
        except Exception:
            continue

    for p in positions:
        try:
            contract = str(p.get("contract") or "")
            size = float(p.get("size", 0) or 0)
            if contract and size != 0.0 and contract not in journal_contracts:
                log.critical(
                    "Startup/reconcile found exchange position without OPEN journal row: contract=%s size=%s",
                    contract,
                    size,
                )
        except Exception:
            continue

    for t in open_trades:
        try:
            asset = str(t.get("asset"))
            contract = _gate_contract_for_asset(asset)
            ex_size = float(pos_size_by_contract.get(contract, 0.0) or 0.0)
            if ex_size != 0.0:
                continue

            log.warning(
                "Reconcile %s: journal says OPEN but exchange size=0. Resolving closure. "
                "trade_id=%s entry_price=%s",
                contract,
                t.get("id") or t.get("trade_id"),
                t.get("entry_price"),
            )
            exit_reason = "EXCHANGE_CLOSE"
            exit_order_id: Optional[str] = None

            try:
                last_oid = journal.get_state_value(f"last_close_order_id_{contract}")
            except Exception:
                last_oid = None
            if last_oid:
                exit_order_id = str(last_oid)
                exit_reason = "SIGNAL_CLOSE" if close_on_signal_change else "MANUAL_CLOSE"

            for key, reason in (("tp_order_id", "TAKE_PROFIT"), ("sl_order_id", "STOP_LOSS")):
                oid = t.get(key)
                if not oid:
                    log.debug("Reconcile %s: no %s stored in journal row", contract, key)
                    continue
                try:
                    o = executor.get_trigger_order(str(oid))
                    status = str(o.get("status", "")).lower()
                    finish_as = str(o.get("finish_as", "") or "").lower()
                    fired_order_id = str(
                        o.get("order_id") or o.get("futures_order_id") or ""
                    ) or None
                    log.info(
                        "Reconcile %s: trigger order %s=%s status=%s finish_as=%s fired_order_id=%s",
                        contract, key, oid, status, finish_as, fired_order_id,
                    )
                    if status in {"finished", "triggered", "closed", "done"}:
                        exit_reason = reason
                        exit_order_id = fired_order_id
                        log.warning(
                            "Reconcile %s: %s triggered -> exit_reason=%s exit_order_id=%s",
                            contract, key.upper(), exit_reason, exit_order_id,
                        )
                        break
                except Exception:
                    log.exception("Reconcile %s: failed to fetch trigger order %s=%s", contract, key, oid)
                    continue

            entry_px = float(t.get("entry_price") or 0.0)
            qty = float(t.get("qty") or 0.0)
            side = str(t.get("side") or "LONG")
            center_ts = _utc_now()

            qm = _get_quanto_multiplier(executor, contract=contract)
            if qty > 0 and qm != 1.0 and qty < qm * 2:
                qty = float(qty * qm)

            exit_px = entry_px
            exit_fee = 0.0
            realized_pnl: Optional[float] = None
            if exit_order_id:
                vwap, fee, rpnl = _fills_summary_for_order(
                    executor,
                    contract=contract,
                    order_id=str(exit_order_id),
                    center_ts=center_ts,
                    window_sec=3600,
                )
                if vwap is not None:
                    exit_px = float(vwap)
                if fee is not None:
                    exit_fee = float(fee)
                realized_pnl = rpnl
            else:
                log.warning(
                    "Reconcile %s: no exit_order_id found; exit price will default to entry_price=%.6g",
                    contract, entry_px,
                )

            closure = _mk_exit_journal_record(
                ts=center_ts,
                asset=asset,
                side=side,
                qty=qty,
                entry_price=entry_px,
                exit_price=exit_px,
                exit_reason=exit_reason,
                fee_rate=float(cfg["execution"]["fee_rate"]),
                exit_order_id=exit_order_id,
            )

            try:
                entry_fee = float(t.get("entry_fee") or 0.0)
            except Exception:
                entry_fee = 0.0

            if exit_fee or entry_fee:
                closure["fees"] = float(entry_fee + float(exit_fee or 0.0))
                try:
                    closure["pnl"] = float(closure.get("gross_pnl", 0.0)) - float(closure.get("fees", 0.0))
                except Exception:
                    pass

            if realized_pnl is not None:
                closure["pnl"] = float(realized_pnl)
                try:
                    closure["gross_pnl"] = float(realized_pnl) + float(closure.get("fees", 0.0))
                except Exception:
                    pass

            closure["trade_id"] = int(t.get("trade_id"))

            journal.log_trade_exit(closure)
            journal.update_equity(ts=center_ts, equity=equity)

            log.warning(
                "Reconcile %s: JOURNAL CLOSED trade_id=%s exit_reason=%s exit_price=%.6g pnl=%s exit_order_id=%s",
                contract,
                closure.get("trade_id"),
                exit_reason,
                exit_px,
                closure.get("pnl"),
                exit_order_id,
            )

            if last_oid:
                try:
                    journal.set_state_value(f"last_close_order_id_{contract}", "", _utc_now())
                except Exception:
                    pass
        except Exception:
            log.exception("Reconciliation failed for open trade: %s", t)


def run_live(config_path: Path) -> None:
    # Load local .env for convenience in dev (does nothing if file missing).
    # Production should set real environment variables via the OS / secret manager.
    try:
        from quant_system.utils.env import load_dotenv

        load_dotenv(".env", override=False)
    except Exception:
        pass

    cfg = load_config(config_path)
    setup_logging(cfg)
    log = logging.getLogger("live_runner")

    # Exit policy:
    # - By default we do NOT close positions on signal flips/neutral.
    #   We let TP/SL on the exchange handle exits.
    # - If you explicitly want reversal-style trading, set:
    #   execution:
    #     close_on_signal_change: true
    close_on_signal_change = bool((cfg.get("execution") or {}).get("close_on_signal_change", False))

    # Optional TP/SL tuning (applied only to SHORT entries when enabled):
    # These values are multipliers on the RiskManager stop_distance.
    # Example: short_sl_mult=0.6 makes SHORT stop 40% tighter vs RM; short_tp_mult=0.5 makes TP half of (1R).
    exec_cfg = (cfg.get("execution") or {})
    short_tpsl_enabled = bool(exec_cfg.get("short_tpsl_override", False))
    short_sl_mult = float(exec_cfg.get("short_sl_mult", 1.0) or 1.0)
    short_tp_mult = float(exec_cfg.get("short_tp_mult", 1.0) or 1.0)

    # Gate trigger rule for TP/SL plan orders (default: last price).
    try:
        trigger_rule = int(exec_cfg.get("trigger_rule", 1) or 1)
    except Exception:
        trigger_rule = 1
    # Guard rails
    if short_sl_mult <= 0:
        short_sl_mult = 1.0
    if short_tp_mult <= 0:
        short_tp_mult = 1.0

    # Leverage bounds. Defaults preserve prior behavior (max 20x) unless configured.
    # Add to config.yaml if you want dynamic bounds, e.g.:
    # execution:
    #   leverage_min: 5
    #   leverage_max: 50
    lev_min = int(cfg.get("execution", {}).get("leverage_min", 1))
    lev_max = int(cfg.get("execution", {}).get("leverage_max", 20))
    if lev_min < 1:
        lev_min = 1
    if lev_max < lev_min:
        lev_max = lev_min

    if str(cfg.get("execution_mode", "mock")).lower() != "gate":
        log.warning("execution_mode is not 'gate'. live_runner will still run, but Gate settings are required.")

    assets: List[str] = list(cfg["assets"])
    timeframe: str = str(cfg["system"]["timeframe"]).upper()

    db = Database(db_path=Path(cfg["paths"]["db_path"]), schema_path=Path(cfg["paths"]["schema_path"]))
    db.initialize()
    journal = Journal(db)

    models_dir = Path(cfg["paths"]["models_dir"])
    signaler = SignalGenerator(cfg, models_dir=models_dir)
    risk = RiskManager(cfg)

    gate_cfg = cfg.get("gate", {})

    api_key = os.environ.get("GATE_API_KEY")
    api_secret = os.environ.get("GATE_API_SECRET")
    if not api_key or not api_secret:
        raise RuntimeError(
            "Missing Gate credentials. Set environment variables GATE_API_KEY and GATE_API_SECRET."
        )

    executor = GateExecutor(
        api_key=str(api_key),
        api_secret=str(api_secret),
        base_url=str(gate_cfg.get("base_url", "https://fx-api.gateio.ws/api/v4")),
        fee_rate=float(cfg["execution"]["fee_rate"]),
        slippage=float(cfg["execution"]["slippage_bps"]) / 10000.0,
    )

    csv_dir = Path(cfg["data"]["csv_dir"])

    # Peak equity is used for drawdown kill-switch.
    # For live/testnet we intentionally initialize from the exchange (not config),
    # so you can manage balances directly on the exchange without editing YAML.
    peak_equity: Optional[float] = None
    persisted_peak = journal.get_state_value("peak_equity")
    if persisted_peak is not None:
        try:
            peak_equity = float(persisted_peak)
        except Exception:
            peak_equity = None

    # Fetch exchange equity once at startup so we can sanity-check persisted peak.
    # This avoids an immediate kill-switch when the DB contains a peak from a previous run
    # (common on testnet when balances are reset).
    try:
        startup_equity = float(executor.get_account_equity())
        time.sleep(0.2)
    except Exception:
        startup_equity = None

    if startup_equity is not None:
        if peak_equity is None:
            peak_equity = startup_equity
        else:
            # If saved peak is wildly above current equity, treat it as stale and reset.
            # Example: config used 10000 but testnet account has ~1400.
            if peak_equity > startup_equity * 1.25:
                peak_equity = startup_equity
        journal.set_state_value("peak_equity", str(peak_equity), pd.Timestamp.utcnow())

        try:
            startup_positions = executor.get_open_positions()
            time.sleep(0.2)
            _reconcile_journal_with_exchange(
                journal=journal,
                executor=executor,
                positions=startup_positions,
                equity=float(startup_equity),
                cfg=cfg,
                close_on_signal_change=close_on_signal_change,
                log=log,
            )
            _repair_recent_closures_from_gate(
                journal=journal,
                executor=executor,
                cfg=cfg,
                log=log,
            )
        except Exception:
            log.exception("Startup reconciliation failed")

    last_processed: Dict[str, pd.Timestamp] = {}

    log.info("Starting live runner. Assets=%s timeframe=%s poll=60s", assets, timeframe)

    while True:
        try:
            # ------------------------------------------------------------
            # PANIC BREAKER: force close all open positions (manual trigger)
            # How to use:
            #   - create file: breakers/PANIC_CLOSE_ALL
            # The runner will:
            #   1) close all positions via reduce direction market orders
            #   2) set runner_state panic_close_active=true
            #   3) skip entries while the file exists
            # ------------------------------------------------------------
            try:
                if PANIC_CLOSE_FILE.exists():
                    BREAKERS_DIR.mkdir(parents=True, exist_ok=True)
                    journal.set_state_value("panic_close_active", "true", pd.Timestamp.utcnow())

                    positions_now = executor.get_open_positions() or []
                    closed_any = False
                    for p in positions_now:
                        try:
                            contract = str(p.get("contract", ""))
                            if not contract:
                                continue
                            size_raw = p.get("size", 0)
                            size = float(size_raw)
                            if size == 0:
                                continue
                            # Reduce-only isn't supported on this endpoint in our adapter;
                            # we send the opposite signed size to flatten.
                            close_size = -int(size)
                            if close_size == 0:
                                continue
                            executor.place_market_order(contract=contract, size=close_size)
                            closed_any = True
                            time.sleep(0.2)
                        except Exception as e:
                            log.error("PANIC_CLOSE failed for contract=%s err=%s", p.get("contract"), e)
                            continue

                    if closed_any:
                        log.warning("PANIC_CLOSE_ALL executed: attempted to flatten all open positions.")
                    else:
                        log.warning("PANIC_CLOSE_ALL active but no open positions found.")

                    # While breaker exists, do not run normal trading logic.
                    time.sleep(5)
                    continue
                else:
                    # Clear the flag when breaker file is removed.
                    if journal.get_state_value("panic_close_active") == "true":
                        journal.set_state_value("panic_close_active", "false", pd.Timestamp.utcnow())
            except Exception:
                # Never block the main loop on breaker state IO.
                pass

            # Equity must come from exchange.
            equity = float(executor.get_account_equity())
            time.sleep(0.2)

            # If peak-equity still isn't known (e.g., startup_equity couldn't be fetched earlier), set now.
            if peak_equity is None:
                peak_equity = equity

            peak_equity = max(peak_equity, equity)
            drawdown = 0.0 if peak_equity == 0 else (equity - peak_equity) / peak_equity
            journal.set_state_value("peak_equity", str(peak_equity), pd.Timestamp.utcnow())
            if drawdown <= -0.25:
                log.critical(
                    "KILL SWITCH: drawdown %.2f%% exceeds 25%%. equity=%.2f peak=%.2f. Stopping runner.",
                    drawdown * 100.0,
                    equity,
                    peak_equity,
                )
                break

            # Reconciliation must run on every poll, not only when a candle closes.
            positions = executor.get_open_positions()
            time.sleep(0.2)
            _reconcile_journal_with_exchange(
                journal=journal,
                executor=executor,
                positions=positions,
                equity=equity,
                cfg=cfg,
                close_on_signal_change=close_on_signal_change,
                log=log,
            )
            _repair_recent_closures_from_gate(
                journal=journal,
                executor=executor,
                cfg=cfg,
                log=log,
            )

            # Candle detection per asset.
            new_candle_assets: List[str] = []
            latest_closed_ts: Dict[str, pd.Timestamp] = {}
            for asset in assets:
                contract = _gate_contract_for_asset(asset)

                # Primary: real exchange candlesticks (public endpoint).
                ts_closed = _latest_closed_candle_ts_from_gate(
                    executor=executor,
                    contract=contract,
                    timeframe=timeframe,
                )

                # If exchange has no data (or asset not listed), fall back to CSV if it exists.
                if ts_closed is None:
                    asset_csv = csv_dir / f"{asset}.csv"
                    if asset_csv.exists():
                        try:
                            ts_closed = _latest_closed_candle_ts(asset_csv, timeframe=timeframe)
                        except Exception:
                            ts_closed = None

                if ts_closed is None:
                    log.warning("No candle data available yet for asset=%s. Skipping.", asset)
                    continue

                latest_closed_ts[asset] = ts_closed
                if asset not in last_processed or ts_closed > last_processed[asset]:
                    new_candle_assets.append(asset)

            if not new_candle_assets:
                time.sleep(60)
                continue

            # Only act on new candle close.
            log.info("New closed candle detected for assets=%s", new_candle_assets)
            for a in new_candle_assets:
                log.info("Candle detected: asset=%s ts=%s", a, str(latest_closed_ts[a]))

            if not signaler.is_ready():
                log.error("Model/threshold not found in %s. Waiting...", models_dir)
                # Update last_processed so we don't spin on the same candle.
                for a in new_candle_assets:
                    last_processed[a] = latest_closed_ts[a]
                time.sleep(60)
                continue

            # Build latest features (cross-section).
            latest_feats = _compute_latest_features(cfg, executor=executor)
            # Filter to the candle timestamps we detected (strict close-only generation).
            latest_feats = latest_feats[latest_feats["asset"].isin(new_candle_assets)].copy()

            # It’s possible some assets' feature rows lag (warmup NaNs). Skip those gracefully.
            if latest_feats.empty:
                log.warning("No feature rows available for new candles (likely warmup).")
                for a in new_candle_assets:
                    last_processed[a] = latest_closed_ts[a]
                time.sleep(60)
                continue

            # Pull positions once per loop.
            positions = executor.get_open_positions()
            time.sleep(0.2)

            # Reconciliation: if journal says OPEN but exchange position is flat, close it in journal.
            try:
                open_trades = journal.get_open_trades()
            except Exception:
                open_trades = []

            pos_size_by_contract: Dict[str, float] = {}
            for p in positions:
                try:
                    c = str(p.get("contract", ""))
                    if not c:
                        continue
                    pos_size_by_contract[c] = float(p.get("size", 0) or 0)
                except Exception:
                    continue

            for t in open_trades:
                try:
                    asset = str(t.get("asset"))
                    contract = _gate_contract_for_asset(asset)
                    ex_size = float(pos_size_by_contract.get(contract, 0.0) or 0.0)
                    if ex_size != 0.0:
                        continue  # still open on exchange

                    # Exchange is flat: detect whether TP or SL executed.
                    log.warning(
                        "Reconcile %s: journal says OPEN but exchange size=0. Resolving closure. "
                        "trade_id=%s entry_price=%s",
                        contract,
                        t.get("id") or t.get("trade_id"),
                        t.get("entry_price"),
                    )
                    exit_reason = "EXCHANGE_CLOSE"
                    exit_order_id: Optional[str] = None

                    # If we previously sent a close order (signal-close path), prefer that order id for fills.
                    # This makes realized PnL accurate and avoids placeholder math.
                    try:
                        last_oid = journal.get_state_value(f"last_close_order_id_{contract}")
                    except Exception:
                        last_oid = None
                    if last_oid:
                        exit_order_id = str(last_oid)
                        # If user enabled dynamic close, keep reason SIGNAL_CLOSE; otherwise treat as MANUAL_CLOSE
                        # because it is a discretionary close not caused by TP/SL trigger.
                        exit_reason = "SIGNAL_CLOSE" if close_on_signal_change else "MANUAL_CLOSE"
                    # If a trigger order exists and is finished, use that.
                    for key, reason in (("tp_order_id", "TAKE_PROFIT"), ("sl_order_id", "STOP_LOSS")):
                        oid = t.get(key)
                        if not oid:
                            log.debug("Reconcile %s: no %s stored in journal row", contract, key)
                            continue
                        try:
                            o = executor.get_trigger_order(str(oid))
                            status = str(o.get("status", "")).lower()
                            # finish_as holds "take_profit"/"stop_loss" when applicable.
                            finish_as = str(o.get("finish_as", "") or "").lower()
                            # order_id is the futures order generated when the trigger fires.
                            # `id` is the plan-order's own ID — do NOT use it as exit order.
                            fired_order_id = str(
                                o.get("order_id") or o.get("futures_order_id") or ""
                            ) or None
                            log.info(
                                "Reconcile %s: trigger order %s=%s status=%s finish_as=%s fired_order_id=%s",
                                contract, key, oid, status, finish_as, fired_order_id,
                            )
                            if status in {"finished", "triggered", "closed", "done"}:
                                exit_reason = reason
                                exit_order_id = fired_order_id
                                log.warning(
                                    "Reconcile %s: %s TRIGGERED → exit_reason=%s exit_order_id=%s",
                                    contract, key.upper(), exit_reason, exit_order_id,
                                )
                                break
                        except Exception:
                            log.exception("Reconcile %s: failed to fetch trigger order %s=%s", contract, key, oid)
                            continue

                    log.info(
                        "Reconcile %s: exchange FLAT → exit_reason=%s exit_order_id=%s",
                        contract, exit_reason, exit_order_id,
                    )

                    # Best-effort exit price/fees/pnl from fills.
                    entry_px = float(t.get("entry_price") or 0.0)
                    qty = float(t.get("qty") or 0.0)
                    side = str(t.get("side") or "LONG")
                    center_ts = pd.Timestamp.utcnow().tz_localize("UTC")

                    # Journal qty should be in Gate UI units; ensure it's normalized.
                    # (Older rows might still be base size.)
                    qm = _get_quanto_multiplier(executor, contract=contract)
                    if qty > 0 and qm != 1.0:
                        # Heuristic: if qty looks like base size, upscale.
                        # Example: XRP base size 63 but UI qty 630.
                        if qty < qm * 2:
                            qty = float(qty * qm)

                    exit_px = entry_px
                    exit_fee = 0.0
                    realized_pnl: Optional[float] = None
                    if exit_order_id:
                        vwap, fee, rpnl = _fills_summary_for_order(
                            executor,
                            contract=contract,
                            order_id=str(exit_order_id),
                            center_ts=center_ts,
                            window_sec=3600,
                        )
                        if vwap is not None:
                            exit_px = float(vwap)
                        if fee is not None:
                            exit_fee = float(fee)
                        realized_pnl = rpnl
                    else:
                        log.warning(
                            "Reconcile %s: no exit_order_id found — exit price will default to entry_price=%.6g",
                            contract, entry_px,
                        )

                    closure = _mk_exit_journal_record(
                        ts=center_ts,
                        asset=asset,
                        side=side,
                        qty=qty,
                        entry_price=entry_px,
                        exit_price=exit_px,
                        exit_reason=exit_reason,
                        fee_rate=float(cfg["execution"]["fee_rate"]),
                        exit_order_id=exit_order_id,
                    )

                    # Prefer exchange-derived fees when available.
                    # Total fees should include entry-side fee (if recorded) + exit-side fee (from fills).
                    try:
                        entry_fee = float(t.get("entry_fee") or 0.0)
                    except Exception:
                        entry_fee = 0.0

                    if exit_fee or entry_fee:
                        closure["fees"] = float(entry_fee + float(exit_fee or 0.0))

                        # If we're not using exchange-provided realized pnl, recompute pnl from gross-fees.
                        # (gross_pnl is already in UI qty units because qty is).
                        try:
                            closure["pnl"] = float(closure.get("gross_pnl", 0.0)) - float(closure.get("fees", 0.0))
                        except Exception:
                            pass

                    if realized_pnl is not None:
                        # Gate's realized_pnl (if present) is reported in USDT (already fee-aware on Gate side).
                        # Keep it as-is, but still keep our fee breakdown.
                        closure["pnl"] = float(realized_pnl)
                        try:
                            closure["gross_pnl"] = float(realized_pnl) + float(closure.get("fees", 0.0))
                        except Exception:
                            pass
                    # Link to trade_id directly for accuracy.
                    closure["trade_id"] = int(t.get("trade_id"))

                    journal.log_trade_exit(closure)
                    journal.update_equity(ts=center_ts, equity=equity)

                    log.warning(
                        "Reconcile %s: JOURNAL CLOSED trade_id=%s exit_reason=%s exit_price=%.6g "
                        "pnl=%s exit_order_id=%s",
                        contract,
                        closure.get("trade_id"),
                        exit_reason,
                        exit_px,
                        closure.get("pnl"),
                        exit_order_id,
                    )

                    # Clear last close hint to avoid reusing it.
                    if last_oid:
                        try:
                            journal.set_state_value(f"last_close_order_id_{contract}", "", pd.Timestamp.utcnow())
                        except Exception:
                            pass
                except Exception:
                    log.exception("Reconciliation failed for open trade: %s", t)

            # Exposure monitoring: warn if abs(position_value)/equity is too high.
            exposure = 0.0
            for p in positions:
                try:
                    value = float(p.get("value", 0.0))
                except Exception:
                    value = 0.0
                exposure += abs(value)
            if equity > 0:
                exposure_x = exposure / equity
                if exposure_x >= 6.0:
                    log.warning("High exposure detected: %.2fx equity (exposure=%.2f equity=%.2f)", exposure_x, exposure, equity)

            # Generate signals from the latest feature rows.
            signals = signaler.generate_signals(latest_feats)
            sig_by_asset: Dict[str, Signal] = {s.asset: s for s in signals}
            for asset in new_candle_assets:
                sig = sig_by_asset.get(asset)
                if sig is not None:
                    log.info(
                        "Signal generated: asset=%s ts=%s side=%s pred=%.6f",
                        sig.asset,
                        str(sig.timestamp),
                        sig.side,
                        sig.prediction,
                    )

            # Position management: close on invalid / reversal.
            for asset in new_candle_assets:
                contract = _gate_contract_for_asset(asset)
                pos_dir = _position_direction_for_contract(positions, contract)
                sig_dir = _signal_direction(sig_by_asset.get(asset))

                # If a position exists but signal is neutral or opposite -> close.
                if close_on_signal_change and pos_dir != 0 and sig_dir != pos_dir:
                    log.info("Closing position due to signal change: contract=%s pos_dir=%d sig_dir=%d", contract, pos_dir, sig_dir)
                    close_res = executor.close_position(contract)
                    time.sleep(0.2)
                    if close_res is not None:
                        # IMPORTANT:
                        # Do NOT journal a closure here.
                        # Rationale:
                        # - On signal-close we often cannot recover entry_price/qty precisely from Gate without
                        #   extra endpoints, so any PnL we write can be wrong.
                        # - We instead rely on the reconciliation block above:
                        #     journal OPEN trade + exchange flat => fetch fills by exit_order_id (TP/SL/manual)
                        #   and log an accurate closure (or best-effort EXCHANGE_CLOSE).
                        close_order_id = str(close_res.get("id", ""))
                        if close_order_id:
                            journal.set_state_value(
                                f"last_close_order_id_{contract}",
                                close_order_id,
                                pd.Timestamp.utcnow(),
                            )
                        log.warning(
                            "Signal-close sent to exchange (contract=%s), closure will be recorded by reconciliation to avoid wrong PnL.",
                            contract,
                        )
                elif (not close_on_signal_change) and pos_dir != 0 and sig_dir != pos_dir:
                    # Visibility log only. Do not close.
                    log.info(
                        "Signal differs from current position, but close_on_signal_change=false. Holding position: contract=%s pos_dir=%d sig_dir=%d",
                        contract,
                        pos_dir,
                        sig_dir,
                    )

            # Refresh positions after potential closes.
            positions = executor.get_open_positions()
            time.sleep(0.2)

            # TP/SL resync: ensure every open exchange position has matching reduce-only triggers.
            # Best-effort and low frequency (only on new candle detection).
            try:
                open_by_contract: Dict[str, Dict[str, Any]] = {}
                try:
                    for t in journal.get_open_trades():
                        c = _gate_contract_for_asset(str(t.get("asset")))
                        open_by_contract[c] = t
                except Exception:
                    open_by_contract = {}

                for p in positions:
                    c = str(p.get("contract") or "")
                    if not c:
                        continue
                    try:
                        sz = float(p.get("size", 0) or 0)
                    except Exception:
                        sz = 0.0
                    if sz == 0.0:
                        continue

                    pos_side = "LONG" if sz > 0 else "SHORT"
                    abs_size = int(abs(sz))
                    jt = open_by_contract.get(c) or {}
                    tp_px = jt.get("tp_price")
                    sl_px = jt.get("stop_price")
                    tp_px_f = float(tp_px) if tp_px is not None else None
                    sl_px_f = float(sl_px) if sl_px is not None else None

                    replaced_orders = _ensure_tpsl_for_position(
                        executor=executor,
                        contract=c,
                        side=pos_side,
                        abs_size=abs_size,
                        tp_price=tp_px_f,
                        sl_price=sl_px_f,
                        trigger_rule=int(trigger_rule),
                        log=log,
                    )
                    trade_id = jt.get("trade_id")
                    if trade_id and (replaced_orders.get("tp_order_id") or replaced_orders.get("sl_order_id")):
                        journal.update_trade_order_ids(
                            int(trade_id),
                            tp_order_id=replaced_orders.get("tp_order_id"),
                            sl_order_id=replaced_orders.get("sl_order_id"),
                        )
            except Exception:
                log.exception("TP/SL resync failed")

            # Cap concurrently open pairs (contracts).
            max_open_pairs = int((cfg.get("execution") or {}).get("max_open_pairs", 5) or 0)
            open_contracts = {
                str(p.get("contract"))
                for p in positions
                if float(p.get("size", 0) or 0) != 0 and str(p.get("contract"))
            }

            # ── Agent pause-entries flag check ────────────────────────────────
            _agent_flags_path = os.path.join(os.path.dirname(__file__), "agent", ".runner_flags.yaml")
            _agent_pause = False
            try:
                if os.path.exists(_agent_flags_path):
                    with open(_agent_flags_path, "r", encoding="utf-8") as _fh:
                        _flags = yaml.safe_load(_fh) or {}
                    _agent_pause = bool(_flags.get("pause_entries", False))
                    _pause_until = _flags.get("pause_entries_until")
                    if _agent_pause and _pause_until:
                        import pandas as _pd
                        _until_ts = _pd.Timestamp(_pause_until)
                        if _pd.Timestamp.utcnow().tz_localize("UTC") >= _until_ts:
                            # Pause sudah expired — clear flag otomatis
                            _flags["pause_entries"] = False
                            _flags["pause_entries_until"] = None
                            with open(_agent_flags_path, "w", encoding="utf-8") as _fh2:
                                yaml.dump(_flags, _fh2, allow_unicode=True)
                            _agent_pause = False
                            log.info("Agent pause_entries expired, auto-cleared")
            except Exception:
                log.warning("Failed to read agent runner flags; proceeding normally")
                _agent_pause = False

            if _agent_pause:
                log.warning("Agent flag: pause_entries=True — skipping all new entries this tick")

            # Entry logic: if no position and have a signal -> size + leverage + order.
            for asset in new_candle_assets:
                contract = _gate_contract_for_asset(asset)
                pos_dir = _position_direction_for_contract(positions, contract)
                sig = sig_by_asset.get(asset)
                if sig is None or pos_dir != 0:
                    continue

                # Agent pause check
                if _agent_pause:
                    log.info("Skipping entry (agent pause): asset=%s", asset)
                    continue

                # Gate futures `size` must be a non-zero integer (contracts).
                # We enforce a minimum size of 1 contract to avoid a hard failure
                # when RiskManager's float qty truncates to 0.
                min_contract_size = int((cfg.get("execution") or {}).get("min_contract_size", 1) or 1)
                if min_contract_size < 1:
                    min_contract_size = 1

                # Enforce max open pairs cap.
                if max_open_pairs > 0 and contract not in open_contracts and len(open_contracts) >= max_open_pairs:
                    log.info(
                        "Max open pairs reached (%d). Skipping entry: asset=%s contract=%s",
                        max_open_pairs,
                        asset,
                        contract,
                    )
                    continue

                row = latest_feats[latest_feats["asset"] == asset]
                if row.empty:
                    continue
                bar = row.iloc[0]

                # Compute open_positions risk snapshot from exchange positions.
                open_pos_map: Dict[str, Dict[str, Any]] = {}
                for p in positions:
                    c = str(p.get("contract", ""))
                    try:
                        size = float(p.get("size", 0))
                    except Exception:
                        size = 0.0
                    if size == 0:
                        continue
                    open_pos_map[c] = {"risk_at_stop": 0.0}

                rm = risk.size_position(signal=sig, bar=bar, equity=equity, open_positions=open_pos_map)
                if rm is None:
                    log.info("RiskManager rejected trade: asset=%s", asset)
                    continue

                # Portfolio risk OK if RM succeeded.
                portfolio_risk_ok = True

                # Leverage: use implied leverage rounded up, then clamp to configured bounds.
                lev = int(max(lev_min, min(lev_max, np.ceil(rm["leverage_implied"])) ))
                executor.set_leverage(contract=contract, leverage=lev)
                time.sleep(0.2)

                # Gate size must be signed integer.
                # RiskManager returns float qty; if it truncates to 0, we must skip (or clamp).
                raw_qty = float(rm.get("qty", 0.0) or 0.0)
                qty_int = int(raw_qty)
                if qty_int < min_contract_size:
                    log.warning(
                        "Computed qty rounds to 0/smaller-than-min; skipping entry to avoid invalid order: asset=%s contract=%s raw_qty=%.6f qty_int=%d min_contract_size=%d",
                        asset,
                        contract,
                        raw_qty,
                        qty_int,
                        min_contract_size,
                    )
                    continue

                signed_size = qty_int if sig.side == "LONG" else -qty_int
                order = executor.place_market_order(
                    contract=contract,
                    size=signed_size,
                    open_positions=positions,
                    portfolio_risk_ok=portfolio_risk_ok,
                )
                time.sleep(0.2)
                order_id = str(order.get("id", ""))
                log.info("Order submitted: asset=%s contract=%s size=%s order_id=%s", asset, contract, signed_size, order_id)

                # Update open-contracts set so we don't exceed cap within the same loop.
                open_contracts.add(contract)

                entry_px = float(bar["close"])
                entry_fee: float = 0.0
                if order_id:
                    vwap, fee, _ = _fills_summary_for_order(
                        executor,
                        contract=contract,
                        order_id=order_id,
                        center_ts=latest_closed_ts[asset],
                    )
                    if vwap is not None:
                        entry_px = float(vwap)
                    if fee is not None:
                        entry_fee = float(fee)

                # Journal entry (best-effort entry_price from CSV close)
                # TP: simple 1R target for visibility (can be replaced with a smarter policy later).
                tp_price: Optional[float] = None
                try:
                    rm_stop_price = float(rm["stop_price"])
                    rm_stop_dist = float(rm["stop_distance"])

                    # Optional: make SHORT TP/SL tighter than LONG.
                    if sig.side == "SHORT" and short_tpsl_enabled:
                        sl_dist = rm_stop_dist * short_sl_mult
                        tp_dist = rm_stop_dist * short_tp_mult
                        stop_price = float(entry_px + sl_dist)
                        tp_price = float(entry_px - tp_dist)
                        rm["stop_price"] = float(stop_price)
                        rm["stop_distance"] = float(sl_dist)
                    else:
                        stop_price = rm_stop_price
                        if sig.side == "LONG":
                            tp_price = float(entry_px + (entry_px - stop_price))
                        else:
                            tp_price = float(entry_px - (stop_price - entry_px))
                except Exception:
                    tp_price = None

                entry = _mk_entry_journal_record(
                    ts=latest_closed_ts[asset],
                    asset=asset,
                    side=sig.side,
                    qty=float(abs(signed_size)) * _get_quanto_multiplier(executor, contract=contract),
                    entry_price=entry_px,
                    stop_price=float(rm["stop_price"]),
                    stop_distance=float(rm["stop_distance"]),
                    leverage_implied=float(rm["leverage_implied"]),
                    prediction=float(sig.prediction),
                    risk_at_stop=float(rm["risk_at_stop"]),
                    tp_price=tp_price,
                    entry_order_id=order_id or None,
                )

                # Place TP/SL on exchange immediately (best-effort).
                # We use reduce-only trigger orders so they only close, never add margin.
                tp_order_id: Optional[str] = None
                sl_order_id: Optional[str] = None
                try:
                    tpsl_res = executor.place_tpsl_orders(
                        contract=contract,
                        position_side=sig.side,
                        size=float(abs(signed_size)),
                        take_profit=tp_price,
                        stop_loss=float(rm["stop_price"]),
                        trigger_rule=int(trigger_rule),
                    )
                    try:
                        if isinstance(tpsl_res, dict):
                            if tpsl_res.get("tp") and isinstance(tpsl_res.get("tp"), dict):
                                tp_order_id = str(tpsl_res["tp"].get("id", "")) or None
                            if tpsl_res.get("sl") and isinstance(tpsl_res.get("sl"), dict):
                                sl_order_id = str(tpsl_res["sl"].get("id", "")) or None
                        log.warning(
                            "TPSL placed for %s %s: tp_order_id=%s tp_price=%s sl_order_id=%s sl_price=%s",
                            asset, sig.side,
                            tp_order_id, tp_price,
                            sl_order_id, rm.get("stop_price"),
                        )
                    except Exception:
                        pass
                except Exception:
                    log.exception("Failed to place TP/SL trigger orders: asset=%s contract=%s", asset, contract)

                # Attach exchange-derived fee and TP/SL order ids for audit.
                entry["entry_fee"] = float(entry_fee) if entry_fee else None
                if tp_order_id:
                    entry["tp_order_id"] = tp_order_id
                if sl_order_id:
                    entry["sl_order_id"] = sl_order_id

                journal.log_trade_entry(entry)
                journal.update_equity(ts=latest_closed_ts[asset], equity=equity)

            # Mark processed candles.
            for a in new_candle_assets:
                last_processed[a] = latest_closed_ts[a]

        except Exception as e:  # noqa: BLE001
            logging.getLogger("live_runner").exception("Live runner loop error: %s", str(e))

        time.sleep(60)


def main() -> None:
    root = Path(__file__).resolve().parent
    config_path = root / "quant_system" / "config.yaml"
    run_live(config_path)


if __name__ == "__main__":
    main()
