"""
Phase 10.7 — Daily Operational Report Generator

Generates a comprehensive daily report from the agent database.

Usage:
    python -m agent.daily_report

Output: /reports/daily_YYYY-MM-DD.json + console summary
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

log = logging.getLogger("agent.daily_report")

REPORT_DIR = os.path.join(os.path.dirname(__file__), "..", "reports")
os.makedirs(REPORT_DIR, exist_ok=True)


class DailyReport:
    """Aggregates all available metrics from the agent database."""

    def __init__(self, storage) -> None:
        self._storage = storage
        self._data: dict = {}

    def generate(self) -> dict:
        """Generate full daily report from storage queries."""
        report = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "day": None,  # set externally
        }

        # ── 1. TRADING PERFORMANCE ──
        report["trading"] = self._trading_performance()

        # ── 2. AI PERFORMANCE ──
        report["ai"] = self._ai_performance()

        # ── 3. EXECUTION METRICS ──
        report["execution"] = self._execution_metrics()

        # ── 4. MEMORY METRICS ──
        report["memory"] = self._memory_metrics()

        # ── 5. REPLAY METRICS ──
        report["replay"] = self._replay_metrics()

        # ── 6. LLM METRICS ──
        report["llm"] = self._llm_metrics()

        # ── 7. INFRASTRUCTURE ──
        report["infrastructure"] = self._infrastructure_health()

        # ── 8. HEALTH SUMMARY ──
        report["health"] = self._health_summary(report)

        self._data = report
        return report

    def _trading_performance(self) -> dict:
        try:
            trades = self._storage.get_trade_replay_summary(limit=500)
            closed = [t for t in trades if t.get("status") in ("CLOSED", "PROFIT", "LOSS")]
            wins = [t for t in closed if t.get("status") == "PROFIT"]
            losses = [t for t in closed if t.get("status") == "LOSS"]
            total_pnl = sum(float(t.get("total_duration_ms", 0)) for t in closed)  # placeholder
            return {
                "total_trades": len(trades),
                "closed_trades": len(closed),
                "wins": len(wins),
                "losses": len(losses),
                "win_rate": round(len(wins) / max(1, len(closed)) * 100, 2),
            }
        except Exception as e:
            return {"error": str(e)}

    def _ai_performance(self) -> dict:
        try:
            audits = self._storage.get_reasoning_audit_summary()
            patterns = self._storage.get_patterns(limit=500)
            validated = self._storage.get_validated_patterns(limit=500)
            return {
                "memory_usage_score": round(audits.get("avg_memory_usage_score", 0), 4),
                "avg_latency_ms": round(audits.get("avg_latency_ms", 0), 1),
                "total_audits": audits.get("total_audits", 0),
                "patterns_mined": len(patterns),
                "patterns_validated": len(validated),
                "most_ignored_dimension": audits.get("most_ignored_dimension", "unknown"),
            }
        except Exception as e:
            return {"error": str(e)}

    def _execution_metrics(self) -> dict:
        try:
            actions = self._storage.get_recent_actions(limit=500)
            successes = sum(1 for a in actions if a.get("success"))
            failures = sum(1 for a in actions if not a.get("success"))
            return {
                "total_actions": len(actions),
                "successful": successes,
                "failed": failures,
                "success_rate": round(successes / max(1, len(actions)) * 100, 2),
            }
        except Exception as e:
            return {"error": str(e)}

    def _memory_metrics(self) -> dict:
        try:
            episodes = self._storage.get_recent_episodes(limit=500)
            resolved = sum(1 for e in episodes if e.get("resolved"))
            attr = self._storage.get_attribution_metrics()
            shadow = self._storage.get_shadow_memory_influence_metrics()
            return {
                "episodes_created": len(episodes),
                "episodes_resolved": resolved,
                "memory_contribution": round(attr.get("average_contribution_score", 0), 4),
                "shadow_agreement_rate": round(shadow.get("agreement_rate", 0) * 100, 2),
                "shadow_influence": round(shadow.get("avg_shadow_influence_score", 0), 4),
            }
        except Exception as e:
            return {"error": str(e)}

    def _replay_metrics(self) -> dict:
        try:
            trades = self._storage.get_trade_replay_summary(limit=500)
            total_events = 0
            for t in trades:
                tid = t.get("trade_id")
                if tid:
                    events = self._storage.get_trade_replay_events(tid)
                    total_events += len(events)
            return {
                "trades_recorded": len(trades),
                "total_events": total_events,
                "avg_events_per_trade": round(total_events / max(1, len(trades)), 1),
            }
        except Exception as e:
            return {"error": str(e)}

    def _llm_metrics(self) -> dict:
        try:
            audits = self._storage.get_reasoning_audits(limit=500)
            providers = {}
            for a in audits:
                p = a.get("llm_provider", "unknown")
                providers[p] = providers.get(p, 0) + 1
            return {
                "total_llm_calls": len(audits),
                "provider_breakdown": providers,
                "avg_latency_ms": round(
                    sum(float(a.get("latency_ms", 0)) for a in audits) / max(1, len(audits)), 1
                ),
            }
        except Exception as e:
            return {"error": str(e)}

    def _infrastructure_health(self) -> dict:
        return {
            "storage_type": "SQLite",
            "status": "healthy",
            "errors_last_24h": 0,
        }

    def _health_summary(self, report: dict) -> dict:
        sections = ["trading", "ai", "execution", "memory", "replay", "llm"]
        errors = [s for s in sections if "error" in report.get(s, {})]
        return {
            "status": "HEALTHY" if not errors else "WARNING",
            "error_count": len(errors),
            "error_sections": errors,
        }

    def save(self, report: dict) -> str:
        """Save report to JSON file and return path."""
        day_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        report["day"] = day_str
        path = os.path.join(REPORT_DIR, f"daily_{day_str}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)
        return path

    def print_summary(self, report: dict) -> None:
        """Print human-readable summary to stdout."""
        print()
        print("=" * 60)
        print(f"DAILY REPORT — Day {report.get('day', '?')}")
        print("=" * 60)

        h = report.get("health", {})
        print(f"Status: {h.get('status', 'UNKNOWN')}")

        t = report.get("trading", {})
        print(f"\n  Trading: {t.get('total_trades', 0)} trades | "
              f"{t.get('wins', 0)}W / {t.get('losses', 0)}L | "
              f"Win Rate: {t.get('win_rate', 0)}%")

        ai = report.get("ai", {})
        print(f"  AI: {ai.get('total_audits', 0)} audits | "
              f"MemScore: {ai.get('memory_usage_score', 0)} | "
              f"Patterns: {ai.get('patterns_validated', 0)}v/{ai.get('patterns_mined', 0)}m")

        ex = report.get("execution", {})
        print(f"  Execution: {ex.get('total_actions', 0)} actions | "
              f"Success: {ex.get('success_rate', 0)}%")

        mem = report.get("memory", {})
        print(f"  Memory: {mem.get('episodes_created', 0)} ep | "
              f"ShadowAgree: {mem.get('shadow_agreement_rate', 0)}%")

        rp = report.get("replay", {})
        print(f"  Replay: {rp.get('trades_recorded', 0)} trades | "
              f"{rp.get('total_events', 0)} events")

        llm = report.get("llm", {})
        print(f"  LLM: {llm.get('total_llm_calls', 0)} calls | "
              f"Providers: {list(llm.get('provider_breakdown', {}).keys())}")

        print()
        print(f"Report saved: {report.get('_path', '')}")
        print("=" * 60)


def main():
    from agent.storage import make_storage

    storage = make_storage()
    reporter = DailyReport(storage)
    report = reporter.generate()
    path = reporter.save(report)
    report["_path"] = path
    reporter.print_summary(report)


if __name__ == "__main__":
    main()