"""
Phase 10.5 — Trade Replay / AI Flight Recorder

Records every stage of every trade as a structured timeline that can
be replayed step-by-step exactly as the AI experienced it.

Stages tracked:
   0. Trade created
   1. Market snapshot captured
   2. ML prediction generated
   3. Memory context retrieved (procedural + episodic + shadow)
   4. Reasoning feedback injected
   5. LLM reasoning (Groq/Ollama/DeepSeek)
   6. AgentPlan generated
   7. Guardrail validation
   8. Risk policy applied
   9. Execution request sent
  10. Exchange response received
  11. Position updated (TP/SL set)
  12. PnL realized
  13. Reflection generated
  14. Memory updated
  15. Final outcome
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from agent.storage import AgentStorage

log = logging.getLogger("agent.trade_replay")


class TradeRecorder:
    """
    Records every stage of a trade into agent_trade_replay_events table.
    Each trade gets a unique trade_id and an ordered list of events.

    Thread-safe: uses a per-trade lock to prevent race conditions on
    event ordering.
    """

    def __init__(self, storage: AgentStorage) -> None:
        self._storage = storage
        self._active_trades: Dict[str, Dict[str, Any]] = {}
        self._locks: Dict[str, threading.Lock] = {}
        self._global_lock = threading.Lock()

    def _get_lock(self, trade_id: str) -> threading.Lock:
        """Get or create a per-trade lock."""
        with self._global_lock:
            if trade_id not in self._locks:
                self._locks[trade_id] = threading.Lock()
            return self._locks[trade_id]

    # ------------------------------------------------------------------
    # Lifecycle: Stage 0 — Agent Tick
    # ------------------------------------------------------------------

    def record_agent_tick(
        self,
        trade_id: str,
        tick_number: int,
        survival_mode: str,
        treasury_usdt: float,
        duration_ms: float = 0.0,
    ) -> None:
        """Stage 0: Agent cycle tick that initiated this trade decision."""
        self._record_event(
            trade_id, "agent_tick",
            {
                "tick_number": tick_number,
                "survival_mode": survival_mode,
                "treasury_usdt": treasury_usdt,
            },
            duration_ms=duration_ms,
        )

    # ------------------------------------------------------------------
    # Lifecycle: Stage 1 — Trade Created
    # ------------------------------------------------------------------

    def create_trade(
        self,
        contract: str,
        side: str,
        plan_id: int,
        llm_provider: str = "unknown",
    ) -> str:
        """Create a new trade record and return trade_id."""
        trade_id = f"{plan_id}_{contract}_{int(time.time())}"
        entry: Dict[str, Any] = {
            "trade_id": trade_id,
            "contract": contract,
            "side": side,
            "plan_id": plan_id,
            "llm_provider": llm_provider,
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
            "status": "OPEN",
            "events": [],
            "total_duration_ms": 0.0,
        }
        with self._get_lock(trade_id):
            self._active_trades[trade_id] = entry
        self._record_event(trade_id, "trade_created", {
            "contract": contract,
            "side": side,
            "plan_id": plan_id,
            "llm_provider": llm_provider,
        })
        return trade_id

    # ------------------------------------------------------------------
    # Lifecycle: Stage 1 — Market Snapshot
    # ------------------------------------------------------------------

    def record_market_snapshot(self, trade_id: str, snapshot: Dict[str, Any]) -> None:
        """Stage 1: Market snapshot at decision time."""
        self._record_event(trade_id, "market_snapshot", {
            "equity": snapshot.get("account", {}).get("equity"),
            "drawdown": snapshot.get("account", {}).get("drawdown_pct"),
            "exposure": snapshot.get("account", {}).get("exposure_x"),
            "open_positions": snapshot.get("account", {}).get("open_positions"),
            "treasury": snapshot.get("treasury_usdt"),
            "survival_mode": snapshot.get("survival_mode"),
        })

    # ------------------------------------------------------------------
    # Lifecycle: Stage 2 — ML Prediction
    # ------------------------------------------------------------------

    def record_ml_prediction(self, trade_id: str, prediction: Dict[str, Any]) -> None:
        """Stage 2: ML model output."""
        self._record_event(trade_id, "ml_prediction", {
            "direction": prediction.get("direction"),
            "probability": prediction.get("probability"),
            "confidence": prediction.get("confidence"),
            "top_features": prediction.get("top_features", [])[:3],
            "market_regime": prediction.get("market_regime"),
            "volatility": prediction.get("volatility"),
        })

    # ------------------------------------------------------------------
    # Lifecycle: Stage 3 — Memory Context
    # ------------------------------------------------------------------

    def record_memory_context(self, trade_id: str, context: Dict[str, Any]) -> None:
        """Stage 3: Memory context retrieved (procedural + episodic + shadow)."""
        self._record_event(trade_id, "memory_context", {
            "procedural_patterns": context.get("procedural_count", 0),
            "validated_patterns": context.get("validated_patterns", []),
            "episodic_count": context.get("episodic_count", 0),
            "shadow_agreement_rate": context.get("shadow_agreement", 0),
            "shadow_confidence": context.get("shadow_confidence", 0),
            "context_size_chars": context.get("context_size", 0),
        })

    # ------------------------------------------------------------------
    # Lifecycle: Stage 4 — Reasoning Feedback
    # ------------------------------------------------------------------

    def record_reasoning_feedback(self, trade_id: str, feedback: Optional[str]) -> None:
        """Stage 4: Reasoning feedback injected into prompt."""
        self._record_event(trade_id, "reasoning_feedback", {
            "feedback_injected": bool(feedback),
            "feedback_length": len(feedback) if feedback else 0,
        })

    # ------------------------------------------------------------------
    # Lifecycle: Stage 5 — LLM Reasoning
    # ------------------------------------------------------------------

    def record_llm_reasoning(
        self,
        trade_id: str,
        provider: str,
        model: str,
        prompt_tokens: int,
        output_tokens: int,
        raw_output: str,
        latency_ms: float,
    ) -> None:
        """Stage 5: LLM reasoning response."""
        self._record_event(
            trade_id, "llm_reasoning",
            {
                "provider": provider,
                "model": model,
                "prompt_tokens": prompt_tokens,
                "output_tokens": output_tokens,
                "raw_output_preview": raw_output[:500],
            },
            provider=provider,
            latency_ms=round(latency_ms, 1),
        )

    # ------------------------------------------------------------------
    # Lifecycle: Stage 6 — Agent Plan
    # ------------------------------------------------------------------

    def record_agent_plan(self, trade_id: str, plan: Dict[str, Any]) -> None:
        """Stage 6: AgentPlan with proposed actions."""
        confidence = plan.get("confidence", 0.5)
        self._record_event(
            trade_id, "agent_plan",
            {
                "summary": plan.get("summary", ""),
                "confidence": confidence,
                "emergency": plan.get("emergency", False),
                "action_count": len(plan.get("proposed_actions", [])),
                "proposed_actions": [
                    {"type": a.get("type"), "why": a.get("why", "")[:100]}
                    for a in plan.get("proposed_actions", [])
                ],
            },
            confidence=confidence,
        )

    # ------------------------------------------------------------------
    # Lifecycle: Stage 7 — Guardrail Validation
    # ------------------------------------------------------------------

    def record_guardrail_result(self, trade_id: str, action_type: str, allowed: bool, reason: str) -> None:
        """Stage 7: Guardrail validation result."""
        status = "allowed" if allowed else "blocked"
        self._record_event(
            trade_id, "guardrail",
            {
                "action_type": action_type,
                "allowed": allowed,
                "reason": reason or "passed",
            },
            status=status,
        )

    # ------------------------------------------------------------------
    # Lifecycle: Stage 8 — Risk Validation
    # ------------------------------------------------------------------

    def record_risk_validation(
        self,
        trade_id: str,
        passed: bool,
        reason: str = "",
        risk_metrics: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Stage 8: Risk policy validation result."""
        status = "passed" if passed else "rejected"
        data: Dict[str, Any] = {
            "passed": passed,
            "reason": reason or "",
        }
        if risk_metrics:
            data["risk_metrics"] = risk_metrics
        self._record_event(
            trade_id, "risk_validation",
            data,
            status=status,
        )

    # ------------------------------------------------------------------
    # Lifecycle: Stage 9 — Execution Request
    # ------------------------------------------------------------------

    def record_execution_request(self, trade_id: str, order: Dict[str, Any]) -> None:
        """Stage 9: Order sent to exchange."""
        self._record_event(trade_id, "execution_request", {
            "contract": order.get("contract"),
            "side": order.get("side"),
            "size": order.get("size"),
            "order_type": order.get("order_type"),
            "price": order.get("price"),
            "reduce_only": order.get("reduce_only", False),
            "ioc": order.get("ioc", False),
        })

    # ------------------------------------------------------------------
    # Lifecycle: Stage 10 — Exchange Response
    # ------------------------------------------------------------------

    def record_exchange_response(
        self,
        trade_id: str,
        response: Dict[str, Any],
        latency_ms: float,
    ) -> None:
        """Stage 10: Exchange response received."""
        status = response.get("status", "unknown")
        self._record_event(
            trade_id, "exchange_response",
            {
                "exchange_order_id": response.get("exchange_order_id"),
                "status": status,
                "filled_size": response.get("filled_size", 0),
                "avg_fill_price": response.get("avg_fill_price"),
                "fees": response.get("fees", 0),
                "slippage": response.get("slippage", 0),
                "error": response.get("error"),
            },
            status=status,
            latency_ms=round(latency_ms, 1),
        )

    # ------------------------------------------------------------------
    # Lifecycle: Stage 11 — Position Update (TP/SL)
    # ------------------------------------------------------------------

    def record_position_update(
        self,
        trade_id: str,
        tp_price: Optional[float],
        sl_price: Optional[float],
    ) -> None:
        """Stage 11: TP/SL set on position."""
        self._record_event(trade_id, "position_update", {
            "tp_price": tp_price,
            "sl_price": sl_price,
            "action": "TP_SL_SET",
        })

    # ------------------------------------------------------------------
    # Lifecycle: Stage 16 — Position Close
    # ------------------------------------------------------------------

    def record_position_close(
        self,
        trade_id: str,
        exit_price: float,
        exit_size: float,
        exit_reason: str = "manual",
        realized_pnl: Optional[float] = None,
    ) -> None:
        """Stage 16: Position closed (manual / TP / SL / liquidation)."""
        data: Dict[str, Any] = {
            "exit_price": exit_price,
            "exit_size": exit_size,
            "exit_reason": exit_reason,
        }
        if realized_pnl is not None:
            data["realized_pnl"] = realized_pnl
        self._record_event(trade_id, "position_closed", data, status="closed")

    # ------------------------------------------------------------------
    # Lifecycle: Stage 12 — PnL
    # ------------------------------------------------------------------

    def record_pnl(
        self,
        trade_id: str,
        realized_pnl: float,
        unrealized_pnl: Optional[float] = None,
    ) -> None:
        """Stage 12: PnL realized."""
        self._record_event(trade_id, "pnl_realized", {
            "realized_pnl": realized_pnl,
            "unrealized_pnl": unrealized_pnl,
        })

    # ------------------------------------------------------------------
    # Lifecycle: Stage 13 — Reflection
    # ------------------------------------------------------------------

    def record_reflection(self, trade_id: str, reflection: str) -> None:
        """Stage 13: Self-reflection generated."""
        self._record_event(trade_id, "reflection", {
            "reflection_text": reflection[:500],
        })

    # ------------------------------------------------------------------
    # Lifecycle: Stage 19 — Memory Update
    # ------------------------------------------------------------------

    def record_memory_update(
        self,
        trade_id: str,
        memory_tables: List[str],
        rules_updated: int = 0,
        episodes_updated: int = 0,
        patterns_updated: int = 0,
    ) -> None:
        """Stage 19: Memory system updated after reflection."""
        self._record_event(trade_id, "memory_update", {
            "memory_tables": memory_tables,
            "rules_updated": rules_updated,
            "episodes_updated": episodes_updated,
            "patterns_updated": patterns_updated,
        }, status="completed")

    # ------------------------------------------------------------------
    # Lifecycle: Stage 15 — Trade Complete
    # ------------------------------------------------------------------

    def complete_trade(
        self,
        trade_id: str,
        final_pnl: float,
        outcome: str = "closed",
        notes: str = "",
    ) -> None:
        """Final outcome: trade completed."""
        lock = self._get_lock(trade_id)
        with lock:
            trade = self._active_trades.get(trade_id)
            if not trade:
                return
            start = datetime.fromisoformat(trade["created_at"])
            total_ms = (datetime.now(tz=timezone.utc) - start).total_seconds() * 1000
            trade["total_duration_ms"] = round(total_ms, 1)
            trade["status"] = outcome.upper()
        self._record_event(trade_id, "trade_complete", {
            "final_pnl": final_pnl,
            "outcome": outcome,
            "total_duration_ms": round(total_ms, 1),
            "notes": notes[:200],
        })
        self._flush(trade_id)

    def fail_trade(self, trade_id: str, error: str) -> None:
        """Mark trade as failed with error."""
        self._record_event(trade_id, "trade_failed", {"error": str(error)})
        self._flush(trade_id)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_trade_timeline(self, trade_id: str) -> List[Dict[str, Any]]:
        """Return sorted timeline of all events for a trade."""
        try:
            rows = self._storage.get_trade_replay_events(trade_id)
            return sorted(rows, key=lambda r: r.get("event_index", 0))
        except Exception:
            return []

    def get_all_trades(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return all recorded trades."""
        try:
            return self._storage.get_trade_replay_summary(limit=limit)
        except Exception:
            return []

    # ── Internal ──

    def _record_event(
        self,
        trade_id: str,
        event_type: str,
        data: Dict[str, Any],
        *,
        status: str = "",
        duration_ms: float = 0.0,
        provider: str = "",
        confidence: float = 0.0,
        latency_ms: float = 0.0,
    ) -> None:
        """
        Record a single event in memory and store to DB.

        Thread-safe: uses per-trade lock so event_index is always
        consistent between memory and database.

        Standard metadata injected into every event:
          trade_id, event_type, event_index, timestamp, status,
          duration_ms, provider, confidence, latency_ms, plan_id.
        """
        timestamp = datetime.now(tz=timezone.utc).isoformat()

        # Extract plan_id from active trade metadata if available
        plan_id = 0
        lock = self._get_lock(trade_id)
        with lock:
            trade = self._active_trades.get(trade_id)
            if trade:
                plan_id = trade.get("plan_id", 0)
                idx = len(trade["events"])
            else:
                idx = len(self._active_trades)  # fallback — should not happen
        if trade is None:
            return  # trade already flushed

        # Build event dict with standard metadata
        event = {
            "trade_id": trade_id,
            "event_type": event_type,
            "event_index": idx,
            "timestamp": timestamp,
            "status": status,
            "duration_ms": round(duration_ms, 1),
            "provider": provider,
            "confidence": round(confidence, 4),
            "latency_ms": round(latency_ms, 1),
            "plan_id": plan_id,
            "metadata": json.dumps(data),
        }

        # Store in memory (under lock)
        with lock:
            trade = self._active_trades.get(trade_id)
            if trade:
                trade["events"].append(event)

        # Store in DB (event_index is captured under lock, identical to memory)
        try:
            self._storage.save_trade_replay_event(
                trade_id=trade_id,
                event_type=event_type,
                event_data=json.dumps(data),
                event_index=idx,
                timestamp=timestamp,
                status=status,
                duration_ms=round(duration_ms, 1),
                provider=provider,
                confidence=round(confidence, 4),
                latency_ms=round(latency_ms, 1),
                plan_id=plan_id,
            )
        except Exception as e:
            log.warning("Trade replay event storage failed: %s", e)

    def _flush(self, trade_id: str) -> None:
        """Persist all events and clean up."""
        lock = self._get_lock(trade_id)
        with lock:
            trade = self._active_trades.get(trade_id)
            if not trade:
                return
            try:
                self._storage.save_trade_replay_summary(
                    trade_id=trade_id,
                    contract=trade.get("contract", ""),
                    side=trade.get("side", ""),
                    plan_id=trade.get("plan_id", 0),
                    llm_provider=trade.get("llm_provider", "unknown"),
                    status=trade.get("status", "OPEN"),
                    total_duration_ms=trade.get("total_duration_ms", 0),
                    event_count=len(trade["events"]),
                    created_at=trade.get("created_at", ""),
                )
            except Exception as e:
                log.warning("Trade replay summary save failed: %s", e)

            # Cleanup
            del self._active_trades[trade_id]
            self._locks.pop(trade_id, None)