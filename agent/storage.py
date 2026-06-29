"""
agent/storage.py — AgentStorage abstraction: PostgresAgentStorage + SQLiteAgentStorage fallback.
"""
from __future__ import annotations
import json, logging, os, sqlite3
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
log = logging.getLogger("agent.storage")

# ===================== ABC =====================
class AgentStorage(ABC):
    @abstractmethod
    def init_schema(self) -> None: ...
    @abstractmethod
    def save_plan(self, ts: datetime, input_snapshot: Dict[str, Any], plan: Dict[str, Any]) -> int: ...
    @abstractmethod
    def save_action(self, plan_id: int, ts: datetime, action_type: str, action_params: Dict[str, Any], result: Dict[str, Any], success: bool) -> None: ...
    @abstractmethod
    def save_treasury(self, ts: datetime, treasury_usdt: float, cost_per_day_usd: float, llm_cost_usd: float, survival_mode: str) -> None: ...
    @abstractmethod
    def load_treasury(self) -> Optional[float]: ...
    @abstractmethod
    def get_recent_plans(self, limit: int = 10) -> List[Dict[str, Any]]: ...
    @abstractmethod
    def get_recent_actions(self, limit: int = 20) -> List[Dict[str, Any]]: ...
    # Shadow
    @abstractmethod
    def save_shadow_observation(self, plan_id, ts, recommended_action, recommended_params, contract, survival_mode, system_action, position_size_before, position_size_after, tpsl_changed, entries_paused, agreement, status, equity_at_obs, drawdown_at_obs) -> int: ...
    @abstractmethod
    def update_shadow_observation(self, obs_id, resolved_at=None, equity_24h_after=None, asset_return_24h=None, equity_change_24h=None, counterfactual_pnl=None) -> None: ...
    @abstractmethod
    def get_shadow_observations(self, limit=20, status=None, agreement=None) -> List[Dict[str, Any]]: ...
    @abstractmethod
    def get_pending_shadow_observations(self) -> List[Dict[str, Any]]: ...
    # Analyst
    @abstractmethod
    def save_analyst_reports(self, plan_id, ts, reports_json, consensus, confidence, breakdown_json) -> None: ...
    @abstractmethod
    def get_recent_analyst_reports(self, limit=10) -> List[Dict[str, Any]]: ...
    # Bull/Bear
    @abstractmethod
    def save_bullbear_debate(self, plan_id, ts, bull_json, bear_json, verdict_json, bull_confidence, bear_confidence, net_bias, final_verdict, final_conviction, override_flag) -> int: ...
    @abstractmethod
    def get_recent_bullbear_debates(self, limit=10) -> List[Dict[str, Any]]: ...
    # Experiment
    @abstractmethod
    def save_experiment_run(self, started_at: datetime, initial_capital: float) -> int: ...
    @abstractmethod
    def update_experiment_run(self, experiment_id, current_capital, peak_capital, max_drawdown, days_alive, survival_score, plans_generated, debates_generated, analyst_reports_generated, shadow_observations, agreement_rate, total_return_pct, highest_runway_days, lowest_runway_days, best_survival_score, worst_survival_score, runway_days, notes="") -> None: ...
    @abstractmethod
    def get_active_experiment(self) -> Optional[Dict[str, Any]]: ...
    @abstractmethod
    def get_experiment_history(self, limit=10) -> List[Dict[str, Any]]: ...
    # Episodic
    @abstractmethod
    def save_episode(self, ts, plan_id, action_type, survival_mode, treasury_usdt, survival_score, analyst_consensus, debate_verdict, snapshot_json, outcome_json, importance_score) -> int: ...
    @abstractmethod
    def update_episode_outcome(self, episode_id, outcome_json, resolved=True) -> None: ...
    @abstractmethod
    def get_recent_episodes(self, limit=20) -> List[Dict[str, Any]]: ...
    @abstractmethod
    def get_episode(self, episode_id: int) -> Optional[Dict[str, Any]]: ...
    # Resolution
    @abstractmethod
    def get_unresolved_episodes(self, limit=100) -> List[Dict[str, Any]]: ...
    @abstractmethod
    def resolve_episode(self, episode_id, outcome_json) -> None: ...
    # Patterns (Phase 7C)
    @abstractmethod
    def save_pattern(self, pattern_key: str, action_type: str, condition_json: str, sample_size: int, positive_count: int, negative_count: int, neutral_count: int, success_rate: float, confidence_score: float, last_episode_id_processed: int = 0) -> int: ...
    @abstractmethod
    def get_patterns(self, limit: int = 50) -> List[Dict[str, Any]]: ...
    @abstractmethod
    def get_pattern_by_key(self, pattern_key: str) -> Optional[Dict[str, Any]]: ...
    # Pattern validation (Phase 7C.2)
    @abstractmethod
    def validate_pattern(self, pattern_key: str, validated: bool, validation_score: float) -> None: ...
    @abstractmethod
    def get_validated_patterns(self, limit: int = 50) -> List[Dict[str, Any]]: ...
    # Memory advice / sandbox (Phase 7D.0)
    @abstractmethod
    def save_memory_advice(self, ts: datetime, plan_id: int, planner_decision: str, memory_decision: str, difference_detected: bool, confidence: float, reason_json: str) -> int: ...
    @abstractmethod
    def get_recent_memory_advice(self, limit: int = 20) -> List[Dict[str, Any]]: ...
    @abstractmethod
    def get_memory_advice_stats(self) -> Dict[str, Any]: ...
    # Memory injections / procedural context (Phase 7D.1)
    @abstractmethod
    def save_memory_injection(self, ts: datetime, plan_id: int, rule_count: int, rules_json: str) -> int: ...
    @abstractmethod
    def get_recent_memory_injections(self, limit: int = 20) -> List[Dict[str, Any]]: ...
    @abstractmethod
    def get_memory_injection_stats(self) -> Dict[str, Any]: ...
    # Memory attribution (Phase 7D.2)
    @abstractmethod
    def save_attribution(self, ts: datetime, plan_id: int, episode_id: int, memory_rules_count: int, memory_confidence: float, planner_decision: str, analyst_consensus: str, debate_verdict: str, survival_mode: str, outcome_quality: str, survival_score_delta: float, equity_delta_pct: float, memory_contribution_score: float) -> int: ...
    @abstractmethod
    def update_attribution(self, episode_id: int, outcome_quality: str, survival_score_delta: float, equity_delta_pct: float, memory_contribution_score: float) -> None: ...
    @abstractmethod
    def get_recent_attributions(self, limit: int = 20) -> List[Dict[str, Any]]: ...
    @abstractmethod
    def get_attribution_metrics(self) -> Dict[str, Any]: ...
    # Shadow Memory Influence (Phase 8.1)
    @abstractmethod
    def save_shadow_memory_influence(self, ts: datetime, plan_id: int, planner_action: str, planner_confidence: float, memory_action: str, memory_confidence: float, agreement: str, influence_weight: float, shadow_influence_score: float, pattern_ids_json: str, validation_scores_json: str, survival_mode: str, analyst_consensus: str, debate_verdict: str) -> int: ...
    @abstractmethod
    def get_recent_shadow_memory_influence(self, limit: int = 20) -> List[Dict[str, Any]]: ...
    @abstractmethod
    def get_shadow_memory_influence_metrics(self) -> Dict[str, Any]: ...

    # Phase 9.2 — Reasoning audit
    @abstractmethod
    def save_reasoning_audit(self, plan_id: int, llm_provider: str, memory_usage_score: float, ml_used: bool, procedural_used: bool, episodic_used: bool, shadow_used: bool, portfolio_used: bool, risk_used: bool, treasury_used: bool, reasoning_json: str, context_size_chars: int = 0, latency_ms: float = 0.0, raw_content_length: int = 0) -> None: ...

    @abstractmethod
    def get_reasoning_audits(self, limit: int = 20) -> List[Dict[str, Any]]: ...
    @abstractmethod
    def get_reasoning_audit_summary(self) -> Dict[str, Any]: ...

    # Phase 9.3 — Reasoning feedback
    @abstractmethod
    def save_reasoning_feedback(self, plan_id: int, reflection: str, missing_dimensions: str, recommended_improvements: str, severity: str = "info") -> None: ...

    # Phase 10.5 — Trade Replay
    @abstractmethod
    def save_trade_replay_event(
        self,
        trade_id: str,
        event_type: str,
        event_data: str,
        event_index: int,
        timestamp: str = "",
        status: str = "",
        duration_ms: float = 0.0,
        provider: str = "",
        confidence: float = 0.0,
        latency_ms: float = 0.0,
        plan_id: int = 0,
    ) -> None: ...

    @abstractmethod
    def save_trade_replay_summary(
        self,
        trade_id: str,
        contract: str,
        side: str,
        plan_id: int,
        llm_provider: str,
        status: str,
        total_duration_ms: float,
        event_count: int,
        created_at: str,
    ) -> None: ...

    @abstractmethod
    def get_trade_replay_events(self, trade_id: str) -> List[Dict[str, Any]]: ...

    @abstractmethod
    def get_trade_replay_summary(self, limit: int = 50) -> List[Dict[str, Any]]: ...

# ===================== PG Schema =====================
PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_plans (id SERIAL PRIMARY KEY, ts TIMESTAMPTZ NOT NULL, input_snapshot JSONB, plan_json JSONB, approved_by TEXT DEFAULT 'auto', executed_at TIMESTAMPTZ, status TEXT DEFAULT 'pending');
CREATE INDEX IF NOT EXISTS idx_agent_plans_ts ON agent_plans(ts DESC);
CREATE TABLE IF NOT EXISTS agent_actions (id SERIAL PRIMARY KEY, plan_id INTEGER REFERENCES agent_plans(id), ts TIMESTAMPTZ NOT NULL, action_type TEXT NOT NULL, action_params JSONB, result_json JSONB, success BOOLEAN NOT NULL DEFAULT FALSE);
CREATE INDEX IF NOT EXISTS idx_agent_actions_ts ON agent_actions(ts DESC);
CREATE INDEX IF NOT EXISTS idx_agent_actions_type_ts ON agent_actions(action_type, ts DESC);
CREATE TABLE IF NOT EXISTS agent_treasury (id SERIAL PRIMARY KEY, ts TIMESTAMPTZ NOT NULL, treasury_usdt DOUBLE PRECISION NOT NULL, cost_per_day_usd DOUBLE PRECISION NOT NULL, llm_cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0, survival_mode TEXT NOT NULL DEFAULT 'NORMAL');
CREATE INDEX IF NOT EXISTS idx_agent_treasury_ts ON agent_treasury(ts DESC);
CREATE TABLE IF NOT EXISTS analyst_reports (id SERIAL PRIMARY KEY, plan_id INTEGER REFERENCES agent_plans(id), ts TIMESTAMPTZ NOT NULL, reports_json JSONB NOT NULL, consensus TEXT NOT NULL, confidence DOUBLE PRECISION NOT NULL DEFAULT 0.0, breakdown_json JSONB NOT NULL DEFAULT '{}');
CREATE INDEX IF NOT EXISTS idx_analyst_reports_ts ON analyst_reports(ts DESC);
CREATE INDEX IF NOT EXISTS idx_analyst_reports_plan ON analyst_reports(plan_id);
CREATE TABLE IF NOT EXISTS bullbear_debates (id SERIAL PRIMARY KEY, plan_id INTEGER REFERENCES agent_plans(id), ts TIMESTAMPTZ NOT NULL, bull_json JSONB NOT NULL, bear_json JSONB NOT NULL, verdict_json JSONB NOT NULL, bull_confidence DOUBLE PRECISION NOT NULL DEFAULT 0.0, bear_confidence DOUBLE PRECISION NOT NULL DEFAULT 0.0, net_bias TEXT NOT NULL DEFAULT 'neutral', final_verdict TEXT NOT NULL DEFAULT 'neutral', final_conviction DOUBLE PRECISION NOT NULL DEFAULT 0.0, override_flag BOOLEAN NOT NULL DEFAULT FALSE);
CREATE INDEX IF NOT EXISTS idx_bullbear_ts ON bullbear_debates(ts DESC);
CREATE INDEX IF NOT EXISTS idx_bullbear_plan ON bullbear_debates(plan_id);
CREATE TABLE IF NOT EXISTS experiment_runs (id SERIAL PRIMARY KEY, started_at TIMESTAMPTZ NOT NULL, ended_at TIMESTAMPTZ, status TEXT NOT NULL DEFAULT 'RUNNING', initial_capital DOUBLE PRECISION NOT NULL, current_capital DOUBLE PRECISION NOT NULL DEFAULT 0.0, peak_capital DOUBLE PRECISION NOT NULL DEFAULT 0.0, max_drawdown DOUBLE PRECISION NOT NULL DEFAULT 0.0, days_alive DOUBLE PRECISION NOT NULL DEFAULT 0.0, survival_score DOUBLE PRECISION NOT NULL DEFAULT 0.0, total_return_pct DOUBLE PRECISION NOT NULL DEFAULT 0.0, highest_runway_days DOUBLE PRECISION NOT NULL DEFAULT 0.0, lowest_runway_days DOUBLE PRECISION NOT NULL DEFAULT 0.0, best_survival_score DOUBLE PRECISION NOT NULL DEFAULT 0.0, worst_survival_score DOUBLE PRECISION NOT NULL DEFAULT 0.0, runway_days DOUBLE PRECISION NOT NULL DEFAULT 0.0, plans_generated INTEGER NOT NULL DEFAULT 0, debates_generated INTEGER NOT NULL DEFAULT 0, analyst_reports_generated INTEGER NOT NULL DEFAULT 0, shadow_observations INTEGER NOT NULL DEFAULT 0, agreement_rate DOUBLE PRECISION NOT NULL DEFAULT 0.0, notes TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS idx_experiment_status ON experiment_runs(status);
CREATE TABLE IF NOT EXISTS shadow_observations (id SERIAL PRIMARY KEY, plan_id INTEGER REFERENCES agent_plans(id), ts TIMESTAMPTZ NOT NULL, recommended_action TEXT NOT NULL, recommended_params TEXT NOT NULL DEFAULT '{}', contract TEXT, survival_mode TEXT NOT NULL, system_action TEXT, position_size_before DOUBLE PRECISION, position_size_after DOUBLE PRECISION, tpsl_changed INTEGER DEFAULT 0, entries_paused INTEGER DEFAULT 0, agreement TEXT NOT NULL DEFAULT 'UNKNOWN', status TEXT NOT NULL DEFAULT 'PENDING_24H', resolved_at TIMESTAMPTZ, equity_at_obs DOUBLE PRECISION, drawdown_at_obs DOUBLE PRECISION, equity_24h_after DOUBLE PRECISION, asset_return_24h DOUBLE PRECISION, equity_change_24h DOUBLE PRECISION, counterfactual_pnl DOUBLE PRECISION);
CREATE INDEX IF NOT EXISTS idx_shadow_obs_ts ON shadow_observations(ts DESC);
CREATE INDEX IF NOT EXISTS idx_shadow_obs_plan ON shadow_observations(plan_id);
CREATE INDEX IF NOT EXISTS idx_shadow_obs_agreement ON shadow_observations(agreement);
CREATE INDEX IF NOT EXISTS idx_shadow_obs_status ON shadow_observations(status);
CREATE TABLE IF NOT EXISTS agent_episodes (id SERIAL PRIMARY KEY, ts TIMESTAMPTZ NOT NULL, plan_id INTEGER REFERENCES agent_plans(id), action_type TEXT NOT NULL, survival_mode TEXT NOT NULL, treasury_usdt DOUBLE PRECISION NOT NULL DEFAULT 0.0, survival_score DOUBLE PRECISION NOT NULL DEFAULT 0.0, analyst_consensus TEXT NOT NULL DEFAULT 'unknown', debate_verdict TEXT NOT NULL DEFAULT 'unknown', snapshot_json JSONB NOT NULL DEFAULT '{}', outcome_json JSONB NOT NULL DEFAULT '{}', importance_score DOUBLE PRECISION NOT NULL DEFAULT 0.5, resolved BOOLEAN NOT NULL DEFAULT FALSE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
CREATE INDEX IF NOT EXISTS idx_agent_episodes_ts ON agent_episodes(ts DESC);
CREATE INDEX IF NOT EXISTS idx_agent_episodes_action ON agent_episodes(action_type);
CREATE INDEX IF NOT EXISTS idx_agent_episodes_mode ON agent_episodes(survival_mode);
CREATE INDEX IF NOT EXISTS idx_agent_episodes_resolved ON agent_episodes(resolved);
CREATE TABLE IF NOT EXISTS semantic_patterns (id SERIAL PRIMARY KEY, pattern_key TEXT NOT NULL UNIQUE, action_type TEXT NOT NULL, condition_json JSONB NOT NULL DEFAULT '{}', sample_size INTEGER NOT NULL DEFAULT 0, positive_count INTEGER NOT NULL DEFAULT 0, negative_count INTEGER NOT NULL DEFAULT 0, neutral_count INTEGER NOT NULL DEFAULT 0, success_rate DOUBLE PRECISION NOT NULL DEFAULT 0.0, confidence_score DOUBLE PRECISION NOT NULL DEFAULT 0.0, first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(), last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(), active BOOLEAN NOT NULL DEFAULT TRUE, last_episode_id_processed INTEGER NOT NULL DEFAULT 0, validated BOOLEAN NOT NULL DEFAULT FALSE, validation_score DOUBLE PRECISION NOT NULL DEFAULT 0.0, last_validated_at TIMESTAMPTZ);
CREATE INDEX IF NOT EXISTS idx_semantic_patterns_key ON semantic_patterns(pattern_key);
CREATE INDEX IF NOT EXISTS idx_semantic_patterns_active ON semantic_patterns(active);
CREATE TABLE IF NOT EXISTS memory_advice (id SERIAL PRIMARY KEY, ts TIMESTAMPTZ NOT NULL, plan_id INTEGER REFERENCES agent_plans(id), planner_decision TEXT NOT NULL, memory_decision TEXT NOT NULL, difference_detected BOOLEAN NOT NULL DEFAULT FALSE, confidence DOUBLE PRECISION NOT NULL DEFAULT 0.0, reason_json JSONB NOT NULL DEFAULT '{}');
CREATE INDEX IF NOT EXISTS idx_memory_advice_ts ON memory_advice(ts DESC);
CREATE INDEX IF NOT EXISTS idx_memory_advice_diff ON memory_advice(difference_detected);
CREATE TABLE IF NOT EXISTS memory_injections (id SERIAL PRIMARY KEY, ts TIMESTAMPTZ NOT NULL, plan_id INTEGER REFERENCES agent_plans(id), rule_count INTEGER NOT NULL DEFAULT 0, rules_json JSONB NOT NULL DEFAULT '[]', planner_used_memory BOOLEAN NOT NULL DEFAULT FALSE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
CREATE INDEX IF NOT EXISTS idx_memory_injections_ts ON memory_injections(ts DESC);
CREATE TABLE IF NOT EXISTS memory_attributions (id SERIAL PRIMARY KEY, ts TIMESTAMPTZ NOT NULL, plan_id INTEGER REFERENCES agent_plans(id), episode_id INTEGER REFERENCES agent_episodes(id), memory_rules_count INTEGER NOT NULL DEFAULT 0, memory_confidence DOUBLE PRECISION NOT NULL DEFAULT 0.0, planner_decision TEXT NOT NULL, analyst_consensus TEXT NOT NULL DEFAULT 'unknown', debate_verdict TEXT NOT NULL DEFAULT 'unknown', survival_mode TEXT NOT NULL DEFAULT 'NORMAL', outcome_quality TEXT NOT NULL DEFAULT 'unknown', survival_score_delta DOUBLE PRECISION NOT NULL DEFAULT 0.0, equity_delta_pct DOUBLE PRECISION NOT NULL DEFAULT 0.0, memory_contribution_score DOUBLE PRECISION NOT NULL DEFAULT 0.0, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
CREATE INDEX IF NOT EXISTS idx_memory_attributions_ts ON memory_attributions(ts DESC);
CREATE INDEX IF NOT EXISTS idx_memory_attributions_pending ON memory_attributions(episode_id) WHERE outcome_quality='pending';
CREATE TABLE IF NOT EXISTS agent_orders (id SERIAL PRIMARY KEY, order_id TEXT NOT NULL UNIQUE, exchange_order_id TEXT, contract TEXT NOT NULL, side TEXT NOT NULL, size DOUBLE PRECISION NOT NULL DEFAULT 0, order_type TEXT NOT NULL DEFAULT 'MARKET', price DOUBLE PRECISION, stop_price DOUBLE PRECISION, tp_price DOUBLE PRECISION, sl_price DOUBLE PRECISION, reduce_only BOOLEAN NOT NULL DEFAULT FALSE, status TEXT NOT NULL DEFAULT 'PENDING', filled_size DOUBLE PRECISION NOT NULL DEFAULT 0, avg_fill_price DOUBLE PRECISION, fees DOUBLE PRECISION NOT NULL DEFAULT 0, slippage DOUBLE PRECISION NOT NULL DEFAULT 0, latency_ms DOUBLE PRECISION NOT NULL DEFAULT 0, error TEXT, execution_mode TEXT NOT NULL DEFAULT 'TESTNET', plan_id INTEGER REFERENCES agent_plans(id), created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), opened_at TIMESTAMPTZ, closed_at TIMESTAMPTZ, realized_pnl DOUBLE PRECISION);
CREATE INDEX IF NOT EXISTS idx_agent_orders_order_id ON agent_orders(order_id);
CREATE INDEX IF NOT EXISTS idx_agent_orders_contract ON agent_orders(contract);
CREATE INDEX IF NOT EXISTS idx_agent_orders_status ON agent_orders(status);
CREATE INDEX IF NOT EXISTS idx_agent_orders_created ON agent_orders(created_at DESC);
CREATE TABLE IF NOT EXISTS agent_reasoning_audit (id SERIAL PRIMARY KEY, plan_id INTEGER REFERENCES agent_plans(id), llm_provider TEXT NOT NULL DEFAULT 'unknown', memory_usage_score DOUBLE PRECISION NOT NULL DEFAULT 0, ml_used BOOLEAN NOT NULL DEFAULT FALSE, procedural_used BOOLEAN NOT NULL DEFAULT FALSE, episodic_used BOOLEAN NOT NULL DEFAULT FALSE, shadow_used BOOLEAN NOT NULL DEFAULT FALSE, portfolio_used BOOLEAN NOT NULL DEFAULT FALSE, risk_used BOOLEAN NOT NULL DEFAULT FALSE, treasury_used BOOLEAN NOT NULL DEFAULT FALSE, reasoning_json JSONB NOT NULL DEFAULT '{}', context_size_chars INTEGER NOT NULL DEFAULT 0, latency_ms DOUBLE PRECISION NOT NULL DEFAULT 0, raw_content_length INTEGER NOT NULL DEFAULT 0, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
CREATE INDEX IF NOT EXISTS idx_reasoning_audit_plan ON agent_reasoning_audit(plan_id);
CREATE INDEX IF NOT EXISTS idx_reasoning_audit_created ON agent_reasoning_audit(created_at DESC);
CREATE TABLE IF NOT EXISTS agent_reasoning_feedback (id SERIAL PRIMARY KEY, plan_id INTEGER REFERENCES agent_plans(id), reflection TEXT NOT NULL DEFAULT '', missing_dimensions JSONB NOT NULL DEFAULT '[]', recommended_improvements JSONB NOT NULL DEFAULT '[]', severity TEXT NOT NULL DEFAULT 'info', created_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
CREATE INDEX IF NOT EXISTS idx_reasoning_feedback_plan ON agent_reasoning_feedback(plan_id);
CREATE INDEX IF NOT EXISTS idx_reasoning_feedback_created ON agent_reasoning_feedback(created_at DESC);

-- Phase 10.5 — Trade Replay events
CREATE TABLE IF NOT EXISTS agent_trade_replay_events (
    id SERIAL PRIMARY KEY,
    trade_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_data JSONB NOT NULL DEFAULT '{}',
    event_index INTEGER NOT NULL DEFAULT 0,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status TEXT NOT NULL DEFAULT '',
    duration_ms DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    provider TEXT NOT NULL DEFAULT '',
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    latency_ms DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    plan_id INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_replay_events_trade ON agent_trade_replay_events(trade_id);
CREATE INDEX IF NOT EXISTS idx_replay_events_type ON agent_trade_replay_events(event_type);
CREATE INDEX IF NOT EXISTS idx_replay_events_idx ON agent_trade_replay_events(trade_id, event_index);

-- Phase 10.5 — Trade Replay summary
CREATE TABLE IF NOT EXISTS agent_trade_replay_summary (
    id SERIAL PRIMARY KEY,
    trade_id TEXT NOT NULL UNIQUE,
    contract TEXT NOT NULL DEFAULT '',
    side TEXT NOT NULL DEFAULT '',
    plan_id INTEGER NOT NULL DEFAULT 0,
    llm_provider TEXT NOT NULL DEFAULT 'unknown',
    status TEXT NOT NULL DEFAULT 'OPEN',
    total_duration_ms DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    event_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_replay_summary_trade ON agent_trade_replay_summary(trade_id);
CREATE INDEX IF NOT EXISTS idx_replay_summary_status ON agent_trade_replay_summary(status);
CREATE INDEX IF NOT EXISTS idx_replay_summary_created ON agent_trade_replay_summary(created_at DESC);
"""

# ===================== SQLite Schema =====================
SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_plans (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, input_snapshot TEXT, plan_json TEXT, approved_by TEXT DEFAULT 'auto', executed_at TEXT, status TEXT DEFAULT 'pending');
CREATE TABLE IF NOT EXISTS agent_actions (id INTEGER PRIMARY KEY AUTOINCREMENT, plan_id INTEGER REFERENCES agent_plans(id), ts TEXT NOT NULL, action_type TEXT NOT NULL, action_params TEXT, result_json TEXT, success INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS agent_treasury (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, treasury_usdt REAL NOT NULL, cost_per_day_usd REAL NOT NULL, llm_cost_usd REAL NOT NULL DEFAULT 0, survival_mode TEXT NOT NULL DEFAULT 'NORMAL');
CREATE TABLE IF NOT EXISTS shadow_observations (id INTEGER PRIMARY KEY AUTOINCREMENT, plan_id INTEGER REFERENCES agent_plans(id), ts TEXT NOT NULL, recommended_action TEXT NOT NULL, recommended_params TEXT NOT NULL DEFAULT '{}', contract TEXT, survival_mode TEXT NOT NULL, system_action TEXT, position_size_before REAL, position_size_after REAL, tpsl_changed INTEGER DEFAULT 0, entries_paused INTEGER DEFAULT 0, agreement TEXT NOT NULL DEFAULT 'UNKNOWN', status TEXT NOT NULL DEFAULT 'PENDING_24H', resolved_at TEXT, equity_at_obs REAL, drawdown_at_obs REAL, equity_24h_after REAL, asset_return_24h REAL, equity_change_24h REAL, counterfactual_pnl REAL);
CREATE INDEX IF NOT EXISTS idx_shadow_obs_ts ON shadow_observations(ts DESC);
CREATE INDEX IF NOT EXISTS idx_shadow_obs_plan ON shadow_observations(plan_id);
CREATE INDEX IF NOT EXISTS idx_shadow_obs_agreement ON shadow_observations(agreement);
CREATE INDEX IF NOT EXISTS idx_shadow_obs_status ON shadow_observations(status);
CREATE TABLE IF NOT EXISTS analyst_reports (id INTEGER PRIMARY KEY AUTOINCREMENT, plan_id INTEGER REFERENCES agent_plans(id), ts TEXT NOT NULL, reports_json TEXT NOT NULL, consensus TEXT NOT NULL, confidence REAL NOT NULL DEFAULT 0.0, breakdown_json TEXT NOT NULL DEFAULT '{}');
CREATE INDEX IF NOT EXISTS idx_analyst_reports_ts ON analyst_reports(ts DESC);
CREATE INDEX IF NOT EXISTS idx_analyst_reports_plan ON analyst_reports(plan_id);
CREATE TABLE IF NOT EXISTS bullbear_debates (id INTEGER PRIMARY KEY AUTOINCREMENT, plan_id INTEGER REFERENCES agent_plans(id), ts TEXT NOT NULL, bull_json TEXT NOT NULL, bear_json TEXT NOT NULL, verdict_json TEXT NOT NULL, bull_confidence REAL NOT NULL DEFAULT 0.0, bear_confidence REAL NOT NULL DEFAULT 0.0, net_bias TEXT NOT NULL DEFAULT 'neutral', final_verdict TEXT NOT NULL DEFAULT 'neutral', final_conviction REAL NOT NULL DEFAULT 0.0, override_flag INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_bullbear_ts ON bullbear_debates(ts DESC);
CREATE INDEX IF NOT EXISTS idx_bullbear_plan ON bullbear_debates(plan_id);
CREATE TABLE IF NOT EXISTS experiment_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL, ended_at TEXT, status TEXT NOT NULL DEFAULT 'RUNNING', initial_capital REAL NOT NULL, current_capital REAL NOT NULL DEFAULT 0.0, peak_capital REAL NOT NULL DEFAULT 0.0, max_drawdown REAL NOT NULL DEFAULT 0.0, days_alive REAL NOT NULL DEFAULT 0.0, survival_score REAL NOT NULL DEFAULT 0.0, total_return_pct REAL NOT NULL DEFAULT 0.0, highest_runway_days REAL NOT NULL DEFAULT 0.0, lowest_runway_days REAL NOT NULL DEFAULT 0.0, best_survival_score REAL NOT NULL DEFAULT 0.0, worst_survival_score REAL NOT NULL DEFAULT 0.0, runway_days REAL NOT NULL DEFAULT 0.0, plans_generated INTEGER NOT NULL DEFAULT 0, debates_generated INTEGER NOT NULL DEFAULT 0, analyst_reports_generated INTEGER NOT NULL DEFAULT 0, shadow_observations INTEGER NOT NULL DEFAULT 0, agreement_rate REAL NOT NULL DEFAULT 0.0, notes TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS idx_experiment_status ON experiment_runs(status);
CREATE TABLE IF NOT EXISTS agent_episodes (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, plan_id INTEGER REFERENCES agent_plans(id), action_type TEXT NOT NULL, survival_mode TEXT NOT NULL, treasury_usdt REAL NOT NULL DEFAULT 0.0, survival_score REAL NOT NULL DEFAULT 0.0, analyst_consensus TEXT NOT NULL DEFAULT 'unknown', debate_verdict TEXT NOT NULL DEFAULT 'unknown', snapshot_json TEXT NOT NULL DEFAULT '{}', outcome_json TEXT NOT NULL DEFAULT '{}', importance_score REAL NOT NULL DEFAULT 0.5, resolved INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_agent_episodes_ts ON agent_episodes(ts DESC);
CREATE INDEX IF NOT EXISTS idx_agent_episodes_action ON agent_episodes(action_type);
CREATE INDEX IF NOT EXISTS idx_agent_episodes_mode ON agent_episodes(survival_mode);
CREATE INDEX IF NOT EXISTS idx_agent_episodes_resolved ON agent_episodes(resolved);
CREATE TABLE IF NOT EXISTS semantic_patterns (id INTEGER PRIMARY KEY AUTOINCREMENT, pattern_key TEXT NOT NULL UNIQUE, action_type TEXT NOT NULL, condition_json TEXT NOT NULL DEFAULT '{}', sample_size INTEGER NOT NULL DEFAULT 0, positive_count INTEGER NOT NULL DEFAULT 0, negative_count INTEGER NOT NULL DEFAULT 0, neutral_count INTEGER NOT NULL DEFAULT 0, success_rate REAL NOT NULL DEFAULT 0.0, confidence_score REAL NOT NULL DEFAULT 0.0, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, last_episode_id_processed INTEGER NOT NULL DEFAULT 0, validated INTEGER NOT NULL DEFAULT 0, validation_score REAL NOT NULL DEFAULT 0.0, last_validated_at TEXT);
CREATE INDEX IF NOT EXISTS idx_semantic_patterns_key ON semantic_patterns(pattern_key);
CREATE INDEX IF NOT EXISTS idx_semantic_patterns_active ON semantic_patterns(active);
CREATE TABLE IF NOT EXISTS memory_advice (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, plan_id INTEGER REFERENCES agent_plans(id), planner_decision TEXT NOT NULL, memory_decision TEXT NOT NULL, difference_detected INTEGER NOT NULL DEFAULT 0, confidence REAL NOT NULL DEFAULT 0.0, reason_json TEXT NOT NULL DEFAULT '{}');
CREATE INDEX IF NOT EXISTS idx_memory_advice_ts ON memory_advice(ts DESC);
CREATE INDEX IF NOT EXISTS idx_memory_advice_diff ON memory_advice(difference_detected);
CREATE TABLE IF NOT EXISTS memory_injections (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, plan_id INTEGER REFERENCES agent_plans(id), rule_count INTEGER NOT NULL DEFAULT 0, rules_json TEXT NOT NULL DEFAULT '[]', planner_used_memory INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_memory_injections_ts ON memory_injections(ts DESC);
CREATE TABLE IF NOT EXISTS memory_attributions (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, plan_id INTEGER REFERENCES agent_plans(id), episode_id INTEGER REFERENCES agent_episodes(id), memory_rules_count INTEGER NOT NULL DEFAULT 0, memory_confidence REAL NOT NULL DEFAULT 0.0, planner_decision TEXT NOT NULL, analyst_consensus TEXT NOT NULL DEFAULT 'unknown', debate_verdict TEXT NOT NULL DEFAULT 'unknown', survival_mode TEXT NOT NULL DEFAULT 'NORMAL', outcome_quality TEXT NOT NULL DEFAULT 'unknown', survival_score_delta REAL NOT NULL DEFAULT 0.0, equity_delta_pct REAL NOT NULL DEFAULT 0.0, memory_contribution_score REAL NOT NULL DEFAULT 0.0, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_memory_attributions_ts ON memory_attributions(ts DESC);
CREATE TABLE IF NOT EXISTS shadow_memory_influence (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, plan_id INTEGER REFERENCES agent_plans(id), planner_action TEXT NOT NULL, planner_confidence REAL NOT NULL DEFAULT 0.0, memory_action TEXT NOT NULL, memory_confidence REAL NOT NULL DEFAULT 0.0, agreement TEXT NOT NULL DEFAULT 'UNKNOWN', influence_weight REAL NOT NULL DEFAULT 0.0, shadow_influence_score REAL NOT NULL DEFAULT 0.0, pattern_ids_json TEXT NOT NULL DEFAULT '[]', validation_scores_json TEXT NOT NULL DEFAULT '[]', survival_mode TEXT NOT NULL DEFAULT 'NORMAL', analyst_consensus TEXT NOT NULL DEFAULT 'unknown', debate_verdict TEXT NOT NULL DEFAULT 'unknown', created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_shadow_memory_influence_ts ON shadow_memory_influence(ts DESC);
CREATE INDEX IF NOT EXISTS idx_shadow_memory_influence_agreement ON shadow_memory_influence(agreement);
CREATE INDEX IF NOT EXISTS idx_shadow_memory_influence_plan ON shadow_memory_influence(plan_id);
CREATE TABLE IF NOT EXISTS agent_reasoning_audit (id INTEGER PRIMARY KEY AUTOINCREMENT, plan_id INTEGER REFERENCES agent_plans(id), llm_provider TEXT NOT NULL DEFAULT 'unknown', memory_usage_score REAL NOT NULL DEFAULT 0, ml_used INTEGER NOT NULL DEFAULT 0, procedural_used INTEGER NOT NULL DEFAULT 0, episodic_used INTEGER NOT NULL DEFAULT 0, shadow_used INTEGER NOT NULL DEFAULT 0, portfolio_used INTEGER NOT NULL DEFAULT 0, risk_used INTEGER NOT NULL DEFAULT 0, treasury_used INTEGER NOT NULL DEFAULT 0, reasoning_json TEXT NOT NULL DEFAULT '{}', context_size_chars INTEGER NOT NULL DEFAULT 0, latency_ms REAL NOT NULL DEFAULT 0, raw_content_length INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_reasoning_audit_plan ON agent_reasoning_audit(plan_id);
CREATE INDEX IF NOT EXISTS idx_reasoning_audit_created ON agent_reasoning_audit(created_at DESC);
CREATE TABLE IF NOT EXISTS agent_reasoning_feedback (id INTEGER PRIMARY KEY AUTOINCREMENT, plan_id INTEGER REFERENCES agent_plans(id), reflection TEXT NOT NULL DEFAULT '', missing_dimensions TEXT NOT NULL DEFAULT '[]', recommended_improvements TEXT NOT NULL DEFAULT '[]', severity TEXT NOT NULL DEFAULT 'info', created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_reasoning_feedback_plan ON agent_reasoning_feedback(plan_id);
CREATE INDEX IF NOT EXISTS idx_reasoning_feedback_created ON agent_reasoning_feedback(created_at DESC);

-- Phase 10.5 — Trade Replay events
CREATE TABLE IF NOT EXISTS agent_trade_replay_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_data TEXT NOT NULL DEFAULT '{}',
    event_index INTEGER NOT NULL DEFAULT 0,
    timestamp TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT '',
    duration_ms REAL NOT NULL DEFAULT 0.0,
    provider TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 0.0,
    latency_ms REAL NOT NULL DEFAULT 0.0,
    plan_id INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_replay_events_trade ON agent_trade_replay_events(trade_id);
CREATE INDEX IF NOT EXISTS idx_replay_events_type ON agent_trade_replay_events(event_type);
CREATE INDEX IF NOT EXISTS idx_replay_events_idx ON agent_trade_replay_events(trade_id, event_index);

-- Phase 10.5 — Trade Replay summary
CREATE TABLE IF NOT EXISTS agent_trade_replay_summary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id TEXT NOT NULL UNIQUE,
    contract TEXT NOT NULL DEFAULT '',
    side TEXT NOT NULL DEFAULT '',
    plan_id INTEGER NOT NULL DEFAULT 0,
    llm_provider TEXT NOT NULL DEFAULT 'unknown',
    status TEXT NOT NULL DEFAULT 'OPEN',
    total_duration_ms REAL NOT NULL DEFAULT 0.0,
    event_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_replay_summary_trade ON agent_trade_replay_summary(trade_id);
CREATE INDEX IF NOT EXISTS idx_replay_summary_status ON agent_trade_replay_summary(status);
CREATE INDEX IF NOT EXISTS idx_replay_summary_created ON agent_trade_replay_summary(created_at DESC);
"""

# ===================== PostgreSQL =====================
class PostgresAgentStorage(AgentStorage):
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn; self._conn = None
    def _get_conn(self):
        import psycopg2, psycopg2.extras
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(self._dsn); self._conn.autocommit = True
        return self._conn
    def init_schema(self) -> None:
        import psycopg2.extras
        with self._get_conn().cursor() as cur: cur.execute(PG_SCHEMA)
        log.info("PostgresAgentStorage: schema initialized")
    def save_plan(self, ts, input_snapshot, plan) -> int:
        with self._get_conn().cursor() as cur:
            cur.execute("INSERT INTO agent_plans (ts, input_snapshot, plan_json, status) VALUES (%s,%s,%s,%s) RETURNING id",
                        (ts, json.dumps(input_snapshot), json.dumps(plan), "executed"))
            return int(cur.fetchone()[0])
    def save_action(self, plan_id, ts, action_type, action_params, result, success) -> None:
        with self._get_conn().cursor() as cur:
            cur.execute("INSERT INTO agent_actions (plan_id, ts, action_type, action_params, result_json, success) VALUES (%s,%s,%s,%s,%s,%s)",
                        (plan_id, ts, action_type, json.dumps(action_params), json.dumps(result), success))
    def save_treasury(self, ts, treasury_usdt, cost_per_day_usd, llm_cost_usd, survival_mode) -> None:
        with self._get_conn().cursor() as cur:
            cur.execute("INSERT INTO agent_treasury (ts, treasury_usdt, cost_per_day_usd, llm_cost_usd, survival_mode) VALUES (%s,%s,%s,%s,%s)",
                        (ts, treasury_usdt, cost_per_day_usd, llm_cost_usd, survival_mode))
    def load_treasury(self) -> Optional[float]:
        try:
            with self._get_conn().cursor() as cur:
                cur.execute("SELECT treasury_usdt FROM agent_treasury ORDER BY ts DESC LIMIT 1")
                row = cur.fetchone()
            return float(row[0]) if row else None
        except Exception:
            log.exception("load_treasury failed"); return None
    def get_recent_plans(self, limit=10) -> List[Dict[str, Any]]:
        try:
            with self._get_conn().cursor() as cur:
                cur.execute("SELECT id, ts, plan_json, input_snapshot, status FROM agent_plans ORDER BY ts DESC LIMIT %s", (limit,))
                rows = cur.fetchall()
            return [{"id": r[0], "ts": str(r[1]), "plan": r[2], "input_snapshot": r[3], "status": r[4]} for r in rows]
        except Exception:
            log.exception("get_recent_plans failed"); return []
    def get_recent_actions(self, limit=20) -> List[Dict[str, Any]]:
        try:
            with self._get_conn().cursor() as cur:
                cur.execute("SELECT id, plan_id, ts, action_type, result_json, success FROM agent_actions ORDER BY ts DESC LIMIT %s", (limit,))
                rows = cur.fetchall()
            return [{"id": r[0], "plan_id": r[1], "ts": str(r[2]), "action_type": r[3], "result": r[4], "success": r[5]} for r in rows]
        except Exception:
            log.exception("get_recent_actions failed"); return []
    def save_shadow_observation(self, plan_id, ts, recommended_action, recommended_params, contract, survival_mode, system_action, position_size_before, position_size_after, tpsl_changed, entries_paused, agreement, status, equity_at_obs, drawdown_at_obs) -> int:
        with self._get_conn().cursor() as cur:
            cur.execute("INSERT INTO shadow_observations (plan_id, ts, recommended_action, recommended_params, contract, survival_mode, system_action, position_size_before, position_size_after, tpsl_changed, entries_paused, agreement, status, equity_at_obs, drawdown_at_obs) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                        (plan_id, ts, recommended_action, recommended_params, contract, survival_mode, system_action, position_size_before, position_size_after, tpsl_changed, entries_paused, agreement, status, equity_at_obs, drawdown_at_obs))
            return int(cur.fetchone()[0])
    def update_shadow_observation(self, obs_id, resolved_at=None, equity_24h_after=None, asset_return_24h=None, equity_change_24h=None, counterfactual_pnl=None) -> None:
        with self._get_conn().cursor() as cur:
            cur.execute("UPDATE shadow_observations SET status='RESOLVED', resolved_at=COALESCE(%s,resolved_at), equity_24h_after=COALESCE(%s,equity_24h_after), asset_return_24h=COALESCE(%s,asset_return_24h), equity_change_24h=COALESCE(%s,equity_change_24h), counterfactual_pnl=COALESCE(%s,counterfactual_pnl) WHERE id=%s",
                        (resolved_at, equity_24h_after, asset_return_24h, equity_change_24h, counterfactual_pnl, obs_id))
    def get_shadow_observations(self, limit=20, status=None, agreement=None) -> List[Dict[str, Any]]:
        try:
            parts = ["1=1"]; params = []
            if status: parts.append("status=%s"); params.append(status)
            if agreement: parts.append("agreement=%s"); params.append(agreement)
            where = " AND ".join(parts)
            with self._get_conn().cursor() as cur:
                cur.execute(f"SELECT * FROM shadow_observations WHERE {where} ORDER BY ts DESC LIMIT %s", tuple(params) + (limit,))
                rows = cur.fetchall(); cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, r)) for r in rows]
        except Exception:
            log.exception("get_shadow_observations failed"); return []
    def get_pending_shadow_observations(self) -> List[Dict[str, Any]]:
        try:
            with self._get_conn().cursor() as cur:
                cur.execute("SELECT * FROM shadow_observations WHERE status='PENDING_24H' ORDER BY ts ASC")
                rows = cur.fetchall(); cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, r)) for r in rows]
        except Exception:
            log.exception("get_pending_shadow_observations failed"); return []
    def save_analyst_reports(self, plan_id, ts, reports_json, consensus, confidence, breakdown_json) -> None:
        with self._get_conn().cursor() as cur:
            cur.execute("INSERT INTO analyst_reports (plan_id, ts, reports_json, consensus, confidence, breakdown_json) VALUES (%s,%s,%s,%s,%s,%s)",
                        (plan_id, ts, reports_json, consensus, confidence, breakdown_json))
    def get_recent_analyst_reports(self, limit=10) -> List[Dict[str, Any]]:
        try:
            with self._get_conn().cursor() as cur:
                cur.execute("SELECT * FROM analyst_reports ORDER BY ts DESC LIMIT %s", (limit,))
                rows = cur.fetchall(); cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, r)) for r in rows]
        except Exception:
            log.exception("get_recent_analyst_reports failed"); return []
    def save_bullbear_debate(self, plan_id, ts, bull_json, bear_json, verdict_json, bull_confidence, bear_confidence, net_bias, final_verdict, final_conviction, override_flag) -> int:
        with self._get_conn().cursor() as cur:
            cur.execute("INSERT INTO bullbear_debates (plan_id, ts, bull_json, bear_json, verdict_json, bull_confidence, bear_confidence, net_bias, final_verdict, final_conviction, override_flag) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                        (plan_id, ts, bull_json, bear_json, verdict_json, bull_confidence, bear_confidence, net_bias, final_verdict, final_conviction, override_flag))
            return int(cur.fetchone()[0])
    def get_recent_bullbear_debates(self, limit=10) -> List[Dict[str, Any]]:
        try:
            with self._get_conn().cursor() as cur:
                cur.execute("SELECT * FROM bullbear_debates ORDER BY ts DESC LIMIT %s", (limit,))
                rows = cur.fetchall(); cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, r)) for r in rows]
        except Exception:
            log.exception("get_recent_bullbear_debates failed"); return []
    def save_experiment_run(self, started_at, initial_capital) -> int:
        with self._get_conn().cursor() as cur:
            cur.execute("INSERT INTO experiment_runs (started_at, initial_capital, current_capital, peak_capital) VALUES (%s,%s,%s,%s) RETURNING id",
                        (started_at, initial_capital, initial_capital, initial_capital))
            return int(cur.fetchone()[0])
    def update_experiment_run(self, experiment_id, current_capital, peak_capital, max_drawdown, days_alive, survival_score, plans_generated, debates_generated, analyst_reports_generated, shadow_observations, agreement_rate, total_return_pct, highest_runway_days, lowest_runway_days, best_survival_score, worst_survival_score, runway_days, notes="") -> None:
        with self._get_conn().cursor() as cur:
            cur.execute("""UPDATE experiment_runs SET current_capital=%s, peak_capital=%s, max_drawdown=%s, days_alive=%s, survival_score=%s, plans_generated=%s, debates_generated=%s, analyst_reports_generated=%s, shadow_observations=%s, agreement_rate=%s, total_return_pct=%s, highest_runway_days=%s, lowest_runway_days=%s, best_survival_score=%s, worst_survival_score=%s, runway_days=%s, notes=%s WHERE id=%s""",
                        (current_capital, peak_capital, max_drawdown, days_alive, survival_score, plans_generated, debates_generated, analyst_reports_generated, shadow_observations, agreement_rate, total_return_pct, highest_runway_days, lowest_runway_days, best_survival_score, worst_survival_score, runway_days, notes, experiment_id))
    def get_active_experiment(self) -> Optional[Dict[str, Any]]:
        try:
            with self._get_conn().cursor() as cur:
                cur.execute("SELECT * FROM experiment_runs WHERE status='RUNNING' ORDER BY started_at DESC LIMIT 1")
                row = cur.fetchone()
                if not row: return None
                cols = [desc[0] for desc in cur.description]
            return dict(zip(cols, row))
        except Exception: return None
    def get_experiment_history(self, limit=10) -> List[Dict[str, Any]]:
        try:
            with self._get_conn().cursor() as cur:
                cur.execute("SELECT * FROM experiment_runs ORDER BY started_at DESC LIMIT %s", (limit,))
                rows = cur.fetchall(); cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, r)) for r in rows]
        except Exception: return []
    def save_episode(self, ts, plan_id, action_type, survival_mode, treasury_usdt, survival_score, analyst_consensus, debate_verdict, snapshot_json, outcome_json, importance_score) -> int:
        with self._get_conn().cursor() as cur:
            cur.execute("INSERT INTO agent_episodes (ts, plan_id, action_type, survival_mode, treasury_usdt, survival_score, analyst_consensus, debate_verdict, snapshot_json, outcome_json, importance_score, resolved, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                        (ts, plan_id, action_type, survival_mode, treasury_usdt, survival_score, analyst_consensus, debate_verdict, snapshot_json, outcome_json, importance_score, False, ts))
            return int(cur.fetchone()[0])
    def update_episode_outcome(self, episode_id, outcome_json, resolved=True) -> None:
        with self._get_conn().cursor() as cur:
            cur.execute("UPDATE agent_episodes SET outcome_json=%s, resolved=%s WHERE id=%s", (outcome_json, resolved, episode_id))
    def get_recent_episodes(self, limit=20) -> List[Dict[str, Any]]:
        try:
            with self._get_conn().cursor() as cur:
                cur.execute("SELECT * FROM agent_episodes ORDER BY ts DESC LIMIT %s", (limit,))
                rows = cur.fetchall(); cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, r)) for r in rows]
        except Exception:
            log.exception("get_recent_episodes failed"); return []
    def get_episode(self, episode_id: int) -> Optional[Dict[str, Any]]:
        try:
            with self._get_conn().cursor() as cur:
                cur.execute("SELECT * FROM agent_episodes WHERE id=%s", (episode_id,))
                row = cur.fetchone()
                if not row: return None
                cols = [desc[0] for desc in cur.description]
            return dict(zip(cols, row))
        except Exception:
            log.exception("get_episode failed"); return None
    def get_unresolved_episodes(self, limit=100) -> List[Dict[str, Any]]:
        try:
            with self._get_conn().cursor() as cur:
                cur.execute("SELECT * FROM agent_episodes WHERE resolved=%s ORDER BY ts ASC LIMIT %s", (False, limit))
                rows = cur.fetchall(); cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, r)) for r in rows]
        except Exception:
            log.exception("get_unresolved_episodes failed"); return []
    def resolve_episode(self, episode_id, outcome_json) -> None:
        with self._get_conn().cursor() as cur:
            cur.execute("UPDATE agent_episodes SET outcome_json=%s, resolved=%s WHERE id=%s", (outcome_json, True, episode_id))
    def save_pattern(self, pattern_key, action_type, condition_json, sample_size, positive_count, negative_count, neutral_count, success_rate, confidence_score, last_episode_id_processed=0) -> int:
        with self._get_conn().cursor() as cur:
            cur.execute("""INSERT INTO semantic_patterns (pattern_key, action_type, condition_json, sample_size, positive_count, negative_count, neutral_count, success_rate, confidence_score, last_seen, last_episode_id_processed) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),%s) ON CONFLICT (pattern_key) DO UPDATE SET sample_size=EXCLUDED.sample_size, positive_count=EXCLUDED.positive_count, negative_count=EXCLUDED.negative_count, neutral_count=EXCLUDED.neutral_count, success_rate=EXCLUDED.success_rate, confidence_score=EXCLUDED.confidence_score, last_seen=NOW(), active=TRUE, last_episode_id_processed=EXCLUDED.last_episode_id_processed RETURNING id""",
                        (pattern_key, action_type, condition_json, sample_size, positive_count, negative_count, neutral_count, success_rate, confidence_score, last_episode_id_processed))
            return int(cur.fetchone()[0])
    def get_patterns(self, limit=50) -> List[Dict[str, Any]]:
        try:
            with self._get_conn().cursor() as cur:
                cur.execute("SELECT * FROM semantic_patterns WHERE active=TRUE ORDER BY confidence_score DESC LIMIT %s", (limit,))
                rows = cur.fetchall(); cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, r)) for r in rows]
        except Exception:
            log.exception("get_patterns failed"); return []
    def get_pattern_by_key(self, pattern_key: str) -> Optional[Dict[str, Any]]:
        try:
            with self._get_conn().cursor() as cur:
                cur.execute("SELECT * FROM semantic_patterns WHERE pattern_key=%s", (pattern_key,))
                row = cur.fetchone()
                if not row: return None
                cols = [desc[0] for desc in cur.description]
            return dict(zip(cols, row))
        except Exception: return None
    def validate_pattern(self, pattern_key: str, validated: bool, validation_score: float) -> None:
        with self._get_conn().cursor() as cur:
            cur.execute("UPDATE semantic_patterns SET validated=%s, validation_score=%s, last_validated_at=NOW(), active=%s WHERE pattern_key=%s",
                        (validated, validation_score, validated, pattern_key))
    def get_validated_patterns(self, limit=50) -> List[Dict[str, Any]]:
        try:
            with self._get_conn().cursor() as cur:
                cur.execute("SELECT * FROM semantic_patterns WHERE validated=TRUE ORDER BY validation_score DESC LIMIT %s", (limit,))
                rows = cur.fetchall(); cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, r)) for r in rows]
        except Exception:
            log.exception("get_validated_patterns failed"); return []
    def save_memory_advice(self, ts, plan_id, planner_decision, memory_decision, difference_detected, confidence, reason_json) -> int:
        with self._get_conn().cursor() as cur:
            cur.execute("INSERT INTO memory_advice (ts, plan_id, planner_decision, memory_decision, difference_detected, confidence, reason_json) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                        (ts, plan_id, planner_decision, memory_decision, difference_detected, confidence, reason_json))
            return int(cur.fetchone()[0])
    def get_recent_memory_advice(self, limit=20) -> List[Dict[str, Any]]:
        try:
            with self._get_conn().cursor() as cur:
                cur.execute("SELECT * FROM memory_advice ORDER BY ts DESC LIMIT %s", (limit,))
                rows = cur.fetchall(); cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, r)) for r in rows]
        except Exception:
            log.exception("get_recent_memory_advice failed"); return []
    def get_memory_advice_stats(self) -> Dict[str, Any]:
        try:
            with self._get_conn().cursor() as cur:
                cur.execute("SELECT COUNT(*) as total, SUM(CASE WHEN difference_detected=TRUE THEN 1 ELSE 0 END) as diffs, AVG(confidence) as avg_conf FROM memory_advice")
                row = cur.fetchone()
                total = int(row[0]) if row else 0
                diffs = int(row[1]) if row else 0
                avg_conf = float(row[2]) if row and row[2] is not None else 0.0
            return {"advice_count": total, "agreement_count": total - diffs, "disagreement_count": diffs, "agreement_rate": round((total - diffs) / max(1, total), 4), "disagreement_rate": round(diffs / max(1, total), 4), "avg_confidence": round(avg_conf, 4)}
        except Exception:
            return {"advice_count": 0, "agreement_count": 0, "disagreement_count": 0, "agreement_rate": 0.0, "disagreement_rate": 0.0, "avg_confidence": 0.0}
    def save_memory_injection(self, ts, plan_id, rule_count, rules_json) -> int:
        with self._get_conn().cursor() as cur:
            cur.execute("INSERT INTO memory_injections (ts, plan_id, rule_count, rules_json, planner_used_memory, created_at) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
                        (ts, plan_id, rule_count, rules_json, False, ts))
            return int(cur.fetchone()[0])
    def get_recent_memory_injections(self, limit=20) -> List[Dict[str, Any]]:
        try:
            with self._get_conn().cursor() as cur:
                cur.execute("SELECT * FROM memory_injections ORDER BY ts DESC LIMIT %s", (limit,))
                rows = cur.fetchall(); cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, r)) for r in rows]
        except Exception:
            log.exception("get_recent_memory_injections failed"); return []
    def get_memory_injection_stats(self) -> Dict[str, Any]:
        try:
            with self._get_conn().cursor() as cur:
                cur.execute("SELECT COUNT(*) as total, AVG(rule_count) as avg_rules FROM memory_injections")
                row = cur.fetchone()
                total = int(row[0]) if row else 0
                avg_rules = float(row[1]) if row and row[1] is not None else 0.0
            return {"injection_count": total, "avg_rules_per_plan": round(avg_rules, 2), "validated_patterns_available": len(self.get_validated_patterns())}
        except Exception:
            return {"injection_count": 0, "avg_rules_per_plan": 0.0, "validated_patterns_available": 0}
    def save_attribution(self, ts, plan_id, episode_id, memory_rules_count, memory_confidence, planner_decision, analyst_consensus, debate_verdict, survival_mode, outcome_quality, survival_score_delta, equity_delta_pct, memory_contribution_score) -> int:
        with self._get_conn().cursor() as cur:
            cur.execute("INSERT INTO memory_attributions (ts, plan_id, episode_id, memory_rules_count, memory_confidence, planner_decision, analyst_consensus, debate_verdict, survival_mode, outcome_quality, survival_score_delta, equity_delta_pct, memory_contribution_score, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                        (ts, plan_id, episode_id, memory_rules_count, memory_confidence, planner_decision, analyst_consensus, debate_verdict, survival_mode, outcome_quality, survival_score_delta, equity_delta_pct, memory_contribution_score, ts))
            return int(cur.fetchone()[0])
    def get_recent_attributions(self, limit=20) -> List[Dict[str, Any]]:
        try:
            with self._get_conn().cursor() as cur:
                cur.execute("SELECT * FROM memory_attributions ORDER BY ts DESC LIMIT %s", (limit,))
                rows = cur.fetchall(); cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, r)) for r in rows]
        except Exception:
            log.exception("get_recent_attributions failed"); return []
    def update_attribution(self, episode_id, outcome_quality, survival_score_delta, equity_delta_pct, memory_contribution_score) -> None:
        with self._get_conn().cursor() as cur:
            cur.execute("UPDATE memory_attributions SET outcome_quality=%s, survival_score_delta=%s, equity_delta_pct=%s, memory_contribution_score=%s WHERE episode_id=%s AND outcome_quality='pending'",
                        (outcome_quality, survival_score_delta, equity_delta_pct, memory_contribution_score, episode_id))
    def get_attribution_metrics(self) -> Dict[str, Any]:
        try:
            with self._get_conn().cursor() as cur:
                cur.execute("SELECT COUNT(*) as total, AVG(memory_contribution_score) as avg_contrib, SUM(CASE WHEN outcome_quality='positive' THEN 1 ELSE 0 END) as pos, SUM(CASE WHEN outcome_quality='negative' THEN 1 ELSE 0 END) as neg, SUM(CASE WHEN outcome_quality='neutral' THEN 1 ELSE 0 END) as neu FROM memory_attributions")
                row = cur.fetchone()
                total = int(row[0]) if row else 0
                avg_contrib = float(row[1]) if row and row[1] is not None else 0.0
                pos = int(row[2]) if row else 0
                neg = int(row[3]) if row else 0
                neu = int(row[4]) if row else 0
            return {"total_attributions": total, "average_contribution_score": round(avg_contrib, 4), "memory_success_count": pos, "memory_failure_count": neg, "memory_neutral_count": neu, "memory_alignment_rate": round(pos / max(1, total), 4), "memory_success_rate": round(pos / max(1, pos + neg), 4) if (pos + neg) > 0 else 0.0}
        except Exception:
            return {"total_attributions": 0, "average_contribution_score": 0.0, "memory_alignment_rate": 0.0, "memory_success_rate": 0.0, "memory_failure_rate": 0.0}
    def save_shadow_memory_influence(self, ts, plan_id, planner_action, planner_confidence, memory_action, memory_confidence, agreement, influence_weight, shadow_influence_score, pattern_ids_json, validation_scores_json, survival_mode, analyst_consensus, debate_verdict) -> int:
        with self._get_conn().cursor() as cur:
            cur.execute("INSERT INTO shadow_memory_influence (ts, plan_id, planner_action, planner_confidence, memory_action, memory_confidence, agreement, influence_weight, shadow_influence_score, pattern_ids_json, validation_scores_json, survival_mode, analyst_consensus, debate_verdict) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                        (ts, plan_id, planner_action, planner_confidence, memory_action, memory_confidence, agreement, influence_weight, shadow_influence_score, pattern_ids_json, validation_scores_json, survival_mode, analyst_consensus, debate_verdict))
            return int(cur.fetchone()[0])
    def get_recent_shadow_memory_influence(self, limit=20) -> List[Dict[str, Any]]:
        try:
            with self._get_conn().cursor() as cur:
                cur.execute("SELECT * FROM shadow_memory_influence ORDER BY ts DESC LIMIT %s", (limit,))
                rows = cur.fetchall(); cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, r)) for r in rows]
        except Exception:
            log.exception("get_recent_shadow_memory_influence failed"); return []
    def get_shadow_memory_influence_metrics(self) -> Dict[str, Any]:
        try:
            with self._get_conn().cursor() as cur:
                cur.execute("SELECT COUNT(*) as total, SUM(CASE WHEN agreement='AGREE' THEN 1 ELSE 0 END) as agrees, SUM(CASE WHEN agreement='DISAGREE' THEN 1 ELSE 0 END) as disagrees, AVG(shadow_influence_score) as avg_shadow, AVG(memory_confidence) as avg_mem_conf FROM shadow_memory_influence")
                row = cur.fetchone()
                total = int(row[0]) if row else 0
                agrees = int(row[1]) if row else 0
                disagrees = int(row[2]) if row else 0
                avg_shadow = float(row[3]) if row and row[3] is not None else 0.0
                avg_mem_conf = float(row[4]) if row and row[4] is not None else 0.0
            return {"total_evaluations": total, "agreement_count": agrees, "disagreement_count": disagrees, "agreement_rate": round(agrees / max(1, total), 4), "disagreement_rate": round(disagrees / max(1, total), 4), "avg_shadow_influence_score": round(avg_shadow, 4), "avg_memory_confidence": round(avg_mem_conf, 4)}
        except Exception:
            return {"total_evaluations": 0, "agreement_count": 0, "disagreement_count": 0, "agreement_rate": 0.0, "disagreement_rate": 0.0, "avg_shadow_influence_score": 0.0, "avg_memory_confidence": 0.0}
    def save_reasoning_audit(self, plan_id, llm_provider, memory_usage_score, ml_used, procedural_used, episodic_used, shadow_used, portfolio_used, risk_used, treasury_used, reasoning_json, context_size_chars=0, latency_ms=0.0, raw_content_length=0) -> None:
        with self._get_conn().cursor() as cur:
            cur.execute("INSERT INTO agent_reasoning_audit (plan_id, llm_provider, memory_usage_score, ml_used, procedural_used, episodic_used, shadow_used, portfolio_used, risk_used, treasury_used, reasoning_json, context_size_chars, latency_ms, raw_content_length) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (plan_id, llm_provider, memory_usage_score, ml_used, procedural_used, episodic_used, shadow_used, portfolio_used, risk_used, treasury_used, reasoning_json, context_size_chars, latency_ms, raw_content_length))
    def get_reasoning_audits(self, limit=20) -> List[Dict[str, Any]]:
        try:
            with self._get_conn().cursor() as cur:
                cur.execute("SELECT * FROM agent_reasoning_audit ORDER BY created_at DESC LIMIT %s", (limit,))
                rows = cur.fetchall(); cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, r)) for r in rows]
        except Exception:
            log.exception("get_reasoning_audits failed"); return []
    def get_reasoning_audit_summary(self) -> Dict[str, Any]:
        try:
            with self._get_conn().cursor() as cur:
                cur.execute("SELECT COUNT(*) as total, COALESCE(AVG(memory_usage_score),0), COALESCE(AVG(context_size_chars),0), COALESCE(AVG(latency_ms),0), COALESCE(SUM(CASE WHEN ml_used THEN 1 ELSE 0 END),0), COALESCE(SUM(CASE WHEN procedural_used THEN 1 ELSE 0 END),0), COALESCE(SUM(CASE WHEN episodic_used THEN 1 ELSE 0 END),0), COALESCE(SUM(CASE WHEN shadow_used THEN 1 ELSE 0 END),0), COALESCE(SUM(CASE WHEN portfolio_used THEN 1 ELSE 0 END),0), COALESCE(SUM(CASE WHEN risk_used THEN 1 ELSE 0 END),0), COALESCE(SUM(CASE WHEN treasury_used THEN 1 ELSE 0 END),0) FROM agent_reasoning_audit")
                row = cur.fetchone()
            total = int(row[0]) if row else 0
            names = ["ml_prediction", "procedural_memory", "episodic_memory", "shadow_memory", "portfolio_state", "risk_state", "treasury"]
            counts = [int(v or 0) for v in row[4:11]] if row else [0] * 7
            rates = {name: round(count / max(1, total), 4) for name, count in zip(names, counts)}
            most_ignored = min(rates, key=rates.get) if rates else "unknown"
            return {"total_audits": total, "avg_memory_usage_score": round(float(row[1] or 0), 4), "avg_context_size_chars": round(float(row[2] or 0), 1), "avg_latency_ms": round(float(row[3] or 0), 1), "most_ignored_dimension": most_ignored, "dimension_usage_rates": rates}
        except Exception:
            log.exception("get_reasoning_audit_summary failed")
            return {"total_audits": 0, "avg_memory_usage_score": 0.0, "avg_context_size_chars": 0.0, "avg_latency_ms": 0.0, "most_ignored_dimension": "unknown", "dimension_usage_rates": {}}
    def save_reasoning_feedback(self, plan_id, reflection, missing_dimensions, recommended_improvements, severity="info") -> None:
        with self._get_conn().cursor() as cur:
            cur.execute("INSERT INTO agent_reasoning_feedback (plan_id, reflection, missing_dimensions, recommended_improvements, severity) VALUES (%s,%s,%s,%s,%s)",
                        (plan_id, reflection, missing_dimensions, recommended_improvements, severity))

    # ── Phase 10.5 — Trade Replay ──
    def save_trade_replay_event(self, trade_id, event_type, event_data, event_index, timestamp="", status="", duration_ms=0.0, provider="", confidence=0.0, latency_ms=0.0, plan_id=0) -> None:
        with self._get_conn().cursor() as cur:
            cur.execute(
                "INSERT INTO agent_trade_replay_events (trade_id, event_type, event_data, event_index, timestamp, status, duration_ms, provider, confidence, latency_ms, plan_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (trade_id, event_type, event_data, event_index, timestamp, status, duration_ms, provider, confidence, latency_ms, plan_id),
            )

    def save_trade_replay_summary(self, trade_id, contract, side, plan_id, llm_provider, status, total_duration_ms, event_count, created_at) -> None:
        with self._get_conn().cursor() as cur:
            cur.execute(
                "INSERT INTO agent_trade_replay_summary (trade_id, contract, side, plan_id, llm_provider, status, total_duration_ms, event_count, created_at, updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW()) ON CONFLICT (trade_id) DO UPDATE SET status=EXCLUDED.status, total_duration_ms=EXCLUDED.total_duration_ms, event_count=EXCLUDED.event_count, updated_at=NOW()",
                (trade_id, contract, side, plan_id, llm_provider, status, total_duration_ms, event_count, created_at),
            )

    def get_trade_replay_events(self, trade_id: str) -> List[Dict[str, Any]]:
        try:
            with self._get_conn().cursor() as cur:
                cur.execute("SELECT * FROM agent_trade_replay_events WHERE trade_id=%s ORDER BY event_index ASC", (trade_id,))
                rows = cur.fetchall()
                cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, r)) for r in rows]
        except Exception:
            log.exception("get_trade_replay_events failed")
            return []

    def get_trade_replay_summary(self, limit: int = 50) -> List[Dict[str, Any]]:
        try:
            with self._get_conn().cursor() as cur:
                cur.execute("SELECT * FROM agent_trade_replay_summary ORDER BY created_at DESC LIMIT %s", (limit,))
                rows = cur.fetchall()
                cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, r)) for r in rows]
        except Exception:
            log.exception("get_trade_replay_summary failed")
            return []

# ===================== SQLite =====================
class SQLiteAgentStorage(AgentStorage):
    def __init__(self, db_path: str = "agent/agent.sqlite") -> None:
        self._db_path = db_path
    def _con(self) -> sqlite3.Connection:
        con = sqlite3.connect(self._db_path); con.execute("PRAGMA journal_mode=WAL"); return con
    def init_schema(self) -> None:
        with self._con() as con: con.executescript(SQLITE_SCHEMA)
        log.info("SQLiteAgentStorage: schema initialized at %s", self._db_path)
    def save_plan(self, ts, input_snapshot, plan) -> int:
        with self._con() as con:
            return int(con.execute("INSERT INTO agent_plans (ts, input_snapshot, plan_json, status) VALUES (?,?,?,?)", (ts.isoformat(), json.dumps(input_snapshot), json.dumps(plan), "executed")).lastrowid)
    def save_action(self, plan_id, ts, action_type, action_params, result, success) -> None:
        with self._con() as con:
            con.execute("INSERT INTO agent_actions (plan_id, ts, action_type, action_params, result_json, success) VALUES (?,?,?,?,?,?)", (plan_id, ts.isoformat(), action_type, json.dumps(action_params), json.dumps(result), int(success)))
    def save_treasury(self, ts, treasury_usdt, cost_per_day_usd, llm_cost_usd, survival_mode) -> None:
        with self._con() as con:
            con.execute("INSERT INTO agent_treasury (ts, treasury_usdt, cost_per_day_usd, llm_cost_usd, survival_mode) VALUES (?,?,?,?,?)", (ts.isoformat(), treasury_usdt, cost_per_day_usd, llm_cost_usd, survival_mode))
    def load_treasury(self) -> Optional[float]:
        try:
            row = self._con().execute("SELECT treasury_usdt FROM agent_treasury ORDER BY ts DESC LIMIT 1").fetchone()
            return float(row[0]) if row else None
        except Exception: return None
    def get_recent_plans(self, limit=10) -> List[Dict[str, Any]]:
        try:
            rows = self._con().execute("SELECT id, ts, plan_json, input_snapshot, status FROM agent_plans ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
            return [{"id": r[0], "ts": r[1], "plan": json.loads(r[2] or "{}"), "input_snapshot": json.loads(r[3] or "{}"), "status": r[4]} for r in rows]
        except Exception: return []
    def get_recent_actions(self, limit=20) -> List[Dict[str, Any]]:
        try:
            rows = self._con().execute("SELECT id, plan_id, ts, action_type, result_json, success FROM agent_actions ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
            return [{"id": r[0], "plan_id": r[1], "ts": r[2], "action_type": r[3], "result": json.loads(r[4] or "{}"), "success": bool(r[5])} for r in rows]
        except Exception: return []
    def save_shadow_observation(self, plan_id, ts, recommended_action, recommended_params, contract, survival_mode, system_action, position_size_before, position_size_after, tpsl_changed, entries_paused, agreement, status, equity_at_obs, drawdown_at_obs) -> int:
        with self._con() as con:
            return int(con.execute("INSERT INTO shadow_observations (plan_id, ts, recommended_action, recommended_params, contract, survival_mode, system_action, position_size_before, position_size_after, tpsl_changed, entries_paused, agreement, status, equity_at_obs, drawdown_at_obs) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (plan_id, ts.isoformat(), recommended_action, recommended_params, contract, survival_mode, system_action, position_size_before, position_size_after, tpsl_changed, entries_paused, agreement, status, equity_at_obs, drawdown_at_obs)).lastrowid)
    def update_shadow_observation(self, obs_id, resolved_at=None, equity_24h_after=None, asset_return_24h=None, equity_change_24h=None, counterfactual_pnl=None) -> None:
        with self._con() as con:
            con.execute("UPDATE shadow_observations SET status='RESOLVED', resolved_at=COALESCE(?,resolved_at), equity_24h_after=COALESCE(?,equity_24h_after), asset_return_24h=COALESCE(?,asset_return_24h), equity_change_24h=COALESCE(?,equity_change_24h), counterfactual_pnl=COALESCE(?,counterfactual_pnl) WHERE id=?", (resolved_at.isoformat() if resolved_at else None, equity_24h_after, asset_return_24h, equity_change_24h, counterfactual_pnl, obs_id))
    def get_shadow_observations(self, limit=20, status=None, agreement=None) -> List[Dict[str, Any]]:
        try:
            parts = ["1=1"]; par = []
            if status: parts.append("status=?"); par.append(status)
            if agreement: parts.append("agreement=?"); par.append(agreement)
            par.append(limit)
            with self._con() as con:
                con.row_factory = sqlite3.Row
                rows = con.execute(f"SELECT * FROM shadow_observations WHERE {' AND '.join(parts)} ORDER BY ts DESC LIMIT ?", par).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            log.exception("get_shadow_observations failed"); return []
    def get_pending_shadow_observations(self) -> List[Dict[str, Any]]:
        try:
            with self._con() as con:
                con.row_factory = sqlite3.Row
                return [dict(r) for r in con.execute("SELECT * FROM shadow_observations WHERE status='PENDING_24H' ORDER BY ts ASC").fetchall()]
        except Exception:
            log.exception("get_pending_shadow_observations failed"); return []
    def save_analyst_reports(self, plan_id, ts, reports_json, consensus, confidence, breakdown_json) -> None:
        with self._con() as con:
            con.execute("INSERT INTO analyst_reports (plan_id, ts, reports_json, consensus, confidence, breakdown_json) VALUES (?,?,?,?,?,?)", (plan_id, ts.isoformat(), reports_json, consensus, confidence, breakdown_json))
    def get_recent_analyst_reports(self, limit=10) -> List[Dict[str, Any]]:
        try:
            with self._con() as con:
                con.row_factory = sqlite3.Row
                return [dict(r) for r in con.execute("SELECT * FROM analyst_reports ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()]
        except Exception:
            log.exception("get_recent_analyst_reports failed"); return []
    def save_bullbear_debate(self, plan_id, ts, bull_json, bear_json, verdict_json, bull_confidence, bear_confidence, net_bias, final_verdict, final_conviction, override_flag) -> int:
        with self._con() as con:
            return int(con.execute("INSERT INTO bullbear_debates (plan_id, ts, bull_json, bear_json, verdict_json, bull_confidence, bear_confidence, net_bias, final_verdict, final_conviction, override_flag) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (plan_id, ts.isoformat(), bull_json, bear_json, verdict_json, bull_confidence, bear_confidence, net_bias, final_verdict, final_conviction, int(override_flag))).lastrowid)
    def get_recent_bullbear_debates(self, limit=10) -> List[Dict[str, Any]]:
        try:
            with self._con() as con:
                con.row_factory = sqlite3.Row
                return [dict(r) for r in con.execute("SELECT * FROM bullbear_debates ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()]
        except Exception:
            log.exception("get_recent_bullbear_debates failed"); return []
    def save_experiment_run(self, started_at, initial_capital) -> int:
        with self._con() as con:
            return int(con.execute("INSERT INTO experiment_runs (started_at, initial_capital, current_capital, peak_capital) VALUES (?,?,?,?)", (started_at.isoformat(), initial_capital, initial_capital, initial_capital)).lastrowid)
    def update_experiment_run(self, experiment_id, current_capital, peak_capital, max_drawdown, days_alive, survival_score, plans_generated, debates_generated, analyst_reports_generated, shadow_observations, agreement_rate, total_return_pct, highest_runway_days, lowest_runway_days, best_survival_score, worst_survival_score, runway_days, notes="") -> None:
        with self._con() as con:
            con.execute("""UPDATE experiment_runs SET current_capital=?, peak_capital=?, max_drawdown=?, days_alive=?, survival_score=?, plans_generated=?, debates_generated=?, analyst_reports_generated=?, shadow_observations=?, agreement_rate=?, total_return_pct=?, highest_runway_days=?, lowest_runway_days=?, best_survival_score=?, worst_survival_score=?, runway_days=?, notes=? WHERE id=?""", (current_capital, peak_capital, max_drawdown, days_alive, survival_score, plans_generated, debates_generated, analyst_reports_generated, shadow_observations, agreement_rate, total_return_pct, highest_runway_days, lowest_runway_days, best_survival_score, worst_survival_score, runway_days, notes, experiment_id))
    def get_active_experiment(self) -> Optional[Dict[str, Any]]:
        try:
            with self._con() as con:
                con.row_factory = sqlite3.Row
                row = con.execute("SELECT * FROM experiment_runs WHERE status='RUNNING' ORDER BY started_at DESC LIMIT 1").fetchone()
            return dict(row) if row else None
        except Exception: return None
    def get_experiment_history(self, limit=10) -> List[Dict[str, Any]]:
        try:
            with self._con() as con:
                con.row_factory = sqlite3.Row
                return [dict(r) for r in con.execute("SELECT * FROM experiment_runs ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()]
        except Exception: return []
    def save_episode(self, ts, plan_id, action_type, survival_mode, treasury_usdt, survival_score, analyst_consensus, debate_verdict, snapshot_json, outcome_json, importance_score) -> int:
        with self._con() as con:
            return int(con.execute("INSERT INTO agent_episodes (ts, plan_id, action_type, survival_mode, treasury_usdt, survival_score, analyst_consensus, debate_verdict, snapshot_json, outcome_json, importance_score, resolved, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (ts.isoformat(), plan_id, action_type, survival_mode, treasury_usdt, survival_score, analyst_consensus, debate_verdict, snapshot_json, outcome_json, importance_score, 0, ts.isoformat())).lastrowid)
    def update_episode_outcome(self, episode_id, outcome_json, resolved=True) -> None:
        with self._con() as con:
            con.execute("UPDATE agent_episodes SET outcome_json=?, resolved=? WHERE id=?", (outcome_json, 1 if resolved else 0, episode_id))
    def get_recent_episodes(self, limit=20) -> List[Dict[str, Any]]:
        try:
            with self._con() as con:
                con.row_factory = sqlite3.Row
                return [dict(r) for r in con.execute("SELECT * FROM agent_episodes ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()]
        except Exception:
            log.exception("get_recent_episodes failed"); return []
    def get_episode(self, episode_id: int) -> Optional[Dict[str, Any]]:
        try:
            with self._con() as con:
                con.row_factory = sqlite3.Row
                row = con.execute("SELECT * FROM agent_episodes WHERE id=?", (episode_id,)).fetchone()
            return dict(row) if row else None
        except Exception:
            log.exception("get_episode failed"); return None
    def get_unresolved_episodes(self, limit=100) -> List[Dict[str, Any]]:
        try:
            with self._con() as con:
                con.row_factory = sqlite3.Row
                return [dict(r) for r in con.execute("SELECT * FROM agent_episodes WHERE resolved=0 ORDER BY ts ASC LIMIT ?", (limit,)).fetchall()]
        except Exception:
            log.exception("get_unresolved_episodes failed"); return []
    def resolve_episode(self, episode_id, outcome_json) -> None:
        with self._con() as con:
            con.execute("UPDATE agent_episodes SET outcome_json=?, resolved=1 WHERE id=?", (outcome_json, episode_id))
    def save_pattern(self, pattern_key, action_type, condition_json, sample_size, positive_count, negative_count, neutral_count, success_rate, confidence_score, last_episode_id_processed=0) -> int:
        with self._con() as con:
            existing = con.execute("SELECT id FROM semantic_patterns WHERE pattern_key=?", (pattern_key,)).fetchone()
            if existing:
                con.execute("""UPDATE semantic_patterns SET sample_size=?, positive_count=?, negative_count=?, neutral_count=?, success_rate=?, confidence_score=?, last_seen=?, active=1, last_episode_id_processed=? WHERE pattern_key=?""",
                            (sample_size, positive_count, negative_count, neutral_count, success_rate, confidence_score, datetime.now(tz=timezone.utc).isoformat(), last_episode_id_processed, pattern_key))
                return int(existing[0])
            else:
                now = datetime.now(tz=timezone.utc).isoformat()
                return int(con.execute("INSERT INTO semantic_patterns (pattern_key, action_type, condition_json, sample_size, positive_count, negative_count, neutral_count, success_rate, confidence_score, first_seen, last_seen, active, last_episode_id_processed) VALUES (?,?,?,?,?,?,?,?,?,?,?,1,?)",
                                       (pattern_key, action_type, condition_json, sample_size, positive_count, negative_count, neutral_count, success_rate, confidence_score, now, now, last_episode_id_processed)).lastrowid)
    def get_patterns(self, limit=50) -> List[Dict[str, Any]]:
        try:
            with self._con() as con:
                con.row_factory = sqlite3.Row
                return [dict(r) for r in con.execute("SELECT * FROM semantic_patterns WHERE active=1 ORDER BY confidence_score DESC LIMIT ?", (limit,)).fetchall()]
        except Exception:
            log.exception("get_patterns failed"); return []
    def get_pattern_by_key(self, pattern_key: str) -> Optional[Dict[str, Any]]:
        try:
            with self._con() as con:
                con.row_factory = sqlite3.Row
                row = con.execute("SELECT * FROM semantic_patterns WHERE pattern_key=?", (pattern_key,)).fetchone()
            return dict(row) if row else None
        except Exception: return None
    def validate_pattern(self, pattern_key: str, validated: bool, validation_score: float) -> None:
        with self._con() as con:
            con.execute("UPDATE semantic_patterns SET validated=?, validation_score=?, last_validated_at=?, active=? WHERE pattern_key=?",
                        (1 if validated else 0, validation_score, datetime.now(tz=timezone.utc).isoformat(), 1 if validated else 0, pattern_key))
    def get_validated_patterns(self, limit=50) -> List[Dict[str, Any]]:
        try:
            with self._con() as con:
                con.row_factory = sqlite3.Row
                return [dict(r) for r in con.execute("SELECT * FROM semantic_patterns WHERE validated=1 ORDER BY validation_score DESC LIMIT ?", (limit,)).fetchall()]
        except Exception:
            log.exception("get_validated_patterns failed"); return []
    def save_memory_advice(self, ts, plan_id, planner_decision, memory_decision, difference_detected, confidence, reason_json) -> int:
        with self._con() as con:
            return int(con.execute("INSERT INTO memory_advice (ts, plan_id, planner_decision, memory_decision, difference_detected, confidence, reason_json) VALUES (?,?,?,?,?,?,?)",
                                  (ts.isoformat(), plan_id, planner_decision, memory_decision, 1 if difference_detected else 0, confidence, reason_json)).lastrowid)
    def get_recent_memory_advice(self, limit=20) -> List[Dict[str, Any]]:
        try:
            with self._con() as con:
                con.row_factory = sqlite3.Row
                return [dict(r) for r in con.execute("SELECT * FROM memory_advice ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()]
        except Exception:
            log.exception("get_recent_memory_advice failed"); return []
    def get_memory_advice_stats(self) -> Dict[str, Any]:
        try:
            with self._con() as con:
                row = con.execute("SELECT COUNT(*) as total, SUM(CASE WHEN difference_detected=1 THEN 1 ELSE 0 END) as diffs, AVG(confidence) as avg_conf FROM memory_advice").fetchone()
                total = int(row[0]) if row else 0
                diffs = int(row[1]) if row else 0
                avg_conf = float(row[2]) if row and row[2] is not None else 0.0
            return {"advice_count": total, "agreement_count": total - diffs, "disagreement_count": diffs, "agreement_rate": round((total - diffs) / max(1, total), 4), "disagreement_rate": round(diffs / max(1, total), 4), "avg_confidence": round(avg_conf, 4)}
        except Exception:
            return {"advice_count": 0, "agreement_count": 0, "disagreement_count": 0, "agreement_rate": 0.0, "disagreement_rate": 0.0, "avg_confidence": 0.0}
    def save_memory_injection(self, ts, plan_id, rule_count, rules_json) -> int:
        with self._con() as con:
            return int(con.execute("INSERT INTO memory_injections (ts, plan_id, rule_count, rules_json, planner_used_memory, created_at) VALUES (?,?,?,?,?,?)",
                                  (ts.isoformat(), plan_id, rule_count, rules_json, 0, ts.isoformat())).lastrowid)
    def get_recent_memory_injections(self, limit=20) -> List[Dict[str, Any]]:
        try:
            with self._con() as con:
                con.row_factory = sqlite3.Row
                return [dict(r) for r in con.execute("SELECT * FROM memory_injections ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()]
        except Exception:
            log.exception("get_recent_memory_injections failed"); return []
    def get_memory_injection_stats(self) -> Dict[str, Any]:
        try:
            with self._con() as con:
                row = con.execute("SELECT COUNT(*) as total, AVG(rule_count) as avg_rules FROM memory_injections").fetchone()
                total = int(row[0]) if row else 0
                avg_rules = float(row[1]) if row and row[1] is not None else 0.0
            return {"injection_count": total, "avg_rules_per_plan": round(avg_rules, 2), "validated_patterns_available": len(self.get_validated_patterns())}
        except Exception:
            return {"injection_count": 0, "avg_rules_per_plan": 0.0, "validated_patterns_available": 0}
    def save_attribution(self, ts, plan_id, episode_id, memory_rules_count, memory_confidence, planner_decision, analyst_consensus, debate_verdict, survival_mode, outcome_quality, survival_score_delta, equity_delta_pct, memory_contribution_score) -> int:
        with self._con() as con:
            return int(con.execute("INSERT INTO memory_attributions (ts, plan_id, episode_id, memory_rules_count, memory_confidence, planner_decision, analyst_consensus, debate_verdict, survival_mode, outcome_quality, survival_score_delta, equity_delta_pct, memory_contribution_score, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                  (ts.isoformat(), plan_id, episode_id, memory_rules_count, memory_confidence, planner_decision, analyst_consensus, debate_verdict, survival_mode, outcome_quality, survival_score_delta, equity_delta_pct, memory_contribution_score, ts.isoformat())).lastrowid)
    def get_recent_attributions(self, limit=20) -> List[Dict[str, Any]]:
        try:
            with self._con() as con:
                con.row_factory = sqlite3.Row
                return [dict(r) for r in con.execute("SELECT * FROM memory_attributions ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()]
        except Exception:
            log.exception("get_recent_attributions failed"); return []
    def update_attribution(self, episode_id, outcome_quality, survival_score_delta, equity_delta_pct, memory_contribution_score) -> None:
        with self._con() as con:
            con.execute("UPDATE memory_attributions SET outcome_quality=?, survival_score_delta=?, equity_delta_pct=?, memory_contribution_score=? WHERE episode_id=? AND outcome_quality='pending'",
                        (outcome_quality, survival_score_delta, equity_delta_pct, memory_contribution_score, episode_id))
    def get_attribution_metrics(self) -> Dict[str, Any]:
        try:
            with self._con() as con:
                row = con.execute("SELECT COUNT(*) as total, AVG(memory_contribution_score) as avg_contrib, SUM(CASE WHEN outcome_quality='positive' THEN 1 ELSE 0 END) as pos, SUM(CASE WHEN outcome_quality='negative' THEN 1 ELSE 0 END) as neg, SUM(CASE WHEN outcome_quality='neutral' THEN 1 ELSE 0 END) as neu FROM memory_attributions").fetchone()
                total = int(row[0]) if row else 0
                avg_contrib = float(row[1]) if row and row[1] is not None else 0.0
                pos = int(row[2]) if row else 0
                neg = int(row[3]) if row else 0
                neu = int(row[4]) if row else 0
            return {"total_attributions": total, "average_contribution_score": round(avg_contrib, 4), "memory_success_count": pos, "memory_failure_count": neg, "memory_neutral_count": neu, "memory_alignment_rate": round(pos / max(1, total), 4), "memory_success_rate": round(pos / max(1, pos + neg), 4) if (pos + neg) > 0 else 0.0}
        except Exception:
            return {"total_attributions": 0, "average_contribution_score": 0.0, "memory_alignment_rate": 0.0, "memory_success_rate": 0.0, "memory_failure_rate": 0.0}
    def save_shadow_memory_influence(self, ts, plan_id, planner_action, planner_confidence, memory_action, memory_confidence, agreement, influence_weight, shadow_influence_score, pattern_ids_json, validation_scores_json, survival_mode, analyst_consensus, debate_verdict) -> int:
        with self._con() as con:
            return int(con.execute("INSERT INTO shadow_memory_influence (ts, plan_id, planner_action, planner_confidence, memory_action, memory_confidence, agreement, influence_weight, shadow_influence_score, pattern_ids_json, validation_scores_json, survival_mode, analyst_consensus, debate_verdict) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                  (ts.isoformat(), plan_id, planner_action, planner_confidence, memory_action, memory_confidence, agreement, influence_weight, shadow_influence_score, pattern_ids_json, validation_scores_json, survival_mode, analyst_consensus, debate_verdict)).lastrowid)
    def get_recent_shadow_memory_influence(self, limit=20) -> List[Dict[str, Any]]:
        try:
            with self._con() as con:
                con.row_factory = sqlite3.Row
                return [dict(r) for r in con.execute("SELECT * FROM shadow_memory_influence ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()]
        except Exception:
            log.exception("get_recent_shadow_memory_influence failed"); return []
    def get_shadow_memory_influence_metrics(self) -> Dict[str, Any]:
        try:
            with self._con() as con:
                row = con.execute("SELECT COUNT(*) as total, SUM(CASE WHEN agreement='AGREE' THEN 1 ELSE 0 END) as agrees, SUM(CASE WHEN agreement='DISAGREE' THEN 1 ELSE 0 END) as disagrees, AVG(shadow_influence_score) as avg_shadow, AVG(memory_confidence) as avg_mem_conf FROM shadow_memory_influence").fetchone()
                total = int(row[0]) if row else 0
                agrees = int(row[1]) if row else 0
                disagrees = int(row[2]) if row else 0
                avg_shadow = float(row[3]) if row and row[3] is not None else 0.0
                avg_mem_conf = float(row[4]) if row and row[4] is not None else 0.0
            return {"total_evaluations": total, "agreement_count": agrees, "disagreement_count": disagrees, "agreement_rate": round(agrees / max(1, total), 4), "disagreement_rate": round(disagrees / max(1, total), 4), "avg_shadow_influence_score": round(avg_shadow, 4), "avg_memory_confidence": round(avg_mem_conf, 4)}
        except Exception:
            return {"total_evaluations": 0, "agreement_count": 0, "disagreement_count": 0, "agreement_rate": 0.0, "disagreement_rate": 0.0, "avg_shadow_influence_score": 0.0, "avg_memory_confidence": 0.0}
    def save_reasoning_audit(self, plan_id, llm_provider, memory_usage_score, ml_used, procedural_used, episodic_used, shadow_used, portfolio_used, risk_used, treasury_used, reasoning_json, context_size_chars=0, latency_ms=0.0, raw_content_length=0) -> None:
        now = datetime.now(tz=timezone.utc).isoformat()
        with self._con() as con:
            con.execute("INSERT INTO agent_reasoning_audit (plan_id, llm_provider, memory_usage_score, ml_used, procedural_used, episodic_used, shadow_used, portfolio_used, risk_used, treasury_used, reasoning_json, context_size_chars, latency_ms, raw_content_length, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (plan_id, llm_provider, memory_usage_score, int(ml_used), int(procedural_used), int(episodic_used), int(shadow_used), int(portfolio_used), int(risk_used), int(treasury_used), reasoning_json, context_size_chars, latency_ms, raw_content_length, now))
    def get_reasoning_audits(self, limit=20) -> List[Dict[str, Any]]:
        try:
            with self._con() as con:
                con.row_factory = sqlite3.Row
                return [dict(r) for r in con.execute("SELECT * FROM agent_reasoning_audit ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()]
        except Exception:
            log.exception("get_reasoning_audits failed"); return []
    def get_reasoning_audit_summary(self) -> Dict[str, Any]:
        try:
            with self._con() as con:
                row = con.execute("SELECT COUNT(*) as total, COALESCE(AVG(memory_usage_score),0), COALESCE(AVG(context_size_chars),0), COALESCE(AVG(latency_ms),0), COALESCE(SUM(ml_used),0), COALESCE(SUM(procedural_used),0), COALESCE(SUM(episodic_used),0), COALESCE(SUM(shadow_used),0), COALESCE(SUM(portfolio_used),0), COALESCE(SUM(risk_used),0), COALESCE(SUM(treasury_used),0) FROM agent_reasoning_audit").fetchone()
            total = int(row[0]) if row else 0
            names = ["ml_prediction", "procedural_memory", "episodic_memory", "shadow_memory", "portfolio_state", "risk_state", "treasury"]
            counts = [int(v or 0) for v in row[4:11]] if row else [0] * 7
            rates = {name: round(count / max(1, total), 4) for name, count in zip(names, counts)}
            most_ignored = min(rates, key=rates.get) if rates else "unknown"
            return {"total_audits": total, "avg_memory_usage_score": round(float(row[1] or 0), 4), "avg_context_size_chars": round(float(row[2] or 0), 1), "avg_latency_ms": round(float(row[3] or 0), 1), "most_ignored_dimension": most_ignored, "dimension_usage_rates": rates}
        except Exception:
            log.exception("get_reasoning_audit_summary failed")
            return {"total_audits": 0, "avg_memory_usage_score": 0.0, "avg_context_size_chars": 0.0, "avg_latency_ms": 0.0, "most_ignored_dimension": "unknown", "dimension_usage_rates": {}}
    def save_reasoning_feedback(self, plan_id, reflection, missing_dimensions, recommended_improvements, severity="info") -> None:
        now = datetime.now(tz=timezone.utc).isoformat()
        with self._con() as con:
            con.execute("INSERT INTO agent_reasoning_feedback (plan_id, reflection, missing_dimensions, recommended_improvements, severity, created_at) VALUES (?,?,?,?,?,?)",
                        (plan_id, reflection, missing_dimensions, recommended_improvements, severity, now))

    # ── Phase 10.5 — Trade Replay ──
    def save_trade_replay_event(self, trade_id, event_type, event_data, event_index, timestamp="", status="", duration_ms=0.0, provider="", confidence=0.0, latency_ms=0.0, plan_id=0) -> None:
        with self._con() as con:
            now = datetime.now(tz=timezone.utc).isoformat()
            con.execute(
                "INSERT INTO agent_trade_replay_events (trade_id, event_type, event_data, event_index, timestamp, status, duration_ms, provider, confidence, latency_ms, plan_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (trade_id, event_type, event_data, event_index, timestamp, status, duration_ms, provider, confidence, latency_ms, plan_id, now),
            )

    def save_trade_replay_summary(self, trade_id, contract, side, plan_id, llm_provider, status, total_duration_ms, event_count, created_at) -> None:
        with self._con() as con:
            now = datetime.now(tz=timezone.utc).isoformat()
            con.execute(
                "INSERT OR REPLACE INTO agent_trade_replay_summary (trade_id, contract, side, plan_id, llm_provider, status, total_duration_ms, event_count, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (trade_id, contract, side, plan_id, llm_provider, status, total_duration_ms, event_count, created_at, now),
            )

    def get_trade_replay_events(self, trade_id: str) -> List[Dict[str, Any]]:
        try:
            with self._con() as con:
                con.row_factory = sqlite3.Row
                return [dict(r) for r in con.execute("SELECT * FROM agent_trade_replay_events WHERE trade_id=? ORDER BY event_index ASC", (trade_id,)).fetchall()]
        except Exception:
            log.exception("get_trade_replay_events failed")
            return []

    def get_trade_replay_summary(self, limit: int = 50) -> List[Dict[str, Any]]:
        try:
            with self._con() as con:
                con.row_factory = sqlite3.Row
                return [dict(r) for r in con.execute("SELECT * FROM agent_trade_replay_summary ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()]
        except Exception:
            log.exception("get_trade_replay_summary failed")
            return []

# ===================== Factory =====================
def make_storage() -> AgentStorage:
    mode = os.environ.get("AGENT_STORAGE", "auto").lower()
    dsn  = os.environ.get("AGENT_POSTGRES_DSN", "")
    if mode == "sqlite":
        log.info("AgentStorage: using SQLite"); return SQLiteAgentStorage()
    if mode == "postgres" or (mode == "auto" and dsn):
        if not dsn: raise RuntimeError("AGENT_POSTGRES_DSN env var required for postgres storage")
        try:
            import psycopg2  # noqa: F401
            log.info("AgentStorage: using PostgreSQL"); return PostgresAgentStorage(dsn)
        except ImportError:
            log.warning("psycopg2 not installed — falling back to SQLite storage")
    log.info("AgentStorage: using SQLite (fallback)"); return SQLiteAgentStorage()