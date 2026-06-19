# Phase 7.6.3 — Memory Pipeline Data Lineage Audit

## Complete End-to-End Trace

---

## 1. Complete Lineage Map

### Stage 1: Episode Creation

| Source | Field | Dest (agent_episodes) | Transformer |
|--------|-------|----------------------|-------------|
| `agent.py:403` `save_episode()` | `action.type.value` | `action_type` | Direct copy |
| | `self._survival_mode.value` | `survival_mode` | Direct copy |
| | `summary.get("consensus")` | `analyst_consensus` | From Phase 4 analysts |
| | `"unknown"` (hardcoded) | `debate_verdict` | **PLACEHOLDER** |
| | `snapshot.model_dump()` | `snapshot_json` | Full serialization |
| | `{"success": ..., "result": ...}` | `outcome_json` | Action result |
| | `self._treasury.treasury` | `treasury_usdt` | Direct copy |
| | `0.0` (hardcoded) | `survival_score` | **PLACEHOLDER** |
| | `0.5` (hardcoded) | `importance_score` | Default |
| | `now` | `ts` | Timestamp |

### Stage 2: Debate Verdict Backfill (Phase 7.6.1)

| Source | Dest | Transformer |
|--------|------|-------------|
| `verdict.get("final_verdict")` | `outcome_json.debate_verdict` | **OVERWRITES entire outcome_json** |

**BUG:** Uses `update_episode_outcome()` which does `SET outcome_json=%s` — full replacement. Action result fields (success, result, guardrail_blocked) are **DESTROYED**.

### Stage 3: Episode Resolution (Phase 7B)

| Source | Dest (agent_episodes.outcome_json) | Transformer |
|--------|-----------------------------------|-------------|
| `episode["survival_score"]` | `survival_score_before` | Direct copy |
| `episode["treasury_usdt"]` | `equity_before` | Direct copy |
| `exp["survival_score"]` | `survival_score_after` | Current experiment value |
| `exp["current_capital"]` | `equity_after` | Current experiment value |
| `delta` | `survival_score_delta` | Computed: after - before |
| `(current - stored) / stored` | `equity_delta_pct` | Computed: percentage change |
| `delta > 0 or pct > 0` | `decision_quality` | Classified: positive/negative/neutral |
| `episode["outcome_json"]` | `action_success` | **Reads from existing — may be null** |
| `episode["outcome_json"]` | `action_result` | **Reads from existing — may be null** |

### Stage 4: Pattern Mining (Phase 7C)

| Source | Dest (semantic_patterns) | Transformer |
|--------|-------------------------|-------------|
| `action_type` | `action_type` | Group-by key |
| `survival_mode` | `condition_json.survival_mode` | Group-by key |
| `analyst_consensus` | `condition_json.analyst_consensus` | Group-by key |
| `debate_verdict` | `condition_json.debate_verdict` | Group-by key |
| `outcome_json.decision_quality` | `positive_count/negative_count/neutral_count` | Increment counter |
| Counts → `positive / total` | `success_rate` | Computed |
| `sample_size * distance_from_random` | `confidence_score` | Computed |

### Stage 5: Pattern Validation (Phase 7C.2)

| Source | Dest (semantic_patterns) | Transformer |
|--------|-------------------------|-------------|
| `pattern.sample_size` | `active` | false if < 10 |
| `pattern.confidence_score` | `active` | false if < 0.60 |
| `pattern.success_rate` | `active` | false if < 0.70 |
| `avg_survival_delta > 0` | `active` | false if <= 0 |
| All 4 checks pass | `validated = true` | Deterministic |
| Composite score | `validation_score` | Computed (0.0-1.0) |

### Stage 6: Memory Advice (Phase 7D.0)

| Source | Dest (memory_advice) | Transformer |
|--------|---------------------|-------------|
| `planner_decision` | `planner_decision` | Direct copy |
| Patterns match score | `memory_decision` | Classified from pattern votes |
| Difference detected | `difference_detected` | Computed: memory != planner |
| From matched patterns | `confidence` | Avg validation score |
| Supporting patterns | `reason_json` | JSON with reasons |

### Stage 7: Memory Attribution (Phase 7D.2)

| Source | Dest (memory_attributions) | Transformer |
|--------|---------------------------|-------------|
| `episode_id` | `episode_id` | Direct copy |
| `plan_id` | `plan_id` | Direct copy |
| `memory_injections` | `memory_rules_count` | len(injections) |
| `avg(validation_score)` | `memory_confidence` | Computed |
| `action.type.value` | `planner_decision` | Direct copy |
| `summary.consensus` | `analyst_consensus` | Direct copy |
| `"unknown"` | `debate_verdict` | **Hardcoded placeholder** |
| `survival_mode` | `survival_mode` | Direct copy |
| Outcome from resolution | `outcome_quality` | Positive/negative/neutral |
| From resolution | `survival_score_delta` | Direct copy |
| From resolution | `equity_delta_pct` | Direct copy |
| Contribution algorithm | `memory_contribution_score` | Computed (0.0-1.0) |

---

## 2. Field Traceability Matrix

| Field | Episode → Resolved → Pattern → Validated → Advice → Attribution | Status |
|-------|----------------------------------------------------------------|--------|
| **action_type** | `agent_episodes.action_type` → `semantic_patterns.action_type` (group-by) → `memory_advice` (via pattern lookup) → `memory_attributions.planner_decision` | ✅ **PRESERVED** |
| **survival_mode** | `agent_episodes.survival_mode` → `semantic_patterns.condition_json.survival_mode` (group-by) → `memory_advice` (via pattern matching) → `memory_attributions.survival_mode` | ✅ **PRESERVED** |
| **analyst_consensus** | `agent_episodes.analyst_consensus` → `semantic_patterns.condition_json.analyst_consensus` (group-by) → `memory_advice` (via pattern matching) → `memory_attributions.analyst_consensus` | ✅ **PRESERVED** |
| **debate_verdict** | `agent_episodes.outcome_json.debate_verdict` → `semantic_patterns.condition_json.debate_verdict` (group-by) → `memory_advice` (via pattern matching) → `memory_attributions.debate_verdict` | ⚠️ **LOST** (hardcoded "unknown" in attribution) |
| **success** | `outcome_json.success` → **DESTROYED BY BACKFILL** → `outcome_json.action_success` = null | ❌ **OVERWRITTEN** |
| **decision_quality** | `outcome_json.decision_quality` (computed at resolution) → `semantic_patterns.positive_count` etc. → _not carried to advice/attribution_ | ✅ **PRESERVED** (aggregated into counts) |
| **survival_score_delta** | `outcome_json.survival_score_delta` (computed at resolution) → Pattern `avg_survival_score_delta` (via `_validate_single`) → `memory_attributions.survival_score_delta` | ✅ **PRESERVED** |
| **equity_delta_pct** | `outcome_json.equity_delta_pct` (computed at resolution) → Pattern `avg_equity_delta_pct` (via `_validate_single`) → `memory_attributions.equity_delta_pct` | ✅ **PRESERVED** |

### Issues Found

| Issue | Location | Impact |
|-------|----------|--------|
| 🔴 `success` field overwritten by backfill | Phase 7.6.1 backfill in agent.py:523 | `action_success` null in resolved episodes |
| 🔴 `result` field overwritten by backfill | Phase 7.6.1 backfill in agent.py:523 | Action detail lost permanently |
| 🔴 `debate_verdict` hardcoded as "unknown" in attribution | agent.py line 421: `debate_verdict="unknown"` | Attribution records can't be traced to debate outcome |
| 🟡 `status_json` not stored in pattern | Pattern has `condition_json` but no `outcome_json` | Can't verify which episodes contributed (only via plan linkage) |
| 🟡 `snapshot_json` stored but never used | Episode has full snapshot but no consumer reads it | 2KB+ per episode wasted |

---

## 3. Pattern Provenance

```
QUESTION: Can every validated pattern be traced back to the exact episodes that created it?
```

### Current Traceability

```
Pattern (semantic_patterns)
  ├── pattern_key = "TIGHTEN_RISK|NORMAL|conservative|maintain"
  │     └── Reconstructed from condition_json
  ├── action_type, sample_size, success_rate
  └── last_episode_id_processed (checkpoint, INTEGER)
```

### Traceability Mechanism

The MemoryMiner groups resolved episodes by `(action_type, survival_mode, analyst_consensus, debate_verdict)`. To trace back:

1. **Plan-level trace:** `agent_episodes.plan_id` → `agent_plans.id` — but this is indirect (requires joining plans to episodes)
2. **Checkpoint trace:** `semantic_patterns.last_episode_id_processed` → the max `agent_episodes.id` included
3. **No direct FK:** `semantic_patterns` has no FK column pointing to `agent_episodes` — the pattern only stores `pattern_key` and aggregated counts, not the constituent episode IDs

### Verdict

```
Pattern Provenance: PARTIAL (55/100)
  ✅ Can identify which conditions produced a pattern
  ✅ Can verify sample_size via checkpoint
  ✅ Can replay episodes matching conditions
  ❌ Cannot list exact episode IDs contributing to a pattern
  ❌ No FK from semantic_patterns to agent_episodes
  ❌ If condition_json = "unknown", trace is collapsed
```

**YES, with replay:** You can query `SELECT * FROM agent_episodes WHERE action_type=X AND survival_mode=Y AND analyst_consensus=Z AND debate_verdict=W` to find the exact episodes. But this is a runtime query, not a stored link.

---

## 4. Attribution Provenance

```
QUESTION: Can every attribution record be traced back to the exact decision context that produced it?
```

### Current Traceability

```
Memory Attribution
  ├── episode_id → agent_episodes.id
  ├── plan_id → agent_plans.id
  ├── planner_decision, analyst_consensus, debate_verdict
  ├── memory_rules_count, memory_confidence
  └── NO direct link to memory_injections
      NO direct link to validated_patterns
```

### Traceability Path

```
Attribution → Episode → Plan → Bull/Bear debate → Validated patterns (via conditions match)
                               → Memory injection (via plan_id)
```

Each step requires an SQL JOIN. There is no direct column linking `memory_attributions` to `memory_injections` or `semantic_patterns`.

### Verdict

```
Attribution Provenance: YES (70/100)
  ✅ Can trace via episode_id → agent_episodes.id
  ✅ Can trace via plan_id → agent_plans.id → bullbear_debates.plan_id
  ✅ memory_rules_count and memory_confidence stored
  ❌ No FK to memory_injections (rules_json stored separately)
  ❌ No FK to semantic_patterns (which patterns were used?)
  ❌ debate_verdict = "unknown" (hardcoded in attribution context record_decision_context)
```

---

## 5. Silent Data Loss Detection

| Loss Type | Stage | Evidence | Severity |
|-----------|-------|----------|----------|
| **Overwritten JSON** | Ep 7.6.1 backfill | `update_episode_outcome()` replaces `outcome_json` with `{"debate_verdict":"..."}`, destroying `success`, `result`, `guardrail_blocked` | 🔴 **HIGH** |
| **Dropped fields** | Episode creation | `survival_score=0.0` placeholder — never updated after experiment tracking runs | 🟡 **MEDIUM** |
| **Dropped fields** | Attribution context | `debate_verdict="unknown"` hardcoded — same bug as episodes (attribution context recorded before debate) | 🟡 **MEDIUM** |
| **Dropped fields** | Attribution context | `memory_injections=[]` hardcoded — no context injection wired | 🟡 **MEDIUM** |
| **Null propagation** | Resolution | If backfill destroyed `success`, then `action_success: null` in resolved outcome_json | 🟡 **MEDIUM** |
| **Count duplication** | Pattern mining | **FIXED** in Phase 7C.1 via `last_episode_id_processed` checkpoint — verified idempotent | ✅ **RESOLVED** |
| **Orphaned records** | `semantic_patterns` | Patterns with `active=false` remain in DB — intentional | ✅ **OK** |
| **Stale references** | `snapshot_json` | Stored in `agent_episodes` but never read — 2KB/episode of dead storage | 🟢 **LOW** |

---

## 6. Final Report

### Pipeline Integrity

```
LINEAGE_STATUS = WARNING

Rationale:
- 8 stages are functional end-to-end
- 2 CRITICAL overwrite bugs found (backfill + attribution hardcoded)
- 2 MEDIUM data quality issues (survival_score=0, memory_injections=[])
- No orphaned records or stale FK references
- Checkpoint-based mining is idempotent
```

### Data Loss Risk

```
DATA_LOSS_RISK = HIGH

Primary risk: Phase 7.6.1 backfill destroys outcome_json for every episode.
Every episode created after this fix will lose its "success" field when
backfill runs. If episodes are resolved BEFORE backfill, the original
outcome_json is preserved. But if backfill runs first (which happens
immediately on each tick), the data is lost permanently.

Risk can be reduced to LOW with the merge fix described in 7.6.2.
```

### Traceability Score

```
TRACEABILITY_SCORE = 68 / 100

Breakdown:
  Episode → Resolved:    20/20  ✅ Direct FK + full data
  Resolved → Pattern:    15/20  ⚠️ No direct episode FK, only conditions
  Pattern → Validated:   15/20  ⚠️ Validated flag but no audit log
  Validated → Advice:    10/20  ❌ No FK to patterns used
  Advice → Attribution:   8/20  ❌ No FK to injections or patterns
```

### Phase 8 Readiness

```
READY_FOR_PHASE_8 = FALSE

Required fixes before Phase 8:
1. 🔴 Fix debate backfill to MERGE (not REPLACE) outcome_json
2. 🔴 Fix attribution context to use actual debate_verdict
3. 🟡 Fix attribution context to pass actual memory_injections
4. 🟡 Update episode survival_score after experiment tracking
```

### Summary of Issues

| # | Severity | Component | Issue | Fix |
|---|----------|-----------|-------|-----|
| 1 | 🔴 | Phase 7.6.1 backfill | `update_episode_outcome()` replaces JSON | Read existing → merge → write |
| 2 | 🔴 | Attribution context (agent.py:421) | `debate_verdict="unknown"` hardcoded | Read verdict after debate or use backfill value |
| 3 | 🟡 | Attribution context (agent.py:420) | `memory_injections=[]` hardcoded | Wire ProceduralMemory.inject_for_plan() result |
| 4 | 🟡 | Episode creation (agent.py:409) | `survival_score=0.0` never updated | Update episode after experiment tracking runs |
| 5 | 🟢 | snapshot_json storage | Stored but never consumed | Can be ignored or cleaned up later |