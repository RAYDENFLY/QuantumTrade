"""
agent/agent.py — Main agent loop (Autonomous Survival Mode C).

Loop:
  1. Fetch snapshot (account + positions + SQLite stats)
  2. Policy layer: tentukan survival mode (deterministik)
  3. Rule-based plan: kalau kondisi jelas → tidak perlu LLM
  4. LLM planning: hanya dipanggil saat perlu (interval + event-based)
  5. Guardrail check semua actions
  6. Execute approved actions
  7. Deduct treasury, simpan ke storage
  8. Tidur sampai interval berikutnya

Jalankan: python -m agent.agent
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# Path setup
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.actions import execute_action
from agent.analysts import AnalystTeam
from agent.guardrails import CircuitBreaker, GuardrailsChecker, RateLimiter
from agent.llm_client import LLMRouter
from agent.policy import PolicyConfig, determine_survival_mode, filter_plan, generate_rule_based_plan, is_emergency
from agent.schema import AgentMode, AgentPlan, AgentSnapshot, SurvivalMode, TokenUsage
from agent.researcher import ResearchTeam
from agent.shadow import ShadowComparator
from agent.snapshot import fetch_snapshot
from agent.memory import EpisodeResolver
from agent.memory_miner import MemoryMiner
from agent.memory_sandbox import MemoryAdvisor
from agent.memory_attribution import MemoryAttributionEngine
from agent.pattern_validator import PatternValidator
from agent.storage import AgentStorage, make_storage

log = logging.getLogger("agent")


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

def _load_agent_config() -> Dict[str, Any]:
    """
    Load config dari env vars + defaults.
    Semua nilai sensitif (API keys, DSN) HANYA dari env.
    """
    import yaml
    cfg_path = os.environ.get("QUANT_CONFIG_PATH", "quant_system/config.yaml")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            base_cfg = yaml.safe_load(f) or {}
    except Exception:
        base_cfg = {}

    # Exchange rate IDR/USD untuk menghitung biaya server
    usdt_to_idr = float((base_cfg.get("display") or {}).get("usdt_to_idr", 16000))

    # Biaya server: Rp 350.000 default (midpoint 300k-400k)
    server_cost_idr = float(os.environ.get("AGENT_SERVER_COST_IDR", "350000"))
    server_cost_monthly_usd = server_cost_idr / usdt_to_idr
    server_cost_daily_usd   = server_cost_monthly_usd / 30.0

    return {
        "dashboard_base_url":     os.environ.get("DASHBOARD_BASE_URL", "http://localhost:8000"),
        "db_path":                (base_cfg.get("paths") or {}).get("db_path", "quant_system/database/quant_system.sqlite"),
        "agent_mode":             os.environ.get("AGENT_MODE", "observe"),
        "ollama_base_url":        os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
        "ollama_primary_model":   os.environ.get("OLLAMA_PRIMARY_MODEL", "qwen2.5:7b"),
        "ollama_fallback_model":  os.environ.get("OLLAMA_FALLBACK_MODEL", "llama3.2:3b"),
        "groq_api_key":           os.environ.get("GROQ_API_KEY", ""),
        "groq_model":             os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
        "deepseek_api_key":       os.environ.get("DEEPSEEK_API_KEY", ""),
        "cloud_budget_per_day":   float(os.environ.get("AGENT_CLOUD_BUDGET_USD", "0.0")),
        "loop_interval_sec":      int(os.environ.get("AGENT_LOOP_INTERVAL_SEC", "300")),   # 5 menit
        "llm_interval_sec":       int(os.environ.get("AGENT_LLM_INTERVAL_SEC", "3600")),  # 1 jam
        "server_cost_daily_usd":  server_cost_daily_usd,
        # Treasury awal — diisi dari storage, ini hanya default pertama kali
        "initial_treasury_usdt":  float(os.environ.get("AGENT_INITIAL_TREASURY_USDT", "20.0")),
        # Survival mode thresholds (bisa override via env)
        "dd_conservative_pct":    float(os.environ.get("AGENT_DD_CONSERVATIVE", "-5.0")),
        "dd_defensive_pct":       float(os.environ.get("AGENT_DD_DEFENSIVE", "-12.0")),
        "dd_emergency_pct":       float(os.environ.get("AGENT_DD_EMERGENCY", "-20.0")),
        # monthly need min/max
        "monthly_need_min_factor": float(os.environ.get("AGENT_MONTHLY_NEED_MIN_FACTOR", "1.0")),
        "monthly_need_max_factor": float(os.environ.get("AGENT_MONTHLY_NEED_MAX_FACTOR", "5.0")),
        "server_cost_monthly_usd": server_cost_monthly_usd,
    }


# ---------------------------------------------------------------------------
# Treasury manager
# ---------------------------------------------------------------------------

class TreasuryManager:
    """
    Track treasury + salary + burn rate.
    Treasury = modal agent untuk bayar operasional.
    """

    def __init__(
        self,
        storage: AgentStorage,
        initial_treasury: float,
        cost_per_day_usd: float,
        monthly_need_usd: float,
        salary_rate: float = 0.10,
    ) -> None:
        self.storage         = storage
        self.cost_per_day    = cost_per_day_usd
        self.monthly_need    = monthly_need_usd
        self.salary_rate     = salary_rate
        self._llm_cost_today = 0.0
        self._cost_day: Optional[str] = None

        # Load dari storage, atau pakai initial value
        saved = storage.load_treasury()
        self.treasury = saved if saved is not None else initial_treasury
        log.info("TreasuryManager init: treasury=$%.2f cost_per_day=$%.4f", self.treasury, cost_per_day_usd)

    def deduct_daily_cost(self) -> None:
        """Panggil sekali per hari — potong biaya operasional."""
        today = time.strftime("%Y-%m-%d")
        if self._cost_day == today:
            return  # sudah dipotong hari ini
        self._cost_day = today
        self._llm_cost_today = 0.0  # reset LLM cost counter
        old = self.treasury
        self.treasury = max(0.0, self.treasury - self.cost_per_day)
        log.warning("Treasury daily cost: $%.4f deducted. %.2f → %.2f", self.cost_per_day, old, self.treasury)

    def add_llm_cost(self, cost_usd: float) -> None:
        today = time.strftime("%Y-%m-%d")
        if self._cost_day != today:
            self._llm_cost_today = 0.0
            self._cost_day = today
        self._llm_cost_today += cost_usd
        # LLM cost JUGA dimasukkan ke treasury jika pakai cloud
        if cost_usd > 0:
            self.treasury = max(0.0, self.treasury - cost_usd)

    def add_profit(self, net_pnl: float) -> float:
        """
        Tambah profit ke treasury (90% retained, 10% salary owner).
        Returns: owner_salary amount.
        """
        if net_pnl <= 0:
            return 0.0
        salary = net_pnl * self.salary_rate
        retained = net_pnl - salary
        self.treasury += retained
        log.warning("Treasury profit: net_pnl=$%.2f → salary=$%.2f retained=$%.2f treasury=$%.2f",
                    net_pnl, salary, retained, self.treasury)
        return salary

    @property
    def is_dead(self) -> bool:
        return self.treasury <= 0.0

    @property
    def runway_days(self) -> float:
        if self.cost_per_day <= 0:
            return 9999.0
        return self.treasury / self.cost_per_day

    def save(self, survival_mode: str) -> None:
        self.storage.save_treasury(
            ts=datetime.now(tz=timezone.utc),
            treasury_usdt=self.treasury,
            cost_per_day_usd=self.cost_per_day,
            llm_cost_usd=self._llm_cost_today,
            survival_mode=survival_mode,
        )


# ---------------------------------------------------------------------------
# Main Agent class
# ---------------------------------------------------------------------------

class AutonomousAgent:
    def __init__(self, cfg: Dict[str, Any]) -> None:
        self.cfg = cfg
        self._mode = AgentMode(cfg["agent_mode"])

        # Policy config
        self._policy_cfg = PolicyConfig()
        self._policy_cfg.dd_conservative     = cfg["dd_conservative_pct"]
        self._policy_cfg.dd_defensive        = cfg["dd_defensive_pct"]
        self._policy_cfg.dd_emergency        = cfg["dd_emergency_pct"]
        self._policy_cfg.operational_cost_per_day_usd = cfg["server_cost_daily_usd"]

        # Storage
        self._storage = make_storage()
        self._storage.init_schema()

        # Treasury
        self._treasury = TreasuryManager(
            storage          = self._storage,
            initial_treasury = cfg["initial_treasury_usdt"],
            cost_per_day_usd = cfg["server_cost_daily_usd"],
            monthly_need_usd = cfg["server_cost_monthly_usd"],
        )

        # LLM
        self._llm = LLMRouter(
            ollama_base_url          = cfg["ollama_base_url"],
            primary_model            = cfg["ollama_primary_model"],
            fallback_model           = cfg["ollama_fallback_model"],
            groq_api_key             = cfg["groq_api_key"] or None,
            groq_model               = cfg["groq_model"],
            deepseek_api_key         = cfg["deepseek_api_key"] or None,
            cloud_budget_per_day_usd = cfg["cloud_budget_per_day"],
        )

        # Guardrails
        self._guardrails = GuardrailsChecker(
            rate_limiter    = RateLimiter(max_per_window=6),
            circuit_breaker = CircuitBreaker(failure_threshold=5, reset_timeout_sec=300),
            max_drawdown_pct = cfg["dd_emergency_pct"],
        )

        # Shadow comparator (Phase 2 — read-only observation)
        self._shadow = ShadowComparator(
            storage             = self._storage,
            dashboard_base_url  = cfg["dashboard_base_url"],
            runner_flags_path   = "agent/.runner_flags.yaml",
            config_path         = "quant_system/config.yaml",
            observation_window_sec = 30,  # 30s window for shadow comparison
        )

        # Analyst team (Phase 4 — multi-analyst reports)
        self._analysts = AnalystTeam()

        # Research team (Phase 5 — Bull/Bear researchers)
        self._research = ResearchTeam()

        # Episode resolver (Phase 7B — outcome resolution)
        self._episode_resolver = EpisodeResolver(storage=self._storage)

        # Phase 7D.2 — Memory Attribution (must be created before EpisodeResolver)
        self._attribution_engine = MemoryAttributionEngine(storage=self._storage)
        # Rebuild episode resolver with attribution engine wired in
        self._episode_resolver = EpisodeResolver(
            storage=self._storage,
            attribution_engine=self._attribution_engine,
        )

        # Phase 7C — Semantic Mining
        self._memory_miner = MemoryMiner(storage=self._storage)
        self._pattern_validator = PatternValidator(storage=self._storage)

        # Phase 7D.0 — Memory Sandbox (advisory only)
        self._memory_advisor = MemoryAdvisor(storage=self._storage)

        # State
        self._survival_mode   = SurvivalMode.NORMAL
        self._last_llm_ts: float = 0.0
        self._loop_count: int = 0

        log.info(
            "AutonomousAgent initialized: mode=%s ollama=%s/%s treasury=$%.2f cost/day=$%.4f",
            self._mode,
            cfg["ollama_primary_model"], cfg["ollama_fallback_model"],
            self._treasury.treasury, cfg["server_cost_daily_usd"],
        )

    def run(self) -> None:
        """Main loop."""
        loop_interval = self.cfg["loop_interval_sec"]
        log.warning("Agent STARTING: mode=%s interval=%ds", self._mode, loop_interval)

        while True:
            try:
                self._tick()
            except KeyboardInterrupt:
                log.warning("Agent stopped by user")
                break
            except Exception:
                log.exception("Agent tick error — sleeping and retrying")
                self._guardrails.circuit_breaker.record_failure()

            time.sleep(loop_interval)

    def _tick(self) -> None:
        self._loop_count += 1
        now = datetime.now(tz=timezone.utc)
        log.info("Agent tick #%d at %s", self._loop_count, now.isoformat())

        # 1. Daily cost deduction
        self._treasury.deduct_daily_cost()

        # 2. Dead check
        if self._treasury.is_dead:
            log.error(
                "AGENT DEAD: treasury=%.2f <= 0. Pausing all entries. Runway=0.",
                self._treasury.treasury,
            )
            execute_action("PAUSE_ENTRIES", {"duration_min": 99999})
            execute_action("SET_SURVIVAL_MODE", {"mode": "HIBERNATE"})
            self._survival_mode = SurvivalMode.HIBERNATE
            self._treasury.save(self._survival_mode.value)
            return

        # 3. Fetch snapshot
        snapshot = fetch_snapshot(
            dashboard_base_url = self.cfg["dashboard_base_url"],
            db_path            = self.cfg["db_path"],
            treasury_usdt      = self._treasury.treasury,
            survival_mode      = self._survival_mode,
            agent_mode         = self._mode,
            llm_cost_today_usd = self._treasury._llm_cost_today,
        )

        # 3b. Run analyst team (Phase 4)
        analyst_reports = self._analysts.analyze(snapshot)
        summary = self._analysts.summarize(analyst_reports)
        log.info(
            "Analyst team: consensus=%s confidence=%.2f",
            summary["consensus"], summary["confidence"],
        )

        # 4. Determine survival mode (deterministik)
        new_mode, reasons = determine_survival_mode(snapshot, self._policy_cfg)
        if new_mode != self._survival_mode:
            log.warning(
                "Survival mode change: %s → %s | reasons: %s",
                self._survival_mode, new_mode, reasons,
            )
            self._survival_mode = new_mode
            execute_action("SET_SURVIVAL_MODE", {"mode": new_mode.value})

        # 5. Rule-based plan (selalu dijalankan)
        rule_plan = generate_rule_based_plan(snapshot, self._policy_cfg)

        # 6. LLM plan (hanya setiap llm_interval atau saat event penting)
        llm_plan: Optional[AgentPlan] = None
        should_call_llm = self._should_call_llm(snapshot)
        if should_call_llm:
            llm_plan, usage = self._llm.generate_plan(snapshot)
            self._last_llm_ts = time.time()
            self._treasury.add_llm_cost(usage.cost_usd)
            log.info("LLM plan generated: summary=%s confidence=%.2f emergency=%s",
                     llm_plan.summary, llm_plan.confidence, llm_plan.emergency)

        # 7. Merge dan execute plans
        # Rule-based plan dieksekusi dulu (priority), lalu LLM plan
        plan_id: Optional[int] = None
        _episode_ids_for_plan: set = set()  # collected during action loop for debate backfill
        for plan in filter(None, [rule_plan, llm_plan]):
            filtered_plan, rejections = filter_plan(plan, snapshot, self._mode, self._policy_cfg)

            if rejections:
                log.info("Policy filtered %d actions: %s", len(rejections), rejections)

            if not filtered_plan.proposed_actions:
                continue

            # Save ke storage
            plan_id = self._storage.save_plan(
                ts             = now,
                input_snapshot = snapshot.model_dump(mode="json"),
                plan           = filtered_plan.model_dump(mode="json"),
            )

            # Execute actions
            for action in filtered_plan.proposed_actions:
                # Guardrail check
                contract = action.params.get("contract")
                allowed, reason = self._guardrails.check_action(action.type, snapshot, contract)
                if not allowed:
                    log.warning("Guardrail BLOCKED %s: %s", action.type, reason)
                    self._storage.save_action(
                        plan_id     = plan_id,
                        ts          = now,
                        action_type = action.type.value,
                        action_params = action.params,
                        result      = {"blocked": reason},
                        success     = False,
                    )
                    continue

                log.warning("EXECUTING action: %s params=%s", action.type, action.params)
                result = execute_action(action.type.value, action.params)
                success = bool(result.get("success", False))

                # Record rate limit untuk order actions
                if success and contract:
                    from agent.schema import HIGH_RISK_ACTIONS, MEDIUM_RISK_ACTIONS
                    if action.type in HIGH_RISK_ACTIONS | MEDIUM_RISK_ACTIONS:
                        self._guardrails.record_order(contract)

                if success:
                    self._guardrails.circuit_breaker.record_success()
                else:
                    self._guardrails.circuit_breaker.record_failure()

                self._storage.save_action(
                    plan_id       = plan_id,
                    ts            = now,
                    action_type   = action.type.value,
                    action_params = action.params,
                    result        = result,
                    success       = success,
                )

                log.info("Action %s result: success=%s detail=%s",
                         action.type, success, result.get("detail", ""))

                # ── Episode recording (Phase 7A — Episodic Memory) ──
                try:
                    import json as _json_ep
                    # Snapshot for the episode (dict-safe serialization)
                    snap_dict = snapshot.model_dump(mode="json") if hasattr(snapshot, 'model_dump') else {}
                    episode_id = self._storage.save_episode(
                        ts                = now,
                        plan_id           = plan_id,
                        action_type       = action.type.value,
                        survival_mode     = self._survival_mode.value,
                        treasury_usdt     = self._treasury.treasury,
                        survival_score    = 0.0,  # will be filled from experiment tracking on next tick
                        analyst_consensus = summary.get("consensus", "unknown"),
                        debate_verdict    = "unknown",  # placeholder — updated after Bull/Bear debate
                        snapshot_json     = _json_ep.dumps(snap_dict),
                        outcome_json      = _json_ep.dumps({"success": success, "result": result, "guardrail_blocked": not allowed}),
                        importance_score  = 0.5,
                    )
                    log.debug("Episode recorded: id=%d action=%s", episode_id, action.type.value)

                    # Collect episode IDs for debate verdict backfill
                    if isinstance(episode_id, int):
                        _episode_ids_for_plan.add(episode_id)

                    # ── Phase 7D.2: Record decision context for attribution ──
                    try:
                        self._attribution_engine.record_decision_context(
                            plan_id=plan_id,
                            episode_id=episode_id,
                            memory_injections=[],
                            planner_decision=action.type.value,
                            analyst_consensus=summary.get("consensus", "unknown"),
                            debate_verdict="unknown",
                            survival_mode=self._survival_mode.value,
                        )
                    except Exception:
                        log.exception("Attribution context recording failed (non-fatal)")

                except Exception:
                    log.exception("Episode recording failed (non-fatal)")

            # ── Shadow observation (Phase 2) ──
            # Compare agent recommendation vs actual system behavior
            # Non-blocking: runs in background thread / on next tick
            if plan_id is not None:
                try:
                    self._shadow.observe(filtered_plan, plan_id)
                except Exception:
                    log.exception("Shadow observe failed (non-fatal)")

        # ── Analyst reports (Phase 4) ──
        if plan_id is not None:
            try:
                import json as _json_ar
                reports_dicts = [r.to_dict() for r in analyst_reports]
                self._storage.save_analyst_reports(
                    plan_id=plan_id,
                    ts=now,
                    reports_json=_json_ar.dumps(reports_dicts),
                    consensus=summary["consensus"],
                    confidence=summary["confidence"],
                    breakdown_json=_json_ar.dumps(summary["breakdown"]),
                )
                log.info(
                    "Analyst reports saved: plan=%d consensus=%s confidence=%.2f",
                    plan_id, summary["consensus"], summary["confidence"],
                )
            except Exception:
                log.exception("Analyst save failed (non-fatal)")

        # ── Bull/Bear research (Phase 5) ──
        if plan_id is not None:
            try:
                import json as _json_bb
                bull, bear, verdict = self._research.run(snapshot, analyst_consensus=summary.get("consensus"))
                debate_id = self._storage.save_bullbear_debate(
                    plan_id=plan_id,
                    ts=now,
                    bull_json=_json_bb.dumps(bull),
                    bear_json=_json_bb.dumps(bear),
                    verdict_json=_json_bb.dumps(verdict),
                    bull_confidence=bull.get("overall_confidence", 0.5),
                    bear_confidence=bear.get("overall_confidence", 0.5),
                    net_bias=verdict.get("net_bias", "neutral"),
                    final_verdict=verdict.get("final_verdict", "neutral"),
                    final_conviction=verdict.get("final_conviction", 0.5),
                    override_flag=verdict.get("override_by_analysts", False),
                )
                log.info(
                    "Bull/Bear debate saved: id=%d bull=%s(%.2f) bear=%s(%.2f) final=%s",
                    debate_id,
                    bull.get("overall_verdict"), bull.get("overall_confidence"),
                    bear.get("overall_verdict"), bear.get("overall_confidence"),
                    verdict.get("final_verdict"),
                )
            except Exception:
                log.exception("Bull/Bear research failed (non-fatal)")

        # ── Phase 7.6.1: Backfill debate_verdict into episodes (merge-safe) ──
        if plan_id is not None and _episode_ids_for_plan:
            try:
                debate_verdict_val = verdict.get("final_verdict", "unknown") if 'verdict' in dir() and isinstance(verdict, dict) else "unknown"
                for ep_id in _episode_ids_for_plan:
                    existing_ep = self._storage.get_episode(ep_id)
                    if existing_ep:
                        merged = existing_ep.get("outcome_json", "{}")
                        if isinstance(merged, str):
                            try:
                                merged = json.loads(merged)
                            except Exception:
                                merged = {}
                        elif not isinstance(merged, dict):
                            merged = {}
                        merged["debate_verdict"] = debate_verdict_val
                        self._storage.update_episode_outcome(
                            episode_id=ep_id,
                            outcome_json=json.dumps(merged),
                            resolved=False,
                        )
            except Exception:
                log.exception("Debate verdict backfill failed (non-fatal)")

        # ── Experiment tracking (Phase 6) ──
        try:
            exp = self._storage.get_active_experiment()
            if exp is None:
                exp_id = self._storage.save_experiment_run(
                    started_at=now,
                    initial_capital=self.cfg["initial_treasury_usdt"],
                )
                # Re-fetch experiment so we use the DB-written values (initial_capital etc.)
                exp = self._storage.get_active_experiment()
            else:
                exp_id = exp["id"]

            current = self._treasury.treasury

            # peak_capital: never lower than initial_capital
            db_peak = float(exp.get("peak_capital", current)) if exp else current
            db_initial = float(exp.get("initial_capital", current)) if exp else current
            if db_peak < db_initial:
                log.warning(
                    "peak_capital (%.2f) < initial_capital (%.2f) — repairing",
                    db_peak, db_initial,
                )
                db_peak = db_initial
            peak = max(db_peak, current)
            drawdown = 0.0
            if peak > 0:
                drawdown = round((peak - current) / peak * 100.0, 2)
            days_alive = 0.0
            if exp:
                import datetime as _dt
                started = exp.get("started_at", now.isoformat())
                started_ts = _dt.datetime.fromisoformat(str(started).replace("Z", "+00:00"))
                days_alive = max(0.0, (now - started_ts).total_seconds() / 86400)
            # Count stats
            plans_c = len(self._storage.get_recent_plans(limit=500))
            debates_c = len(self._storage.get_recent_bullbear_debates(limit=500))
            analysts_c = len(self._storage.get_recent_analyst_reports(limit=500))
            shadows_c = len(self._storage.get_shadow_observations(limit=500))
            # Agreement rate from shadow observations
            shadows_all = self._storage.get_shadow_observations(limit=500)
            agrees = sum(1 for s in shadows_all if s.get("agreement") == "AGREE")
            disagree = sum(1 for s in shadows_all if s.get("agreement") == "DISAGREE")
            agree_rate = round(agrees / max(1, agrees + disagree), 2)
            # Survival score
            cap_growth = ((current - exp.get("initial_capital", current)) / max(0.01, exp.get("initial_capital", current))) * 100 if exp else 0
            cap_score = min(100, max(0, 50 + cap_growth))
            dd_score = min(100, max(0, 100 - abs(drawdown) * 5))
            long_score = min(100, days_alive * 2)
            agree_score = agree_rate * 100
            runway_val = self._treasury.runway_days
            runway_score = min(100, runway_val * 5)
            surv_score = round(cap_score * 0.30 + dd_score * 0.25 + long_score * 0.20 + agree_score * 0.15 + runway_score * 0.10, 1)
            total_return = round(((current - exp.get("initial_capital", current)) / max(0.01, exp.get("initial_capital", current))) * 100, 2) if exp else 0
            prev_best = exp.get("best_survival_score", 0) if exp else 0
            prev_worst = exp.get("worst_survival_score", 100) if exp else 100
            prev_high_runway = exp.get("highest_runway_days", 0) if exp else 0
            prev_low_runway = exp.get("lowest_runway_days", 9999) if exp else 9999
            self._storage.update_experiment_run(
                experiment_id=exp_id,
                current_capital=round(current, 2),
                peak_capital=round(peak, 2),
                max_drawdown=round(drawdown, 2),
                days_alive=round(days_alive, 2),
                survival_score=surv_score,
                plans_generated=plans_c,
                debates_generated=debates_c,
                analyst_reports_generated=analysts_c,
                shadow_observations=shadows_c,
                agreement_rate=agree_rate,
                total_return_pct=total_return,
                highest_runway_days=max(prev_high_runway, runway_val),
                lowest_runway_days=min(prev_low_runway, runway_val if runway_val < 9999 else 0),
                best_survival_score=max(prev_best, surv_score),
                worst_survival_score=min(prev_worst, surv_score),
                runway_days=round(runway_val, 1),
            )
        except Exception:
            log.exception("Experiment tracking failed (non-fatal)")

        # 8. Save treasury state
        self._treasury.save(self._survival_mode.value)
        
        # ── Shadow resolution (Phase 2) ──
        # Resolve observations older than 24h with objective measurements
        try:
            resolved = self._shadow.resolve_pending()
            if resolved > 0:
                log.info("Shadow resolved %d pending observations", resolved)
        except Exception:
            log.exception("Shadow resolve failed (non-fatal)")

        # ── Episode resolution (Phase 7B — Outcome Evaluation) ──
        # Resolve episodes older than 6h with current experiment metrics
        try:
            ep_resolved = self._episode_resolver.resolve_pending_episodes()
            if ep_resolved > 0:
                log.info("EpisodeResolver: resolved %d episodes", ep_resolved)
        except Exception:
            log.exception("Episode resolution failed (non-fatal)")

        # ── Phase 7C: Pattern Mining & Validation (every 50 ticks ≈ 4h) ──
        try:
            if self._loop_count % 50 == 0:
                mined = self._memory_miner.mine_patterns()
                if mined > 0:
                    val_result = self._pattern_validator.validate_patterns()
                    log.info(
                        "MemoryMiner: mined=%d patterns | PatternValidator: validated=%d rejected=%d",
                        mined, val_result.get("validated", 0), val_result.get("rejected", 0),
                    )
        except Exception:
            log.exception("Pattern mining/validation failed (non-fatal)")

        # ── Phase 7D.0: Memory Sandbox advice (per plan, advisory only) ──
        if plan_id is not None:
            try:
                planner_rec = "maintain"
                if rule_plan and rule_plan.proposed_actions:
                    planner_rec = rule_plan.proposed_actions[0].type.value
                elif llm_plan and llm_plan.proposed_actions:
                    planner_rec = llm_plan.proposed_actions[0].type.value
                self._memory_advisor.advise(
                    plan_id=plan_id,
                    planner_decision=planner_rec,
                    survival_mode=self._survival_mode.value,
                    analyst_consensus=summary.get("consensus", "unknown"),
                    debate_verdict=verdict.get("final_verdict", "unknown") if 'verdict' in dir() and isinstance(verdict, dict) else "unknown",
                    treasury_usdt=self._treasury.treasury,
                    drawdown_pct=snapshot.account.drawdown_pct if hasattr(snapshot, 'account') else 0.0,
                )
            except Exception:
                log.exception("MemoryAdvisor advice failed (non-fatal)")

        log.info(
            "Agent tick #%d done. mode=%s treasury=$%.2f runway=%.1fd",
            self._loop_count, self._survival_mode,
            self._treasury.treasury, self._treasury.runway_days,
        )

    def _should_call_llm(self, snapshot: AgentSnapshot) -> bool:
        """Tentukan apakah LLM perlu dipanggil saat ini."""
        llm_interval = self.cfg["llm_interval_sec"]
        since_last   = time.time() - self._last_llm_ts

        # Jangan panggil LLM saat HIBERNATE (hemat resource)
        if self._survival_mode == SurvivalMode.HIBERNATE:
            return False

        # Event-based: panggil LLM kalau ada kondisi abnormal
        emergency = is_emergency(snapshot, self._policy_cfg)
        if emergency and since_last > 60:  # min 1 menit cooldown
            log.info("LLM triggered by emergency condition")
            return True

        # Interval rutin
        if since_last >= llm_interval:
            return True

        return False


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def _setup_logging() -> None:
    import json as _json

    class JsonFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            d = {
                "ts":    self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S"),
                "level": record.levelname,
                "name":  record.name,
                "msg":   record.getMessage(),
            }
            if record.exc_info:
                d["exc"] = self.formatException(record.exc_info)
            return _json.dumps(d, ensure_ascii=False)

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.root.handlers = [handler]
    logging.root.setLevel(logging.INFO)


if __name__ == "__main__":
    _setup_logging()

    # Load .env so AGENT_STORAGE/AGENT_POSTGRES_DSN etc are available
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        try:
            from quant_system.utils.env import load_dotenv
            load_dotenv()
        except Exception:
            pass

    cfg = _load_agent_config()
    agent = AutonomousAgent(cfg)
    agent.run()