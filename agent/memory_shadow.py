"""
agent/memory_shadow.py — Phase 8.1: Shadow Memory Influence Layer.

Evaluates how memory WOULD influence planner decisions without allowing
memory to modify live trading behavior.

Memory remains observational. Influence weight = 0.0.
No planner, execution, risk, or trading changes.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from agent.procedural_memory import ProceduralMemory
from agent.storage import AgentStorage

log = logging.getLogger("agent.memory_shadow")

# Recommended actions derived from validated patterns
# Maps action_type -> description
MEMORY_RECOMMENDATION_WEIGHTS = {
    "PAUSE_ENTRIES": 0.9,
    "TIGHTEN_RISK": 0.7,
    "REDUCE_POSITION": 0.6,
    "RESUME_ENTRIES": 0.4,
    "REPLACE_TPSL": 0.5,
    "CANCEL_STALE_TPSL": 0.5,
    "NOTIFY": 0.3,
    "CLOSE_POSITION": 0.8,
    "SET_SURVIVAL_MODE": 0.5,
    "UPDATE_CONFIG": 0.4,
}


class ShadowMemoryInfluence:
    """
    Shadow influence layer that generates memory recommendations
    independently from the planner and records agreement metrics.

    Influence weight = 0.0 — never modifies planner decisions.
    """

    def __init__(
        self,
        storage: AgentStorage,
        procedural_memory: ProceduralMemory,
    ) -> None:
        self._storage = storage
        self._procedural_memory = procedural_memory

    def evaluate(
        self,
        plan_id: int,
        planner_action: str,
        planner_confidence: float,
        survival_mode: str,
        analyst_consensus: str,
        debate_verdict: str,
        treasury_usdt: float,
        drawdown_pct: float,
    ) -> Dict[str, Any]:
        """
        Generate a shadow memory recommendation and compare with planner.

        Steps:
          1. Get relevant validated patterns for current context.
          2. Determine memory-recommended action.
          3. Compare planner vs memory action.
          4. Record agreement/shadow influence metrics.
          5. Store to DB.

        Returns shadow evaluation dict. Planner is never modified.
        """
        # 1. Get validated patterns matching current conditions
        relevant_patterns = self._procedural_memory.get_relevant_rules(
            survival_mode=survival_mode,
            analyst_consensus=analyst_consensus,
            debate_verdict=debate_verdict,
        )

        # 2. Determine memory recommendation from patterns
        memory_action, memory_confidence, pattern_ids, validation_scores = (
            self._determine_memory_recommendation(
                relevant_patterns=relevant_patterns,
                survival_mode=survival_mode,
                treasury_usdt=treasury_usdt,
                drawdown_pct=drawdown_pct,
            )
        )

        # 3. Compare planner vs memory
        agreement = (planner_action == memory_action)
        if agreement:
            agreement_status = "AGREE"
        else:
            agreement_status = "DISAGREE"

        # 4. Compute shadow influence score
        # Influence weight is always 0.0 — this is a shadow measurement
        influence_weight = 0.0
        if agreement:
            shadow_influence_score = min(1.0, planner_confidence * memory_confidence)
        else:
            # How much influence WOULD memory have had?
            shadow_influence_score = memory_confidence * (1.0 - planner_confidence)

        # 5. Store shadow evaluation
        try:
            self._storage.save_shadow_memory_influence(
                ts=datetime.now(tz=timezone.utc),
                plan_id=plan_id,
                planner_action=planner_action,
                planner_confidence=round(planner_confidence, 4),
                memory_action=memory_action,
                memory_confidence=round(memory_confidence, 4),
                agreement=agreement_status,
                influence_weight=influence_weight,
                shadow_influence_score=round(shadow_influence_score, 4),
                pattern_ids_json=json.dumps(pattern_ids),
                validation_scores_json=json.dumps(validation_scores),
                survival_mode=survival_mode,
                analyst_consensus=analyst_consensus,
                debate_verdict=debate_verdict,
            )
            log.info(
                "ShadowMemoryInfluence: plan=%d planner=%s memory=%s agreement=%s "
                "shadow_score=%.4f patterns=%d",
                plan_id, planner_action, memory_action, agreement_status,
                shadow_influence_score, len(pattern_ids),
            )
        except Exception:
            log.exception("ShadowMemoryInfluence: failed to save evaluation (non-fatal)")

        return {
            "plan_id": plan_id,
            "planner_action": planner_action,
            "planner_confidence": planner_confidence,
            "memory_action": memory_action,
            "memory_confidence": memory_confidence,
            "agreement": agreement_status,
            "influence_weight": influence_weight,
            "shadow_influence_score": round(shadow_influence_score, 4),
            "pattern_ids": pattern_ids,
            "validation_scores": validation_scores,
            "pattern_count": len(relevant_patterns),
        }

    def _determine_memory_recommendation(
        self,
        relevant_patterns: List[Dict[str, Any]],
        survival_mode: str,
        treasury_usdt: float,
        drawdown_pct: float,
    ) -> tuple[str, float, List[int], List[float]]:
        """
        Determine what action memory would recommend based on validated patterns.

        Uses a scoring system:
        - Each pattern votes for its action_type weighted by validation_score.
        - The action with the highest cumulative score wins.
        - Confidence = weighted average of supporting pattern validation_scores.

        Returns (memory_action, memory_confidence, pattern_ids, validation_scores).
        """
        if not relevant_patterns:
            # No patterns → default to "maintain" with low confidence
            return "maintain", 0.0, [], []

        # Score each action type based on supporting patterns
        action_scores: Dict[str, float] = {}
        action_confidences: Dict[str, List[float]] = {}
        action_pattern_ids: Dict[str, List[int]] = {}

        for pattern in relevant_patterns:
            action = str(pattern.get("action_type", "maintain"))
            vscore = float(pattern.get("validation_score", 0) or 0)
            pid = int(pattern.get("id", 0))

            # Base score from validation_score
            # Bonus for defensive actions during conservative/defensive modes
            score = vscore
            if survival_mode in ("CONSERVATIVE", "DEFENSIVE", "HIBERNATE"):
                if action in ("PAUSE_ENTRIES", "TIGHTEN_RISK", "REDUCE_POSITION"):
                    score *= 1.2  # Defensive bonus
            elif survival_mode == "NORMAL":
                if action in ("RESUME_ENTRIES",):
                    score *= 1.1  # Normal mode bonus for resuming

            action_scores[action] = action_scores.get(action, 0) + score
            action_confidences.setdefault(action, []).append(vscore)
            action_pattern_ids.setdefault(action, []).append(pid)

        # Select the action with the highest score
        if not action_scores:
            return "maintain", 0.0, [], []

        best_action = max(action_scores, key=action_scores.get)  # type: ignore
        best_score = action_scores[best_action]
        total_score = sum(action_scores.values())

        # Confidence = best action's share of total weighted by avg validation
        action_share = best_score / max(0.001, total_score)
        avg_validation = sum(action_confidences[best_action]) / max(1, len(action_confidences[best_action]))
        memory_confidence = min(1.0, action_share * avg_validation * 1.5)

        pattern_ids = action_pattern_ids[best_action]
        validation_scores = action_confidences[best_action]

        return best_action, round(memory_confidence, 4), pattern_ids, validation_scores

    def get_shadow_metrics(self) -> Dict[str, Any]:
        """Return aggregate shadow influence metrics for dashboard."""
        return self._storage.get_shadow_memory_influence_metrics()

    def get_recent_evaluations(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return recent shadow evaluations."""
        return self._storage.get_recent_shadow_memory_influence(limit=limit)