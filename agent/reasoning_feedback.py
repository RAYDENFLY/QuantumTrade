"""
Phase 9.3 — Self Reflection & Reasoning Feedback Loop

Analyzes past reasoning audits, generates reflections on ignored memory
dimensions, and injects improvement guidance into future LLM prompts.

Goal: The LLM progressively references more internal state over time.
This is NOT reinforcement learning. This is a lightweight feedback loop.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from agent.storage import AgentStorage

log = logging.getLogger("agent.reasoning_feedback")


# Maps decisions to context dimensions that SHOULD have been considered
DECISION_REQUIRED_CONTEXT = {
    "PAUSE_ENTRIES": ["portfolio_state", "risk_state", "treasury"],
    "RESUME_ENTRIES": ["portfolio_state", "risk_state", "ml_prediction", "procedural_memory"],
    "TIGHTEN_RISK": ["risk_state", "procedural_memory", "episodic_memory", "portfolio_state"],
    "REDUCE_POSITION": ["portfolio_state", "risk_state", "shadow_memory"],
    "CLOSE_POSITION": ["portfolio_state", "risk_state", "episodic_memory", "treasury"],
    "REPLACE_TPSL": ["portfolio_state", "risk_state", "ml_prediction"],
    "CANCEL_STALE_TPSL": ["portfolio_state", "risk_state"],
    "SET_SURVIVAL_MODE": ["risk_state", "treasury", "portfolio_state", "episodic_memory"],
    "UPDATE_CONFIG": ["treasury", "risk_state"],
    "NOTIFY": [],
    "HOLD": ["ml_prediction", "portfolio_state", "risk_state", "procedural_memory"],
}

# Severity levels for missing context
SEVERITY_MAP = {
    "portfolio_state": "high",
    "risk_state": "high",
    "treasury": "high",
    "ml_prediction": "medium",
    "procedural_memory": "medium",
    "episodic_memory": "low",
    "shadow_memory": "low",
}


class ReasoningFeedbackEngine:
    """Generates reflections and improvement suggestions from audit data."""

    def __init__(self, storage: AgentStorage) -> None:
        self._storage = storage

    def analyze_recent_audits(self, limit: int = 20) -> Dict[str, Any]:
        """Analyze recent reasoning audits and generate aggregated feedback."""
        try:
            audits = self._storage.get_reasoning_audits(limit=limit)
        except Exception:
            audits = []

        if not audits:
            return {
                "total_audits": 0,
                "ignored_dimensions": [],
                "most_ignored": None,
                "reflections": [],
                "severity": "info",
            }

        # Count usage per dimension
        dimension_used = {dim: 0 for dim in DECISION_REQUIRED_CONTEXT.keys()}
        dimension_total = {dim: 0 for dim in DECISION_REQUIRED_CONTEXT.keys()}
        dimension_usage: Dict[str, Dict[str, int]] = {}  # dim -> {used, total}

        # Track by section
        sections = ["ml_prediction", "procedural_memory", "episodic_memory",
                     "shadow_memory", "portfolio_state", "risk_state", "treasury"]
        for s in sections:
            dimension_usage[s] = {"used": 0, "total": 0}

        for audit in audits:
            for s in sections:
                if audit.get(f"{s}_used", False):
                    dimension_usage[s]["used"] += 1
                dimension_usage[s]["total"] += 1

        # Find most and least referenced dimensions
        ignored = []
        for s, stats in dimension_usage.items():
            if stats["total"] > 0 and stats["used"] / stats["total"] < 0.5:
                ignored.append({
                    "dimension": s,
                    "usage_rate": round(stats["used"] / stats["total"], 2),
                    "severity": SEVERITY_MAP.get(s, "medium"),
                })

        most_ignored = max(ignored, key=lambda x: x["severity"] == "high") if ignored else None

        # Generate reflections for each ignored dimension
        reflections = []
        for item in ignored:
            reflection = self._generate_reflection(item["dimension"], item["usage_rate"])
            if reflection:
                reflections.append(reflection)

        return {
            "total_audits": len(audits),
            "dimension_usage": dimension_usage,
            "ignored_dimensions": ignored,
            "most_ignored": most_ignored,
            "reflections": reflections,
            "severity": "warning" if most_ignored else "info",
        }

    def _generate_reflection(self, dimension: str, usage_rate: float) -> Optional[Dict[str, Any]]:
        """Generate a human-readable reflection for a specific ignored dimension."""
        templates = {
            "ml_prediction": (
                f"The reasoning referenced ML prediction data in only {usage_rate:.0%} of plans. "
                "ML predictions provide objective directional probabilities. "
                "Ignoring them may lead to decisions not grounded in market data."
            ),
            "procedural_memory": (
                f"Procedural memory usage is at {usage_rate:.0%}. "
                "Validated patterns contain historical success rates and confidence scores. "
                "Reference them to ground decisions in proven experience."
            ),
            "episodic_memory": (
                f"Episodic memory was used in only {usage_rate:.0%} of plans. "
                "Past episode outcomes indicate what worked or failed under similar conditions. "
                "Consider them to avoid repeating mistakes."
            ),
            "shadow_memory": (
                f"Shadow memory influence was referenced in {usage_rate:.0%} of plans. "
                "Memory disagreements may indicate when the planner should reconsider. "
                "Review memory recommendations when available."
            ),
            "portfolio_state": (
                f"Portfolio state was used in {usage_rate:.0%} of plans. "
                "Current equity, positions, and exposure directly impact risk capacity. "
                "They should be considered in every decision."
            ),
            "risk_state": (
                f"Risk state usage is {usage_rate:.0%}. "
                "Drawdown, survival mode, and circuit breaker are critical constraints. "
                "They must influence every risk-related action."
            ),
            "treasury": (
                f"Treasury state was referenced in {usage_rate:.0%} of plans. "
                "Treasury balance and runway determine how aggressively the agent can operate. "
                "They are essential for survival-aware reasoning."
            ),
        }

        text = templates.get(dimension)
        if not text:
            return None

        return {
            "dimension": dimension,
            "usage_rate": usage_rate,
            "severity": SEVERITY_MAP.get(dimension, "medium"),
            "reflection": text,
            "recommendation": f"Explicitly consider {dimension.replace('_', ' ')} in future reasoning.",
        }

    def build_feedback_prompt(self, limit: int = 20) -> Optional[str]:
        """Build a feedback section to inject into the LLM system prompt."""
        analysis = self.analyze_recent_audits(limit=limit)

        if analysis["total_audits"] < 3 or not analysis["ignored_dimensions"]:
            return None

        lines = [
            "===== REASONING FEEDBACK =====",
            f"Recent {analysis['total_audits']} plans show opportunity to improve context usage:",
        ]

        for item in analysis["ignored_dimensions"]:
            severity_icon = "🔴" if item["severity"] == "high" else "🟡" if item["severity"] == "medium" else "🟢"
            dim_label = item["dimension"].replace("_", " ").title()
            lines.append(f"  {severity_icon} {dim_label}: {item['usage_rate']:.0%} usage rate")

        if analysis["reflections"]:
            lines.append("\nImprovement suggestions:")
            for r in analysis["reflections"][:3]:
                lines.append(f"  • {r['reflection'][:150]}...")

        lines.append("\nExplicitly reference ALL available context sections in your analysis.")
        lines.append("This will improve decision quality and risk awareness.")
        lines.append("=" * 40)

        return "\n".join(lines)

    def store_feedback(self, audit_id: Optional[int], plan_id: int) -> Dict[str, Any]:
        """Analyze an audit and store the resulting feedback."""
        try:
            audit = None
            if audit_id:
                audits = self._storage.get_reasoning_audits(limit=50)
                audit = next((a for a in audits if a.get("id") == audit_id), None)

            if not audit:
                # Use latest audits to infer
                analysis = self.analyze_recent_audits(limit=10)
            else:
                # Analyze single audit
                reasoning = audit.get("reasoning_json", {})
                if isinstance(reasoning, str):
                    try:
                        reasoning = json.loads(reasoning)
                    except Exception:
                        reasoning = {}

                ignored = []
                dims = ["ml_prediction", "procedural_memory", "episodic_memory",
                        "shadow_memory", "portfolio_state", "risk_state", "treasury"]
                for d in dims:
                    if not audit.get(f"{d}_used", False):
                        decision = reasoning.get("plan_summary", "")
                        required = DECISION_REQUIRED_CONTEXT.get("HOLD", [])
                        for action in reasoning.get("proposed_actions", []):
                            if action in DECISION_REQUIRED_CONTEXT:
                                required = DECISION_REQUIRED_CONTEXT[action]
                                break
                        if d in required:
                            ignored.append({
                                "dimension": d,
                                "severity": SEVERITY_MAP.get(d, "medium"),
                            })

                analysis = {
                    "total_audits": 1,
                    "ignored_dimensions": ignored,
                }

            reflection_text = ""
            if analysis.get("ignored_dimensions"):
                items = [f"{i['dimension']} (severity: {i['severity']})" for i in analysis["ignored_dimensions"]]
                reflection_text = f"Missing context: {', '.join(items)}"

            feedback = {
                "plan_id": plan_id,
                "reflection": reflection_text,
                "missing_dimensions": json.dumps([i["dimension"] for i in analysis.get("ignored_dimensions", [])]),
                "recommended_improvements": json.dumps([
                    f"Reference {d.replace('_', ' ')} in reasoning"
                    for d in [i["dimension"] for i in analysis.get("ignored_dimensions", [])]
                ]),
                "severity": analysis.get("severity", "info"),
            }

            self._storage.save_reasoning_feedback(**feedback)
            return feedback

        except Exception as e:
            log.warning("Failed to store reasoning feedback: %s", e)
            return {}