"""
agent/actions.py — Implementasi action executor.

Setiap action class implements execute() yang:
- Melakukan aksi nyata (update config, call API, dll)
- Returns dict result {success: bool, detail: str, ...}
- Tidak boleh akses API key secara langsung (lewat executor)
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import yaml

log = logging.getLogger("agent.actions")

CONFIG_PATH = os.environ.get("QUANT_CONFIG_PATH", "quant_system/config.yaml")
RUNNER_STATE_FILE = os.environ.get("RUNNER_STATE_FILE", "agent/.runner_flags.yaml")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_config() -> Dict[str, Any]:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _save_config(cfg: Dict[str, Any]) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, sort_keys=False)


def _load_runner_flags() -> Dict[str, Any]:
    if os.path.exists(RUNNER_STATE_FILE):
        with open(RUNNER_STATE_FILE, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def _save_runner_flags(flags: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(RUNNER_STATE_FILE), exist_ok=True)
    with open(RUNNER_STATE_FILE, "w", encoding="utf-8") as f:
        yaml.dump(flags, f, allow_unicode=True)


# ---------------------------------------------------------------------------
# Action implementations
# ---------------------------------------------------------------------------

def action_pause_entries(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Set flag pause_entries di runner_flags.yaml.
    live_runner.py harus baca file ini setiap loop.
    """
    duration_min = int(params.get("duration_min", 60))
    from datetime import datetime, timedelta, timezone
    resume_at = (datetime.now(tz=timezone.utc) + timedelta(minutes=duration_min)).isoformat()
    flags = _load_runner_flags()
    flags["pause_entries"] = True
    flags["pause_entries_until"] = resume_at
    _save_runner_flags(flags)
    log.warning("PAUSE_ENTRIES: set until %s (%d min)", resume_at, duration_min)
    return {"success": True, "detail": f"Paused entries until {resume_at}", "resume_at": resume_at}


def action_resume_entries(params: Dict[str, Any]) -> Dict[str, Any]:
    flags = _load_runner_flags()
    flags["pause_entries"] = False
    flags.pop("pause_entries_until", None)
    _save_runner_flags(flags)
    log.warning("RESUME_ENTRIES: cleared pause flag")
    return {"success": True, "detail": "Entries resumed"}


def action_tighten_risk(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Update risk params di config.yaml.
    Params: atr_multiplier, risk_per_trade (opsional)
    """
    changes: Dict[str, Any] = {}
    try:
        cfg = _load_config()

        if "atr_multiplier" in params:
            new_atr = float(params["atr_multiplier"])
            old_atr = cfg.get("risk", {}).get("atr_multiplier", "N/A")
            cfg.setdefault("risk", {})["atr_multiplier"] = new_atr
            changes["atr_multiplier"] = {"old": old_atr, "new": new_atr}

        if "risk_per_trade" in params:
            new_rpt = float(params["risk_per_trade"])
            # Hard clamp: jangan sampai terlalu besar
            new_rpt = min(new_rpt, 0.01)
            old_rpt = cfg.get("risk", {}).get("risk_per_trade", "N/A")
            cfg.setdefault("risk", {})["risk_per_trade"] = new_rpt
            changes["risk_per_trade"] = {"old": old_rpt, "new": new_rpt}

        _save_config(cfg)
        log.warning("TIGHTEN_RISK: applied changes=%s", changes)
        return {"success": True, "detail": "Config updated", "changes": changes}
    except Exception as e:
        log.exception("TIGHTEN_RISK failed")
        return {"success": False, "detail": str(e), "changes": changes}


def action_set_survival_mode(params: Dict[str, Any]) -> Dict[str, Any]:
    """Write survival mode ke runner flags (agent state)."""
    mode = str(params.get("mode", "NORMAL")).upper()
    flags = _load_runner_flags()
    old_mode = flags.get("survival_mode", "NORMAL")
    flags["survival_mode"] = mode
    _save_runner_flags(flags)
    log.warning("SET_SURVIVAL_MODE: %s → %s", old_mode, mode)
    return {"success": True, "detail": f"Survival mode changed {old_mode}→{mode}"}


def action_notify(params: Dict[str, Any]) -> Dict[str, Any]:
    """Log notifikasi. TODO: extend ke Telegram/Discord."""
    message = str(params.get("message", ""))
    log.warning("AGENT NOTIFY: %s", message)
    # Tulis ke runner flags untuk dashboard bisa baca
    flags = _load_runner_flags()
    from datetime import datetime, timezone
    flags.setdefault("notifications", []).append({
        "ts": datetime.now(tz=timezone.utc).isoformat(),
        "message": message,
    })
    # Jaga maksimal 50 notifikasi
    flags["notifications"] = flags["notifications"][-50:]
    _save_runner_flags(flags)
    return {"success": True, "detail": f"Notified: {message}"}


def action_update_config(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generic config update. Params: {section.key: value}
    Contoh: {"execution.max_open_pairs": 3}
    Hanya allow key yang sudah di whitelist.
    """
    ALLOWED_KEYS = {
        "execution.max_open_pairs",
        "execution.leverage_max",
        "execution.leverage_min",
        "execution.close_on_signal_change",
        "risk.risk_per_trade",
        "risk.atr_multiplier",
        "risk.max_portfolio_risk",
    }
    changes = {}
    errors = []
    try:
        cfg = _load_config()
        for dotkey, value in params.items():
            if dotkey not in ALLOWED_KEYS:
                errors.append(f"{dotkey} not in whitelist")
                continue
            parts = dotkey.split(".", 1)
            section, key = parts[0], parts[1]
            old = cfg.get(section, {}).get(key, "N/A")
            cfg.setdefault(section, {})[key] = value
            changes[dotkey] = {"old": old, "new": value}
        _save_config(cfg)
        log.warning("UPDATE_CONFIG: changes=%s errors=%s", changes, errors)
        return {"success": len(errors) == 0, "changes": changes, "errors": errors}
    except Exception as e:
        log.exception("UPDATE_CONFIG failed")
        return {"success": False, "detail": str(e)}


def action_rotate_logs(params: Dict[str, Any]) -> Dict[str, Any]:
    """Trigger log rotation (logging.handlers.RotatingFileHandler akan handle ini)."""
    import logging.handlers
    for handler in logging.root.handlers:
        if isinstance(handler, logging.handlers.RotatingFileHandler):
            handler.doRollover()
    log.info("ROTATE_LOGS: done")
    return {"success": True, "detail": "Log rotated"}


def action_export_report(params: Dict[str, Any]) -> Dict[str, Any]:
    """Placeholder — bisa diperluas untuk export CSV/HTML report."""
    log.info("EXPORT_REPORT: not yet implemented")
    return {"success": True, "detail": "Export report requested (noop for now)"}


def action_cancel_stale_tpsl(
    params: Dict[str, Any],
    executor: Any = None,
) -> Dict[str, Any]:
    """
    Cancel trigger orders yang stale untuk sebuah contract.
    Memerlukan executor.cancel_trigger_order(order_id).
    """
    contract = str(params.get("contract", ""))
    if not contract or executor is None:
        return {"success": False, "detail": "Missing contract or executor"}
    try:
        open_orders = executor.get_open_trigger_orders(contract=contract)
        cancelled = []
        for o in open_orders:
            oid = o.get("id")
            if oid:
                executor.cancel_trigger_order(str(oid))
                cancelled.append(str(oid))
        log.warning("CANCEL_STALE_TPSL: contract=%s cancelled=%s", contract, cancelled)
        return {"success": True, "cancelled": cancelled}
    except Exception as e:
        log.exception("CANCEL_STALE_TPSL failed")
        return {"success": False, "detail": str(e)}


def action_replace_tpsl(
    params: Dict[str, Any],
    executor: Any = None,
) -> Dict[str, Any]:
    """
    Replace TP/SL orders untuk sebuah contract.
    Params: contract, tp, sl, position_side, size, trigger_rule
    """
    if executor is None:
        return {"success": False, "detail": "No executor provided"}
    try:
        contract      = str(params["contract"])
        tp            = float(params["tp"]) if params.get("tp") else None
        sl            = float(params["sl"]) if params.get("sl") else None
        position_side = str(params.get("position_side", "LONG")).upper()
        size          = float(params["size"])
        trigger_rule  = int(params.get("trigger_rule", 1))

        res = executor.place_tpsl_orders(
            contract=contract,
            position_side=position_side,
            size=size,
            take_profit=tp,
            stop_loss=sl,
            trigger_rule=trigger_rule,
        )
        log.warning("REPLACE_TPSL: contract=%s tp=%s sl=%s result=%s", contract, tp, sl, res)
        return {"success": True, "result": str(res)}
    except Exception as e:
        log.exception("REPLACE_TPSL failed")
        return {"success": False, "detail": str(e)}


def action_reduce_position(
    params: Dict[str, Any],
    executor: Any = None,
) -> Dict[str, Any]:
    """
    Reduce position by pct (0..1). Max 25% per call.
    """
    if executor is None:
        return {"success": False, "detail": "No executor provided"}
    try:
        contract = str(params["contract"])
        pct      = min(float(params.get("pct", 0.25)), 0.25)  # hard cap 25%
        positions = executor.get_positions()
        pos = next((p for p in positions if str(p.get("contract")) == contract), None)
        if not pos:
            return {"success": False, "detail": f"No open position for {contract}"}
        size = float(pos.get("size", 0) or 0)
        if size == 0:
            return {"success": False, "detail": "Position size is 0"}
        reduce_size = max(1, int(abs(size) * pct))
        close_side  = "sell" if size > 0 else "buy"
        result = executor.place_market_order(
            contract=contract,
            size=reduce_size,
            side=close_side,
            reduce_only=True,
        )
        log.warning("REDUCE_POSITION: contract=%s pct=%.0f%% reduce_size=%d", contract, pct * 100, reduce_size)
        return {"success": True, "reduced_size": reduce_size, "result": str(result)}
    except Exception as e:
        log.exception("REDUCE_POSITION failed")
        return {"success": False, "detail": str(e)}


def action_close_position(
    params: Dict[str, Any],
    executor: Any = None,
) -> Dict[str, Any]:
    """HIGH-RISK: Close seluruh posisi untuk contract. Emergency only."""
    if executor is None:
        return {"success": False, "detail": "No executor provided"}
    try:
        contract = str(params["contract"])
        reason   = str(params.get("reason", "AGENT_EMERGENCY"))
        positions = executor.get_positions()
        pos = next((p for p in positions if str(p.get("contract")) == contract), None)
        if not pos:
            return {"success": False, "detail": f"No open position for {contract}"}
        size       = float(pos.get("size", 0) or 0)
        close_side = "sell" if size > 0 else "buy"
        result = executor.place_market_order(
            contract=contract,
            size=int(abs(size)),
            side=close_side,
            reduce_only=True,
        )
        log.warning("CLOSE_POSITION: contract=%s reason=%s size=%s", contract, reason, size)
        return {"success": True, "closed_size": size, "reason": reason, "result": str(result)}
    except Exception as e:
        log.exception("CLOSE_POSITION failed")
        return {"success": False, "detail": str(e)}


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

ACTION_MAP = {
    "PAUSE_ENTRIES":     action_pause_entries,
    "RESUME_ENTRIES":    action_resume_entries,
    "TIGHTEN_RISK":      action_tighten_risk,
    "SET_SURVIVAL_MODE": action_set_survival_mode,
    "NOTIFY":            action_notify,
    "UPDATE_CONFIG":     action_update_config,
    "ROTATE_LOGS":       action_rotate_logs,
    "EXPORT_REPORT":     action_export_report,
}

# Actions yang butuh executor
EXECUTOR_ACTIONS = {
    "CANCEL_STALE_TPSL": action_cancel_stale_tpsl,
    "REPLACE_TPSL":      action_replace_tpsl,
    "REDUCE_POSITION":   action_reduce_position,
    "CLOSE_POSITION":    action_close_position,
}


def execute_action(
    action_type: str,
    params: Dict[str, Any],
    executor: Any = None,
) -> Dict[str, Any]:
    """Dispatch dan eksekusi action. Returns result dict."""
    fn = ACTION_MAP.get(action_type) or EXECUTOR_ACTIONS.get(action_type)
    if fn is None:
        return {"success": False, "detail": f"Unknown action_type: {action_type}"}

    if action_type in EXECUTOR_ACTIONS:
        return fn(params, executor=executor)
    return fn(params)
