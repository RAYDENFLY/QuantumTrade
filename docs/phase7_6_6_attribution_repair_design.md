# Phase 7.6.6 — Attribution Integrity Repair Design

## Design Review & Implementation Plan

**Status: Design only — no implementation**

---

## A. Debate Verdict Repair

### A.1 Problem Analysis

```
Current execution order in _tick():
  1. Action loop → save_episode() → record_decision_context(debate_verdict="unknown")
  2. Analyst reports saved
  3. Bull/Bear Research runs → verdict now available
  4. Phase 7.6.1 backfill updates episode's outcome_json with debate_verdict
  5. Attribution is already recorded with "unknown" — TOO LATE
```

### A.2 Design: Option A (Recommended)

**Move `record_decision_context()` after Bull/Bear Research.**

```python
# Current agent.py _tick() order:
#   Action loop: save_episode() + record_decision_context() ← BAD: debate_verdict unknown
#   Bull/Bear Research

# Proposed order:
#   Action loop: save_episode() only ← collect episode_ids
#   Bull/Bear Research → debate_verdict available
#   For each episode_id: record_decision_context(debate_verdict=actual_verdict)
```

**No data loss:** The episode already has the correct `debate_verdict` in its `outcome_json` (via Phase 7.6.1 backfill). The attribution engine can read it from there.

```python
# Proposed record_decision_context call:
for ep_id in _episode_ids_for_plan:
    ep = self._storage.get_episode(ep_id)
    if ep:
        outcome = ep.get("outcome_json", "{}")
        if isinstance(outcome, str):
            outcome = json.loads(outcome)
        debate = outcome.get("debate_verdict", "unknown") if isinstance(outcome, dict) else "unknown"
        
        self._attribution_engine.record_decision_context(
            plan_id=plan_id,
            episode_id=ep_id,
            memory_injections=... ,  # See Section B
            planner_decision=...,    # Read from episode.action_type
            analyst_consensus=summary.get("consensus", "unknown"),
            debate_verdict=debate,   # ← NOW CORRECT
            survival_mode=...,
        )
```

### A.3 Design: Option B (Alternative)

**Pass the verdict directly from the Bull/Bear result.**

```python
# After Bull/Bear verdict is computed:
debate_verdict_val = verdict.get("final_verdict", "unknown")
for ep_id in _episode_ids_for_plan:
    self._attribution_engine.record_decision_context(
        ...
        debate_verdict=debate_verdict_val,  # ← Direct from debate engine
        ...
    )
```

**Verdict:** Option B is simpler (no extra DB read) but Option A is more robust (reads from source of truth).

---

## B. Memory Injection Lineage

### B.1 Data Flow Diagram

```
Validated Patterns (semantic_patterns)
    │
    ▼
ProceduralMemory.get_relevant_rules(survival_mode, analyst_consensus, debate_verdict)
    │  Returns top-5 validated patterns matching conditions
    ▼
ProceduralMemory.inject_for_plan(plan_id, ...)
    │  Builds memory_context dict + stores memory_injection record
    │
    ├──▶ MemoryAdvisor.advise()        ← Currently uses get_validated_patterns()
    │      Produces counterfactual advice
    │      Stores memory_advice record
    │
    └──▶ MemoryAttributionEngine.record_decision_context()
           Uses memory_context.rules for memory_rules_count
           Uses memory_context.avg_validation_score for memory_confidence
```

### B.2 Required Integration

**Current (broken):**
```python
self._attribution_engine.record_decision_context(
    memory_injections=[],           # ← Always empty
    ...
)
```

**Proposed (fixed):**
```python
# Before action loop starts, build memory context once for this plan:
memory_context = self._procedural_memory.inject_for_plan(
    plan_id=plan_id,
    survival_mode=self._survival_mode.value,
    analyst_consensus=summary.get("consensus", "unknown"),
    debate_verdict=debate_verdict_val,  # From Option A/B above
    treasury_usdt=self._treasury.treasury,
    drawdown_pct=snapshot.account.drawdown_pct if hasattr(snapshot, 'account') else 0.0,
)

# Then pass to attribution:
self._attribution_engine.record_decision_context(
    memory_injections=memory_context.get("memory_context", []),
    ...
)
```

### B.3 Expected Values After Fix

| Field | Before | After |
|-------|--------|-------|
| `memory_rules_count` | Always 0 | 0-5 (matched validated patterns) |
| `memory_confidence` | Always 0.0 | 0.5-0.95 (avg validation_score of matched patterns) |
| `memory_contribution_score` | Always 0.0 | 0.0-0.95 (meaningful, varies by outcome) |

---

## C. Attribution Record Lifecycle

### C.1 Current (broken): CREATE + CREATE

```
record_decision_context() → INSERT → id=10: outcome_quality="pending"
attribute_outcome()      → INSERT → id=12: outcome_quality="positive"
                                  ← 2 rows per episode
                                  ← AVG() is halved
```

### C.2 Design: Single-Record Lifecycle

```
record_decision_context() → INSERT → id=10: outcome_quality="pending"
attribute_outcome()      → UPDATE → id=10: outcome_quality="positive"
                                  ← 1 row per episode
                                  ← AVG() is correct
```

### C.3 Implementation Strategy

Add a new `update_attribution()` method to `AgentStorage` that targets the pending record by `episode_id`:

```python
# In AgentStorage (ABC):
@abstractmethod
def update_attribution(
    self,
    episode_id: int,
    outcome_quality: str,
    survival_score_delta: float,
    equity_delta_pct: float,
    memory_contribution_score: float,
) -> None: ...

# In both backends:
# PostgreSQL:
UPDATE memory_attributions 
SET outcome_quality=%s, survival_score_delta=%s, equity_delta_pct=%s,
    memory_contribution_score=%s
WHERE episode_id=%s AND outcome_quality='pending'

# SQLite:
UPDATE memory_attributions 
SET outcome_quality=?, survival_score_delta=?, equity_delta_pct=?,
    memory_contribution_score=?
WHERE episode_id=? AND outcome_quality='pending'
```

### C.4 Modified `MemoryAttributionEngine.attribute_outcome()`

```python
def attribute_outcome(self, episode_id, outcome_quality, survival_score_delta, equity_delta_pct):
    # Find the pending attribution record
    attributions = self._storage.get_recent_attributions(limit=100)
    target = None
    for a in attributions:
        if int(a.get("episode_id", 0)) == episode_id and a.get("outcome_quality") == "pending":
            target = a
            break
    
    if not target:
        log.warning("No pending attribution found for episode %d", episode_id)
        return None
    
    memory_rules_count = int(target.get("memory_rules_count", 0))
    memory_confidence = float(target.get("memory_confidence", 0.0))
    contribution = self._compute_contribution(
        outcome_quality, memory_rules_count, memory_confidence,
        survival_score_delta, equity_delta_pct,
    )
    
    # UPDATE existing record (was INSERT)
    self._storage.update_attribution(
        episode_id=episode_id,
        outcome_quality=outcome_quality,
        survival_score_delta=round(survival_score_delta, 4),
        equity_delta_pct=round(equity_delta_pct, 4),
        memory_contribution_score=round(contribution, 4),
    )
    
    return {"episode_id": episode_id, "contribution": round(contribution, 4)}
```

---

## D. Storage Audit

### D.1 Required Storage Changes

| Change | Type | Purpose |
|--------|------|---------|
| `update_attribution()` | New abstract method | Update pending → resolved without INSERT |
| PG implementation | New method | `UPDATE ... WHERE episode_id=%s AND outcome_quality='pending'` |
| SQLite implementation | New method | Same pattern with `?` placeholders |

### D.2 Retention of Existing Methods

| Method | Keep? | Reason |
|--------|-------|--------|
| `save_attribution()` | **Keep** | Still needed for CREATE (initial pending record) |
| `update_attribution()` | **NEW** | Needed for UPDATE (resolve without duplicate) |
| `get_recent_attributions()` | **Keep** | Dashboard querying |
| `get_attribution_metrics()` | **Keep** | Dashboard aggregation (will now be accurate) |

### D.3 Indexes

Current indexes on `memory_attributions`:
```sql
CREATE INDEX IF NOT EXISTS idx_memory_attributions_ts ON memory_attributions(ts DESC);
```

**Proposed new index** for UPDATE performance:
```sql
CREATE INDEX IF NOT EXISTS idx_memory_attributions_pending 
ON memory_attributions(episode_id) WHERE outcome_quality='pending';
```

This ensures the UPDATE in `attribute_outcome()` can find the pending record efficiently.

---

## E. Required Code Changes Summary

### E.1 Files to Modify

| File | Changes | Lines Affected |
|------|---------|---------------|
| `agent/storage.py` (ABC) | Add `update_attribution()` abstract method | +5 |
| `agent/storage.py` (PG) | Add `update_attribution()` implementation | +10 |
| `agent/storage.py` (SQLite) | Add `update_attribution()` implementation | +8 |
| `agent/memory_attribution.py` | Modify `attribute_outcome()` to use UPDATE | ~40% rewrite |
| `agent/agent.py` | Move `record_decision_context()` after Bull/Bear + pass real values | ~20 lines |

### E.2 No Changes Required

| Component | Reason |
|-----------|--------|
| `agent/policy.py` | No behavioral changes |
| `agent/schema.py` | No schema changes |
| `agent/actions.py` | No execution changes |
| `agent/memory.py` | EpisodeResolver only uses `attribute_outcome()` — interface unchanged |
| `agent/storage.py` (schemas) | No column changes, only new index |
| `dashboard/app.py` | Already reads from same endpoints — no changes needed |

---

## F. Migration Risk Assessment

### F.1 Risk Matrix

| Change | Risk | Mitigation |
|--------|------|------------|
| Update existing pending records | **Low** | `WHERE outcome_quality='pending'` ensures only pending records affected |
| Missing `update_attribution()` method | **Low** | Python raises `TypeError` at startup if abstract method unimplemented |
| Index creation on PG | **Low** | `CREATE INDEX IF NOT EXISTS` is idempotent |
| Moving `record_decision_context()` call | **Medium** | Must ensure `_episode_ids_for_plan` set is populated before the new call location |
| Duplicate records from old code | **Low** | Old "pending" records are harmless — they'll be ignored by `WHERE outcome_quality != 'pending'` in metrics |

### F.2 Migration Steps (Priority Order)

```
1. Add update_attribution() to ABC + both backends
   → Code compiles, no runtime change yet
   
2. Modify attribute_outcome() to use update_attribution()
   → New code path active, old pending records unaffected
   → All NEW resolutions will UPDATE instead of INSERT
   
3. Move record_decision_context() in agent.py
   → Attribution now gets real debate_verdict + memory_injections
   
4. Add PG index
   → Faster pending record lookups
```

### F.3 Rollback Plan

Each step is independently revertible:
- Step 1: Comment out abstract method → Python error prevents startup (safe failure)
- Step 2: Revert `attribute_outcome()` to `save_attribution()` → back to duplicates (no data loss)
- Step 3: Revert `agent.py` ordering → back to "unknown" verdict (no data loss)
- Step 4: `DROP INDEX IF EXISTS` → query performance degrades (no data loss)

---

## G. Expected Attribution Metrics After Repair

### G.1 Before vs After

| Metric | Before (broken) | After (fixed) |
|--------|----------------|---------------|
| `memory_rules_count` | Always 0 | 0-5 (meaningful) |
| `memory_confidence` | Always 0.0 | 0.5-0.95 (meaningful) |
| `memory_contribution_score` | Always 0.0 | 0.0-0.95 (meaningful) |
| Duplicate records | 2× episode_count | 1× episode_count |
| `AVG(memory_contribution_score)` | 0.0 (halved) | Correct average |
| `debate_verdict` coverage | 0% "unknown" | 100% real values |
| Attribute-to-episode ratio | 2:1 | 1:1 ✅ |

### G.2 Accountability

Once fixed, `memory_contribution_score` will answer:
- **When patterns are matched:** `score > 0` — memory provided useful guidance
- **When no patterns matched:** `score = 0` — memory was not relevant
- **When patterns matched but outcome was negative:** `score = confidence × 0.3` — memory was wrong
- **When patterns matched and outcome was positive:** `score = confidence × (0.5 + ...)` — memory helped

---

## H. Data Lineage Diagram (Post-Repair)

```
agent_episodes (created)
  │ plan_id → agent_plans
  │ action_type → planner_decision
  │ survival_mode → survival_mode
  │ analyst_consensus → analyst_consensus
  │ outcome_json.debate_verdict → debate_verdict
  │
  ├──▶ episode creation stores episode_id in _episode_ids_for_plan
  │
  ├──▶ Bull/Bear Research runs → debate_verdict computed
  │     ↓
  │     Phase 7.6.1 backfill writes debate_verdict to episode.outcome_json
  │
  ├──▶ ProceduralMemory.inject_for_plan() 
  │     │  Uses validated patterns (semantic_patterns WHERE validated=TRUE)
  │     │  Returns memory_context with rules + validation scores
  │     │  Stores memory_injection record (memory_injections)
  │     │
  │     ├──▶ MemoryAdvisor.advise() ← counterfactual sandbox
  │     └──▶ MemoryAttributionEngine.record_decision_context()
  │              │  INSERT INTO memory_attributions (outcome_quality='pending')
  │              │  memory_rules_count = len(memory_context.rules)  ← NOW REAL
  │              │  memory_confidence = avg(validation_score)        ← NOW REAL
  │              │  debate_verdict = from backfilled outcome_json   ← NOW REAL
  │
  └──▶ EpisodeResolver._resolve_single() resolves episode (6h later)
        │  Reads current from experiment_runs
        │  Computes deltas + decision_quality
        │  Writes resolved outcome_json to agent_episodes
        │
        └──▶ MemoryAttributionEngine.attribute_outcome()
                 │  UPDATE memory_attributions SET
                 │    outcome_quality='positive|negative|neutral'
                 │    survival_score_delta=...
                 │    equity_delta_pct=...
                 │    memory_contribution_score=...
                 │  WHERE episode_id=X AND outcome_quality='pending'
                 │  ← NOW SINGLE RECORD PER EPISODE ✅
```

---

## I. Readiness Verdict

```
ATTRIBUTION_READY = FALSE

Current deficiencies:
  1. No update_attribution() method → duplicates persist
  2. record_decision_context() called before debate verdict available
  3. memory_injections=[] always → contribution scores always 0
  4. No ProceduralMemory integration
  
Required before TRUE:
  ✅ Add update_attribution() to ABC + both backends
  ✅ Modify attribute_outcome() to UPDATE instead of INSERT
  ✅ Move record_decision_context() after Bull/Bear in agent.py
  ✅ Wire ProceduralMemory.inject_for_plan() output to attribution
  ✅ Add partial index on (episode_id) WHERE outcome_quality='pending'

Estimated implementation effort:
  storage.py:      ~25 lines (3 methods × 2 backends)
  memory_attribution.py: ~30 lines (rewrite attribute_outcome)
  agent.py:        ~25 lines (reorder + wire memory context)
  
Estimated developer time: 1-2 hours
```

### Estimated Timeline

| Step | Effort | Dependencies |
|------|--------|-------------|
| 1. Add `update_attribution()` abstract | 10 min | None |
| 2. Implement PG + SQLite | 15 min | Step 1 |
| 3. Rewrite `attribute_outcome()` | 20 min | Steps 1-2 |
| 4. Add PG index | 5 min | Step 3 |
| 5. Reorder `agent.py` calls | 15 min | Step 3 |
| 6. Wire `ProceduralMemory` | 15 min | Step 5 |
| 7. Test | 20 min | Steps 1-6 |
| **Total** | **~1.5 hours** | |