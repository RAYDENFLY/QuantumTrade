"""
agent/policy.py — Deterministic policy layer.

Ini SELALU menang di atas LLM. Rule-based, no ML.

Responsibilities:
1. Hitung survival mode berdasarkan kondisi real-time.
2. Tentukan apakah sebuah action boleh dijalankan.
3. Tentukan apakah kondisi emergency terpenuhi.
4. Override / filter plan yang datang dari LLM.
"""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple

from agent.schema import (
    AccountSnapshot,
    AgentMode,
    AgentPlan,
    AgentSnapshot,
    ActionType,
    HIGH_RISK_ACTIONS,
    MEDIUM_RISK_ACTIONS,
    ProposedAction,
    SurvivalMode,
)

log = logging.getLogger("agent.policy")


# ---------------------------------------------------------------------------
# Thresholds — bisa di-override lewat config
# ---------------------------------------------------------------------------

class PolicyConfig:
    # Drawdown thresholds (persen, nilai negatif)
    dd_conservative: float = -5.0    # → CONSERVATIVE
    dd_defensive: float    = -12.0   # → DEFENSIVE
    dd_emergency: float    = -20.0   # → hard kill / HIBERNATE

    # Exposure thresholds (x)
    exposure_conservative: float = 4.0
    exposure_defensive: float    = 6.0
    exposure_emergency: float    = 8.0

    # Runner errors
    errors_defensive: int  = 5
    errors_hibernate: int  = 15

    # Treasury
    treasury_conservative_days: float = 7.0   # runway < 7 hari → CONSERVATIVE
    treasury_defensive_days: float    = 3.0   # runway < 3 hari → DEFENSIVE
    treasury_dead: float              = 0.0   # treasury <= 0 → DEAD

    # Order rate per 4H
    max_order_rate_4h: int = 6

    # Min confidence untuk eksekusi non-emergency
    min_confidence: float = 0.55

    # Burn rate (cost per hari) — diisi dari config
    operational_cost_per_day_usd: float = 0.63  # ~$19/bulan default


_default_cfg = PolicyConfig()


# ---------------------------------------------------------------------------
# Survival mode determination (deterministik)
# ---------------------------------------------------------------------------

def determine_survival_mode(
    snapshot: AgentSnapshot,
    cfg: PolicyConfig = _default_cfg,
) -> Tuple[SurvivalMode, List[str]]:
    """
    Returns: (SurvivalMode, [list of reasons])
    Priority: HIBERNATE > DEFENSIVE > CONSERVATIVE > NORMAL
    """
    reasons: List[str] = []
    acct = snapshot.account

    # 1. DEAD check (dihandle di agent.py, tapi log di sini)
    if snapshot.treasury_usdt <= cfg.treasury_dead:
        reasons.append(f"treasury={snapshot.treasury_usdt:.2f} <= 0 (DEAD)")
        return SurvivalMode.HIBERNATE, reasons

    # 2. HIBERNATE conditions
    if acct.drawdown_pct <= cfg.dd_emergency:
        reasons.append(f"drawdown={acct.drawdown_pct:.1f}% <= {cfg.dd_emergency}%")
        return SurvivalMode.HIBERNATE, reasons

    if acct.exposure_x >= cfg.exposure_emergency:
        reasons.append(f"exposure={acct.exposure_x:.1f}x >= {cfg.exposure_emergency}x")
        return SurvivalMode.HIBERNATE, reasons

    if snapshot.runner_error_count >= cfg.errors_hibernate:
        reasons.append(f"runner_errors={snapshot.runner_error_count} >= {cfg.errors_hibernate}")
        return SurvivalMode.HIBERNATE, reasons

    # Runway check
    runway = _compute_runway(snapshot, cfg)
    if 0 < runway <= cfg.treasury_defensive_days:
        reasons.append(f"treasury runway={runway:.1f}d <= {cfg.treasury_defensive_days}d")
        return SurvivalMode.DEFENSIVE, reasons

    # 3. DEFENSIVE conditions
    if acct.drawdown_pct <= cfg.dd_defensive:
        reasons.append(f"drawdown={acct.drawdown_pct:.1f}% <= {cfg.dd_defensive}%")
        return SurvivalMode.DEFENSIVE, reasons

    if acct.exposure_x >= cfg.exposure_defensive:
        reasons.append(f"exposure={acct.exposure_x:.1f}x >= {cfg.exposure_defensive}x")
        return SurvivalMode.DEFENSIVE, reasons

    if snapshot.runner_error_count >= cfg.errors_defensive:
        reasons.append(f"runner_errors={snapshot.runner_error_count} >= {cfg.errors_defensive}")
        return SurvivalMode.DEFENSIVE, reasons

    # 4. CONSERVATIVE conditions
    if acct.drawdown_pct <= cfg.dd_conservative:
        reasons.append(f"drawdown={acct.drawdown_pct:.1f}% <= {cfg.dd_conservative}%")
        return SurvivalMode.CONSERVATIVE, reasons

    if acct.exposure_x >= cfg.exposure_conservative:
        reasons.append(f"exposure={acct.exposure_x:.1f}x >= {cfg.exposure_conservative}x")
        return SurvivalMode.CONSERVATIVE, reasons

    if 0 < runway <= cfg.treasury_conservative_days:
        reasons.append(f"treasury runway={runway:.1f}d <= {cfg.treasury_conservative_days}d")
        return SurvivalMode.CONSERVATIVE, reasons

    return SurvivalMode.NORMAL, []


def _compute_runway(snapshot: AgentSnapshot, cfg: PolicyConfig) -> float:
    """Berapa hari treasury akan bertahan dengan burn rate saat ini."""
    if cfg.operational_cost_per_day_usd <= 0:
        return 9999.0
    return snapshot.treasury_usdt / cfg.operational_cost_per_day_usd


# ---------------------------------------------------------------------------
# Emergency detection
# ---------------------------------------------------------------------------

def is_emergency(snapshot: AgentSnapshot, cfg: PolicyConfig = _default_cfg) -> bool:
    """True jika kondisi emergency hard — izinkan high-risk actions."""
    acct = snapshot.account
    return (
        acct.drawdown_pct <= cfg.dd_emergency
        or acct.exposure_x >= cfg.exposure_emergency
        or snapshot.runner_error_count >= cfg.errors_hibernate
        or snapshot.treasury_usdt <= cfg.treasury_dead
    )


# ---------------------------------------------------------------------------
# Action filter — biar plan LLM tidak melanggar aturan
# ---------------------------------------------------------------------------

def filter_plan(
    plan: AgentPlan,
    snapshot: AgentSnapshot,
    agent_mode: AgentMode,
    cfg: PolicyConfig = _default_cfg,
) -> Tuple[AgentPlan, List[str]]:
    """
    Filter & override plan dari LLM.
    Returns: (filtered_plan, list_of_rejections)
    """
    rejections: List[str] = []
    approved: List[ProposedAction] = []

    emergency = is_emergency(snapshot, cfg)
    mode = determine_survival_mode(snapshot, cfg)[0]

    for action in plan.proposed_actions:
        reason = _check_action(action, plan, snapshot, agent_mode, emergency, mode, cfg)
        if reason:
            rejections.append(f"{action.type}: {reason}")
            log.warning("Policy REJECTED action %s: %s", action.type, reason)
        else:
            approved.append(action)

    # Rebuild plan dengan action yang sudah difilter
    filtered = plan.model_copy(update={"proposed_actions": approved})
    return filtered, rejections


def _check_action(
    action: ProposedAction,
    plan: AgentPlan,
    snapshot: AgentSnapshot,
    agent_mode: AgentMode,
    emergency: bool,
    mode: SurvivalMode,
    cfg: PolicyConfig,
) -> Optional[str]:
    """
    Return None jika action diizinkan, atau string alasan penolakan.
    """
    # Observe mode: tidak ada eksekusi apapun
    if agent_mode == AgentMode.OBSERVE:
        return "agent_mode=observe: no execution allowed"

    # Off mode: tidak ada apapun
    if agent_mode == AgentMode.OFF:
        return "agent_mode=off"

    # High-risk hanya boleh saat emergency
    if action.type in HIGH_RISK_ACTIONS:
        if not emergency:
            return "high-risk action requires emergency condition"
        if not plan.emergency:
            return "high-risk action requires plan.emergency=True"

    # Rate limit check
    if snapshot.account.order_rate_4h >= cfg.max_order_rate_4h:
        if action.type in HIGH_RISK_ACTIONS | MEDIUM_RISK_ACTIONS:
            return f"order_rate_4h={snapshot.account.order_rate_4h} >= {cfg.max_order_rate_4h}"

    # Confidence check untuk non-emergency
    if not emergency and action.type not in {ActionType.PAUSE_ENTRIES, ActionType.SET_SURVIVAL_MODE}:
        if plan.confidence < cfg.min_confidence:
            return f"confidence={plan.confidence:.2f} < min_confidence={cfg.min_confidence}"

    # HIBERNATE: hanya izinkan PAUSE_ENTRIES, NOTIFY, ROTATE_LOGS
    if mode == SurvivalMode.HIBERNATE:
        allowed_in_hibernate = {ActionType.PAUSE_ENTRIES, ActionType.NOTIFY, ActionType.ROTATE_LOGS, ActionType.SET_SURVIVAL_MODE}
        if action.type not in allowed_in_hibernate:
            return f"survival_mode=HIBERNATE only allows safe actions, got {action.type}"

    return None  # diizinkan


# ---------------------------------------------------------------------------
# Auto-plan generator (rule-based, tanpa LLM)
# ---------------------------------------------------------------------------

def generate_rule_based_plan(
    snapshot: AgentSnapshot,
    cfg: PolicyConfig = _default_cfg,
) -> Optional[AgentPlan]:
    """
    Buat plan deterministik berdasarkan kondisi saat ini.
    Dipakai sebagai pelengkap atau pengganti LLM saat kondisi jelas.
    Returns None jika tidak ada action yang diperlukan (NORMAL, semua oke).
    """
    from datetime import datetime, timezone

    mode, reasons = determine_survival_mode(snapshot, cfg)
    emergency = is_emergency(snapshot, cfg)
    actions: List[ProposedAction] = []
    observations = reasons[:]
    risks: List[str] = []

    if mode == SurvivalMode.HIBERNATE or emergency:
        actions.append(ProposedAction(
            type=ActionType.PAUSE_ENTRIES,
            params={"duration_min": 480},
            why=" | ".join(reasons) or "emergency/hibernate condition",
            guardrails=["drawdown_recovery", "error_rate_normal"],
        ))
        risks.append("System in critical state")
        if emergency:
            actions.append(ProposedAction(
                type=ActionType.SET_SURVIVAL_MODE,
                params={"mode": SurvivalMode.HIBERNATE},
                why="Policy override: emergency detected",
                guardrails=[],
            ))

    elif mode == SurvivalMode.DEFENSIVE:
        actions.append(ProposedAction(
            type=ActionType.PAUSE_ENTRIES,
            params={"duration_min": 240},
            why=" | ".join(reasons),
            guardrails=["drawdown < -12%"],
        ))
        risks.append("Drawdown or exposure approaching critical levels")

    elif mode == SurvivalMode.CONSERVATIVE:
        actions.append(ProposedAction(
            type=ActionType.TIGHTEN_RISK,
            params={"risk_per_trade": 0.002, "atr_multiplier": 3.0},
            why=" | ".join(reasons),
            guardrails=["drawdown < -5%"],
        ))
        risks.append("Minor stress — tightening risk params")

    if not actions:
        return None

    return AgentPlan(
        ts=datetime.now(tz=timezone.utc),
        summary=f"Rule-based plan: survival_mode={mode}",
        observations=observations,
        risks=risks,
        proposed_actions=actions,
        needs_human_approval=False,
        confidence=1.0,  # rule-based = deterministic = full confidence
        emergency=emergency,
    )
