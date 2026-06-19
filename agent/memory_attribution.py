"""
agent/memory_attribution.py — Phase 7D.2: Memory Usage Tracking & Decision Attribution.

Measures whether procedural memory contributes to successful decisions.
Observational only — no planner, execution, or policy changes.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from agent.storage import AgentStorage

log = logging.getLogger("agent.memory_attribution")


class MemoryAttributionEngine:
    """
    Tracks and attributes decisions to memory influence.
    Every resolved episode receives attribution.

    memory_contribution_score: 0.0 (memory irrelevant) to 1.0 (strongly aligned)
    """

    def __init__(self, storage: AgentStorage) -> None:
        self._storage = storage

    def record_decision_context(
        self,
        plan_id: int,
        episode_id: int,
        memory_injections: List[Dict[str, Any]],
        planner_decision: str,
        analyst_consensus: str,
        debate_verdict: str,
        survival_mode: str,
    ) -> int:
        """
        Record decision context before outcome is known.
        Returns attribution_id.
        """
        memory_rules_count = len(memory_injections)
        avg_memory_confidence = 0.0
        if memory_rules_count > 0:
            avg_memory_confidence = sum(
                float(r.get("validation_score", 0) or 0) for r in memory_injections
            ) / max(1, memory_rules_count)

        return self._storage.save_attribution(
            ts=datetime.now(tz=timezone.utc),
            plan_id=plan_id,
            episode_id=episode_id,
            memory_rules_count=memory_rules_count,
            memory_confidence=round(avg_memory_confidence, 4),
            planner_decision=planner_decision,
            analyst_consensus=analyst_consensus,
            debate_verdict=debate_verdict,
            survival_mode=survival_mode,
            outcome_quality="pending",
            survival_score_delta=0.0,
            equity_delta_pct=0.0,
            memory_contribution_score=0.0,
        )

    def attribute_outcome(
        self,
        episode_id: int,
        outcome_quality: str,
        survival_score_delta: float,
        equity_delta_pct: float,
    ) -> Optional[Dict[str, Any]]:
        """
        Attribute outcome to memory for a resolved episode.
        Updates the existing pending attribution record in-place.
        No duplicate rows created.
        """
        # Find the pending attribution record for this episode
        attributions = self._storage.get_recent_attributions(limit=100)
        target = None
        for a in attributions:
            if int(a.get("episode_id", 0)) == episode_id and a.get("outcome_quality") == "pending":
                target = a
                break

        if not target:
            log.warning("MemoryAttributionEngine: no pending attribution found for episode %d", episode_id)
            return None

        memory_rules_count = int(target.get("memory_rules_count", 0))
        memory_confidence = float(target.get("memory_confidence", 0.0))

        # Compute memory_contribution_score
        contribution = self._compute_contribution(
            outcome_quality=outcome_quality,
            memory_rules_count=memory_rules_count,
            memory_confidence=memory_confidence,
            survival_score_delta=survival_score_delta,
            equity_delta_pct=equity_delta_pct,
        )

        # UPDATE existing pending record (no duplicate created)
        self._storage.update_attribution(
            episode_id=episode_id,
            outcome_quality=outcome_quality,
            survival_score_delta=round(survival_score_delta, 4),
            equity_delta_pct=round(equity_delta_pct, 4),
            memory_contribution_score=round(contribution, 4),
        )

        log.info(
            "MemoryAttributionEngine: episode %d → quality=%s contribution=%.4f",
            episode_id, outcome_quality, contribution,
        )

        return {
            "episode_id": episode_id,
            "memory_contribution_score": round(contribution, 4),
            "outcome_quality": outcome_quality,
        }

    def _compute_contribution(
        self,
        outcome_quality: str,
        memory_rules_count: int,
        memory_confidence: float,
        survival_score_delta: float,
        equity_delta_pct: float,
    ) -> float:
        """
        Compute memory_contribution_score (0.0 - 1.0).

        Logic:
        - If no memory rules were available (count=0), contribution = 0.0
        - If outcome is positive AND memory was available (count > 0): score based on confidence + delta
        - If outcome is negative: score based on how confidently memory was wrong
        - If outcome is neutral: moderate score
        """
        if memory_rules_count == 0:
            return 0.0

        if outcome_quality == "positive":
            # Memory was available and outcome was positive
            # Contribution = confidence * survival_impact
            surv_factor = min(1.0, max(0.0, survival_score_delta / 10.0))
            equity_factor = min(1.0, max(0.0, equity_delta_pct / 5.0))
            return memory_confidence * (0.5 + 0.25 * surv_factor + 0.25 * equity_factor)

        elif outcome_quality == "negative":
            # Memory was available but outcome was negative
            # Higher confidence with negative outcome = lower contribution
            return memory_confidence * 0.3  # significanly discounted

        else:  # neutral
            return memory_confidence * 0.5

    def compute_memory_contribution(self) -> Dict[str, Any]:
        """Return aggregate contribution metrics."""
        return self._storage.get_attribution_metrics()

    def get_attribution_metrics(self) -> Dict[str, Any]:
        """Return all attribution data for dashboard."""
        records = self._storage.get_recent_attributions(limit=100)
        metrics = self._storage.get_attribution_metrics()
        return {"records": records, "metrics": metrics}