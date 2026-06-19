"""
agent/schema.py — Pydantic models untuk Plan JSON agent.

Schema ini dipakai oleh:
- llm_client.py  → parse & validate output LLM
- agent.py       → type-safe plan handling
- storage        → serialisasi ke DB
"""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SurvivalMode(str, Enum):
    NORMAL       = "NORMAL"
    CONSERVATIVE = "CONSERVATIVE"
    DEFENSIVE    = "DEFENSIVE"
    HIBERNATE    = "HIBERNATE"


class AgentMode(str, Enum):
    OFF     = "off"
    OBSERVE = "observe"
    EXECUTE = "execute"


class ActionType(str, Enum):
    # Low-risk
    PAUSE_ENTRIES       = "PAUSE_ENTRIES"
    RESUME_ENTRIES      = "RESUME_ENTRIES"
    TIGHTEN_RISK        = "TIGHTEN_RISK"
    ROTATE_LOGS         = "ROTATE_LOGS"
    EXPORT_REPORT       = "EXPORT_REPORT"
    NOTIFY              = "NOTIFY"
    # Medium-risk
    CANCEL_STALE_TPSL   = "CANCEL_STALE_TPSL"
    REPLACE_TPSL        = "REPLACE_TPSL"
    REDUCE_POSITION     = "REDUCE_POSITION"
    # High-risk (emergency only)
    CLOSE_POSITION      = "CLOSE_POSITION"
    REVERSE_POSITION    = "REVERSE_POSITION"
    # Agent self-management
    SET_SURVIVAL_MODE   = "SET_SURVIVAL_MODE"
    UPDATE_CONFIG       = "UPDATE_CONFIG"


HIGH_RISK_ACTIONS = {ActionType.CLOSE_POSITION, ActionType.REVERSE_POSITION}
MEDIUM_RISK_ACTIONS = {ActionType.CANCEL_STALE_TPSL, ActionType.REPLACE_TPSL, ActionType.REDUCE_POSITION}
LOW_RISK_ACTIONS = {
    ActionType.PAUSE_ENTRIES, ActionType.RESUME_ENTRIES, ActionType.TIGHTEN_RISK,
    ActionType.ROTATE_LOGS, ActionType.EXPORT_REPORT, ActionType.NOTIFY,
    ActionType.SET_SURVIVAL_MODE, ActionType.UPDATE_CONFIG,
}


# ---------------------------------------------------------------------------
# Action model
# ---------------------------------------------------------------------------

class ProposedAction(BaseModel):
    type: ActionType
    params: Dict[str, Any] = Field(default_factory=dict)
    why: str = ""
    guardrails: List[str] = Field(default_factory=list)

    @field_validator("type", mode="before")
    @classmethod
    def coerce_type(cls, v: Any) -> ActionType:
        # Already an ActionType → return directly (avoids str() mangling to "ActionType.FOO")
        if isinstance(v, ActionType):
            return v
        # Str → strip "ActionType." prefix if present, then convert
        raw = str(v).upper().removeprefix("ACTIONTYPE.")
        return ActionType(raw)


# ---------------------------------------------------------------------------
# Plan model — output LLM / rule engine
# ---------------------------------------------------------------------------

class AgentPlan(BaseModel):
    ts: datetime
    summary: str
    observations: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    proposed_actions: List[ProposedAction] = Field(default_factory=list)
    needs_human_approval: bool = False

    # Mode C tambahan — wajib ada
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    emergency: bool = False

    @model_validator(mode="after")
    def check_high_risk_needs_emergency(self) -> "AgentPlan":
        for act in self.proposed_actions:
            if act.type in HIGH_RISK_ACTIONS and not self.emergency:
                raise ValueError(
                    f"Action {act.type} is high-risk and requires emergency=True in plan"
                )
        return self

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)

    @classmethod
    def from_json(cls, raw: str) -> "AgentPlan":
        return cls.model_validate(json.loads(raw))


# ---------------------------------------------------------------------------
# Snapshot model — input ke LLM
# ---------------------------------------------------------------------------

class PositionSnapshot(BaseModel):
    contract: str
    side: str          # LONG | SHORT
    size: float
    entry_price: float
    unrealized_pnl: float
    leverage: float
    tp_price: Optional[float] = None
    sl_price: Optional[float] = None


class AccountSnapshot(BaseModel):
    equity: float
    available: float
    unrealized_pnl: float
    drawdown_pct: float          # current DD dari peak, sebagai persen (mis. -5.2)
    exposure_x: float            # total notional / equity
    open_positions: int
    order_rate_4h: int           # berapa order dikirim dalam 4H terakhir


class AgentSnapshot(BaseModel):
    ts: datetime
    account: AccountSnapshot
    positions: List[PositionSnapshot] = Field(default_factory=list)
    # runner health
    last_candle_ts: Dict[str, str] = Field(default_factory=dict)   # asset → ISO ts
    runner_error_count: int = 0
    # survival
    treasury_usdt: float = 0.0
    survival_mode: SurvivalMode = SurvivalMode.NORMAL
    agent_mode: AgentMode = AgentMode.OBSERVE
    # cost
    llm_cost_today_usd: float = 0.0
    # recent perf (simple)
    realized_pnl_7d: float = 0.0
    realized_pnl_30d: float = 0.0
    win_rate_30d: float = 0.0

    def to_prompt_text(self) -> str:
        """Format ringkas untuk disisipkan ke prompt LLM — tanpa secret."""
        lines = [
            f"[Snapshot {self.ts.isoformat()}]",
            f"Equity: ${self.account.equity:.2f}  Available: ${self.account.available:.2f}",
            f"Drawdown: {self.account.drawdown_pct:.1f}%  Exposure: {self.account.exposure_x:.2f}x",
            f"Open positions: {self.account.open_positions}  Order rate (4H): {self.account.order_rate_4h}",
            f"Treasury: ${self.treasury_usdt:.2f}  LLM cost today: ${self.llm_cost_today_usd:.4f}",
            f"Survival mode: {self.survival_mode}  Agent mode: {self.agent_mode}",
            f"PnL 7d: ${self.realized_pnl_7d:.2f}  PnL 30d: ${self.realized_pnl_30d:.2f}  WinRate 30d: {self.win_rate_30d:.1%}",
            "",
        ]
        if self.positions:
            lines.append("Positions:")
            for p in self.positions:
                tp_str = f" TP={p.tp_price}" if p.tp_price else ""
                sl_str = f" SL={p.sl_price}" if p.sl_price else ""
                lines.append(
                    f"  {p.contract} {p.side} size={p.size} entry={p.entry_price:.4f}"
                    f" uPnL={p.unrealized_pnl:.2f}{tp_str}{sl_str}"
                )
        if self.runner_error_count > 0:
            lines.append(f"Runner errors (recent): {self.runner_error_count}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Token usage / cost tracking
# ---------------------------------------------------------------------------

class TokenUsage(BaseModel):
    provider: str                       # "ollama" | "deepseek" | "grok"
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_hit_input_tokens: int = 0
    cache_miss_input_tokens: int = 0
    cost_usd: float = 0.0

    @classmethod
    def deepseek_cost(
        cls,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_hit_input: int = 0,
    ) -> "TokenUsage":
        cache_miss = max(0, input_tokens - cache_hit_input)
        cost = (cache_hit_input / 1e6) * 0.028 + (cache_miss / 1e6) * 0.28 + (output_tokens / 1e6) * 0.42
        return cls(
            provider="deepseek",
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_hit_input_tokens=cache_hit_input,
            cache_miss_input_tokens=cache_miss,
            cost_usd=cost,
        )
