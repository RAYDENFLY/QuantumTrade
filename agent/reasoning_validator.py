"""
Phase 9.2 — Reasoning Validation Layer

Proves (or disproves) that the LLM is actually using the memory context
provided by MemoryContextBuilder.

For every generated AgentPlan, scans the output for explicit references to
each memory dimension and produces a Memory Usage Score.

Stores results in agent_reasoning_audit table.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from agent.schema import AgentPlan
from agent.storage import AgentStorage

log = logging.getLogger("agent.reasoning_validator")


# Keywords that indicate the LLM explicitly referenced each memory dimension
REFERENCE_KEYWORDS = {
    "ml_prediction": [
        "ml prediction", "model confidence", "prediction", "probability",
        "feature", "model says", "lightgbm", "directional", "forecast",
    ],
    "procedural_memory": [
        "validated pattern", "procedural memory", "pattern", "historical pattern",
        "success rate", "sample size", "pattern confidence", "proven pattern",
    ],
    "episodic_memory": [
        "episodic memory", "previous episode", "past outcome", "similar situation",
        "historical episode", "resolved episode", "past experience", "we previously",
        "last time", "previously when", "outcome quality",
    ],
    "shadow_memory": [
        "shadow memory", "memory influence", "memory disagreement", "memory suggested",
        "memory recommended", "memory influence score", "shadow influence",
        "memory vs planner",
    ],
    "portfolio_state": [
        "portfolio", "position", "equity", "exposure", "open position",
        "current balance", "available margin", "treasury", "capital",
    ],
    "risk_state": [
        "risk", "drawdown", "survival mode", "risk level", "circuit breaker",
        "risk metric", "order rate", "risk tolerance",
    ],
    "treasury": [
        "treasury", "runway", "budget", "cost", "burn rate",
        "treasury usdt", "operating cost",
    ],
}


class ReasoningAuditRecord:
    """Single reasoning audit entry."""

    def __init__(
        self,
        plan_id: int,
        llm_provider: str,
        raw_content: str,
        plan: AgentPlan,
        context_size_chars: int = 0,
        latency_ms: float = 0.0,
    ) -> None:
        self.plan_id = plan_id
        self.llm_provider = llm_provider
        self.raw_content = raw_content
        self.plan = plan
        self.context_size_chars = context_size_chars
        self.latency_ms = latency_ms

        # Run validation at construction
        self.result = self._validate()

    def _validate(self) -> Dict[str, Any]:
        """Analyze the raw LLM output for memory references."""
        content_lower = self.raw_content.lower()
        sections_used: Dict[str, Dict[str, Any]] = {}
        total_sections = len(REFERENCE_KEYWORDS)
        used_count = 0

        for section, keywords in REFERENCE_KEYWORDS.items():
            found = []
            for kw in keywords:
                if kw in content_lower:
                    found.append(kw)
            if found:
                used_count += 1
                sections_used[section] = {
                    "used": True,
                    "matched_keywords": found,
                    "confidence": round(min(1.0, len(found) / len(keywords)), 2),
                }
            else:
                sections_used[section] = {
                    "used": False,
                    "matched_keywords": [],
                    "confidence": 0.0,
                }

        memory_usage_score = round(used_count / max(1, total_sections), 2)

        # Extract reasoning from plan fields
        reasoning_text = ""
        if self.plan.observations:
            reasoning_text += " ".join(self.plan.observations) + " "
        if self.plan.risks:
            reasoning_text += " ".join(self.plan.risks) + " "
        if self.plan.summary:
            reasoning_text += self.plan.summary
        for action in self.plan.proposed_actions:
            if action.why:
                reasoning_text += " " + action.why

        return {
            "memory_usage_score": memory_usage_score,
            "sections_used": used_count,
            "sections_total": total_sections,
            "sections": sections_used,
            "ml_used": sections_used.get("ml_prediction", {}).get("used", False),
            "procedural_used": sections_used.get("procedural_memory", {}).get("used", False),
            "episodic_used": sections_used.get("episodic_memory", {}).get("used", False),
            "shadow_used": sections_used.get("shadow_memory", {}).get("used", False),
            "portfolio_used": sections_used.get("portfolio_state", {}).get("used", False),
            "risk_used": sections_used.get("risk_state", {}).get("used", False),
            "treasury_used": sections_used.get("treasury", {}).get("used", False),
            "reasoning_excerpt": reasoning_text[:500],
            "raw_length": len(self.raw_content),
        }

    def to_db_record(self) -> Dict[str, Any]:
        r = self.result
        return {
            "plan_id": self.plan_id,
            "llm_provider": self.llm_provider,
            "memory_usage_score": r["memory_usage_score"],
            "ml_used": r["ml_used"],
            "procedural_used": r["procedural_used"],
            "episodic_used": r["episodic_used"],
            "shadow_used": r["shadow_used"],
            "portfolio_used": r["portfolio_used"],
            "risk_used": r["risk_used"],
            "treasury_used": r["treasury_used"],
            "reasoning_json": json.dumps({
                "sections": r["sections"],
                "reasoning_excerpt": r["reasoning_excerpt"],
                "plan_summary": self.plan.summary,
                "proposed_actions": [a.type.value for a in self.plan.proposed_actions],
                "plan_confidence": self.plan.confidence,
            }),
            "context_size_chars": self.context_size_chars,
            "latency_ms": self.latency_ms,
            "raw_content_length": r["raw_length"],
        }


class ReasoningValidator:
    """
    Validates LLM reasoning quality for every generated plan.
    Stores audit records in agent_reasoning_audit.
    """

    def __init__(self, storage: AgentStorage) -> None:
        self._storage = storage

    def audit_plan(
        self,
        plan_id: int,
        llm_provider: str,
        raw_content: str,
        plan: AgentPlan,
        context_size_chars: int = 0,
        latency_ms: float = 0.0,
    ) -> Dict[str, Any]:
        """Audit a single LLM-generated plan for memory usage."""
        record = ReasoningAuditRecord(
            plan_id=plan_id,
            llm_provider=llm_provider,
            raw_content=raw_content,
            plan=plan,
            context_size_chars=context_size_chars,
            latency_ms=latency_ms,
        )

        db_data = record.to_db_record()
        try:
            self._storage.save_reasoning_audit(**db_data)
        except Exception as e:
            log.warning("Failed to save reasoning audit: %s", e)

        log.info(
            "Reasoning audit: plan=%d provider=%s score=%.0f%% "
            "ml=%s proc=%s epi=%s shad=%s port=%s risk=%s treas=%s",
            plan_id, llm_provider,
            record.result["memory_usage_score"] * 100,
            record.result["ml_used"],
            record.result["procedural_used"],
            record.result["episodic_used"],
            record.result["shadow_used"],
            record.result["portfolio_used"],
            record.result["risk_used"],
            record.result["treasury_used"],
        )

        return record.result

    def get_recent_audits(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return recent reasoning audit records."""
        try:
            return self._storage.get_reasoning_audits(limit=limit)
        except Exception as e:
            log.warning("Failed to fetch reasoning audits: %s", e)
            return []

    def get_summary_stats(self) -> Dict[str, Any]:
        """Compute aggregate reasoning quality statistics."""
        try:
            return self._storage.get_reasoning_audit_summary()
        except Exception as e:
            log.warning("Failed to compute reasoning summary: %s", e)
            return {
                "total_audits": 0,
                "avg_memory_usage_score": 0.0,
                "most_used_section": "unknown",
                "least_used_section": "unknown",
                "ml_usage_rate": 0.0,
                "procedural_usage_rate": 0.0,
                "episodic_usage_rate": 0.0,
                "shadow_usage_rate": 0.0,
                "portfolio_usage_rate": 0.0,
                "risk_usage_rate": 0.0,
                "treasury_usage_rate": 0.0,
            }