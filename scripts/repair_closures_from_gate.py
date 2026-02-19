"""Repair trade_closures PnL/fees/exit_price using Gate.io fills.

Why:
- Historical closures may have been journaled with placeholder math (entry=exit, qty rounded, etc.)
- Gate provides fill-level realized PnL and fees via /futures/usdt/my_trades.

This script:
1) Loads config + Gate credentials from environment (.env supported by quant_system.utils.env)
2) Reads recent rows from SQLite trade_closures where exit_order_id is present
3) For each closure, joins back to trades.entry_order_id (when available)
4) Pulls *fill-level trades* from Gate for both entry and exit order ids,
    then recomputes (exchange-accurate, best-effort):
    - qty (abs sum sizes from ENTRY fills)
    - entry_price (ENTRY VWAP)
    - exit_price (EXIT VWAP)
    - fees_total (entry fees + exit fees)
    - gross_pnl (price diff * qty)
    - pnl (gross_pnl - fees_total)
5) Updates SQLite rows in-place:
    - trade_closures: qty, entry_price, exit_price, fees, pnl, gross_pnl
    - trades: qty, entry_price, entry_fee (when entry fills are available)

Safety:
- Only updates rows where Gate returns at least one fill for the exit_order_id.
- Leaves rows unchanged if Gate query fails or no fills match.

Run from repo root:
  python scripts/repair_closures_from_gate.py --limit 200

Optional:
  --db quant_system/database/quant_system.sqlite
  --dry-run
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import yaml

# Ensure repo root is importable when running as a script on Windows.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_system.execution.gate_executor import GateExecutor


def _load_cfg(root: Path) -> Dict[str, Any]:
    return yaml.safe_load((root / "quant_system" / "config.yaml").read_text(encoding="utf-8"))


def _mk_executor(cfg: Dict[str, Any]) -> GateExecutor:
    # Load .env for convenience if available.
    try:
        from quant_system.utils.env import load_dotenv

        load_dotenv(".env", override=False)
    except Exception:
        pass

    import os

    api_key = os.environ.get("GATE_API_KEY")
    api_secret = os.environ.get("GATE_API_SECRET")
    if not api_key or not api_secret:
        raise RuntimeError("Missing GATE_API_KEY/GATE_API_SECRET in environment")

    gate = cfg.get("gate") or {}
    execution = cfg.get("execution") or {}

    return GateExecutor(
        api_key=str(api_key),
        api_secret=str(api_secret),
        base_url=str(gate.get("base_url", "https://api.gateio.ws/api/v4")),
        fee_rate=float(execution.get("fee_rate", 0.0)),
        slippage=float(execution.get("slippage_bps", 0.0)) / 10000.0,
    )


def _fills_summary_for_order(
    executor: GateExecutor,
    *,
    contract: str,
    order_id: str,
    center_ts: pd.Timestamp,
    window_sec: int = 6 * 3600,
) -> Tuple[Optional[float], Optional[float], Optional[float], int]:
    center_ts = pd.Timestamp(center_ts).tz_convert("UTC")
    from_ts = int((center_ts - pd.Timedelta(seconds=window_sec)).timestamp())
    to_ts = int((center_ts + pd.Timedelta(seconds=window_sec)).timestamp())

    trades = executor.get_my_trades(contract=contract, from_ts=from_ts, to_ts=to_ts) or []

    matched: List[Dict[str, Any]] = []
    s_order = str(order_id)
    for t in trades:
        oid = str(t.get("order_id", t.get("order", t.get("id", ""))))
        if oid == s_order:
            matched.append(t)

    if not matched:
        return None, None, None, 0

    qty_sum = 0.0
    px_qty_sum = 0.0
    fee_sum = 0.0
    pnl_sum: Optional[float] = 0.0

    for t in matched:
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
        # Gate futures my_trades on some accounts does NOT include realized pnl.
        # Prefer common keys; if none exist, we return None and let caller compute from prices.
        rpnl_val = None
        for k in ("realized_pnl", "realised_pnl", "pnl", "profit", "realized_profit", "realised_profit"):
            if k in t and t.get(k) is not None:
                rpnl_val = t.get(k)
                break

        if rpnl_val is None:
            rpnl = None
        else:
            try:
                rpnl = float(rpnl_val)
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
    return vwap, fee_sum, pnl_sum, len(matched)


def _compute_gross_pnl_from_prices(*, side: str, qty: float, entry_price: float, exit_price: float) -> float:
    s = str(side).upper()
    if s == "LONG":
        return float((exit_price - entry_price) * qty)
    return float((entry_price - exit_price) * qty)


def _get_quanto_multiplier(executor: GateExecutor, *, contract: str) -> float:
    """Return Gate contract quantity multiplier.

    Gate USDT futures uses integer `size` in orders/fills.
    Some contracts represent multiple units per 1 size via `quanto_multiplier`.

    Example (from datagate.md in this repo):
      - XRP_USDT fills size sum=63 but UI shows 630 XRP => quanto_multiplier=10
      - ADA_USDT fills size sum=273 but UI shows 2730 ADA => quanto_multiplier=10

    If metadata or field missing, default to 1.
    """
    try:
        meta = executor.get_contract_detail(contract)
        qm = meta.get("quanto_multiplier")
        if qm is None:
            return 1.0
        qmf = float(qm)
        if qmf <= 0:
            return 1.0
        return qmf
    except Exception:
        return 1.0


def _compute_pnl_from_prices(*, side: str, qty: float, entry_price: float, exit_price: float, fees: float) -> float:
    s = str(side).upper()
    if s == "LONG":
        gross = (exit_price - entry_price) * qty
    else:
        gross = (entry_price - exit_price) * qty
    return float(gross - float(fees))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="quant_system/database/quant_system.sqlite")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    root = ROOT
    cfg = _load_cfg(root)
    executor = _mk_executor(cfg)

    db_path = (root / args.db).resolve()
    if not db_path.exists():
        raise FileNotFoundError(str(db_path))

    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT closure_id, trade_id, timestamp, asset, side, qty, entry_price, exit_order_id, exit_price, fees, pnl
            FROM trade_closures
            WHERE exit_order_id IS NOT NULL AND TRIM(exit_order_id) != ''
            ORDER BY closure_id DESC
            LIMIT ?
            """,
            (int(args.limit),),
        ).fetchall()

        updated = 0
        checked = 0

        for r in rows:
            checked += 1
            cid = int(r["closure_id"])
            trade_id = r["trade_id"]
            trade_id = int(trade_id) if trade_id is not None else None
            ts = pd.Timestamp(r["timestamp"]).tz_convert("UTC")
            asset = str(r["asset"])
            contract = asset  # internal asset naming matches Gate contract in this repo
            oid = str(r["exit_order_id"])

            # Quantity normalization factor (Gate contract multiplier)
            qm = _get_quanto_multiplier(executor, contract=contract)

            side = str(r.get("side") if hasattr(r, "get") else r["side"])  # type: ignore[attr-defined]
            try:
                side = str(r["side"])
            except Exception:
                side = "LONG"

            # Try to locate entry order id from trades table.
            entry_order_id: Optional[str] = None
            if trade_id is not None:
                tr = conn.execute(
                    "SELECT entry_order_id FROM trades WHERE trade_id = ?",
                    (trade_id,),
                ).fetchone()
                if tr is not None:
                    eo = tr["entry_order_id"]
                    if eo is not None and str(eo).strip() != "":
                        entry_order_id = str(eo)

            # 1) Exit fills.
            try:
                exit_vwap, exit_fee, exit_rpnl, exit_fill_count = _fills_summary_for_order(
                    executor,
                    contract=contract,
                    order_id=oid,
                    center_ts=ts,
                    window_sec=6 * 3600,
                )
            except Exception:
                continue

            if exit_vwap is None or exit_fee is None or exit_fill_count <= 0:
                continue

            # 2) Entry fills (optional, but required for accurate PnL if journal entry was wrong).
            entry_vwap: Optional[float] = None
            entry_fee: float = 0.0
            entry_qty: Optional[float] = None
            if entry_order_id:
                try:
                    ev, ef, _epnl, e_fill_count = _fills_summary_for_order(
                        executor,
                        contract=contract,
                        order_id=entry_order_id,
                        center_ts=ts,
                        window_sec=12 * 3600,
                    )
                except Exception:
                    ev, ef, e_fill_count = None, None, 0

                if ev is not None and ef is not None and e_fill_count > 0:
                    entry_vwap = float(ev)
                    entry_fee = float(ef)

                    # qty from fills: we must re-fetch matched fills to sum sizes; easiest is to query my_trades
                    # again and sum sizes for the entry order.
                    try:
                        center_ts2 = pd.Timestamp(ts).tz_convert("UTC")
                        from_ts2 = int((center_ts2 - pd.Timedelta(seconds=12 * 3600)).timestamp())
                        to_ts2 = int((center_ts2 + pd.Timedelta(seconds=12 * 3600)).timestamp())
                        trades2 = executor.get_my_trades(contract=contract, from_ts=from_ts2, to_ts=to_ts2) or []
                        qsum = 0.0
                        for t in trades2:
                            oid2 = str(t.get("order_id", t.get("order", t.get("id", ""))))
                            if oid2 != str(entry_order_id):
                                continue
                            try:
                                qsum += abs(float(t.get("size", t.get("qty", 0.0))))
                            except Exception:
                                continue
                        if qsum > 0:
                            entry_qty = float(qsum)
                    except Exception:
                        pass

            # Build new closure numbers.
            new_exit = float(exit_vwap)
            new_entry = float(entry_vwap) if entry_vwap is not None else float(r["entry_price"])
            base_qty = float(entry_qty) if entry_qty is not None else float(r["qty"])
            new_qty = float(base_qty * float(qm))
            new_fees = float(entry_fee + float(exit_fee))

            new_gross = _compute_gross_pnl_from_prices(
                side=side,
                qty=new_qty,
                entry_price=new_entry,
                exit_price=new_exit,
            )
            new_pnl = float(new_gross - new_fees)

            # If Gate actually provided realized pnl on exit fills, prefer that as net PnL when entry fills absent.
            if entry_vwap is None and exit_rpnl is not None:
                try:
                    new_pnl = float(exit_rpnl)
                    new_gross = float(new_pnl + new_fees)
                except Exception:
                    pass

            if args.dry_run:
                updated += 1
                continue

            conn.execute(
                """
                UPDATE trade_closures
                SET qty = ?, entry_price = ?, exit_price = ?, fees = ?, pnl = ?, gross_pnl = ?
                WHERE closure_id = ?
                """,
                (new_qty, new_entry, new_exit, new_fees, new_pnl, float(new_gross), cid),
            )

            # Also patch the trade entry if we have entry fills.
            if trade_id is not None and entry_vwap is not None:
                conn.execute(
                    """
                    UPDATE trades
                    SET qty = ?, entry_price = ?, entry_fee = ?
                    WHERE trade_id = ?
                    """,
                    # Store human-meaningful qty in the journal (same as Gate UI, post-multiplier)
                    (new_qty, float(entry_vwap), float(entry_fee), int(trade_id)),
                )
            updated += 1

        if not args.dry_run:
            conn.commit()

    print(f"checked={checked} updated={updated} db={db_path}")


if __name__ == "__main__":
    main()
