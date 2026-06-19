"""
Phase 7.10 — Post-Restart Verification Audit
Audit only. No code modifications.
"""
import json
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timezone
from dotenv import load_dotenv
load_dotenv()

import psycopg2

dsn = os.environ["AGENT_POSTGRES_DSN"]
conn = psycopg2.connect(dsn)
cur = conn.cursor()


def q(sql):
    cur.execute(sql)
    cols = [desc[0] for desc in cur.description]
    rows = cur.fetchall()
    return [dict(zip(cols, r)) for r in rows]


now = datetime.now(tz=timezone.utc)

print("=" * 70)
print("PHASE 7.10 — POST-RESTART VERIFICATION AUDIT")
print("=" * 70)
print(f"Audit timestamp: {now.isoformat()}")
print()

# ==================================================================
# Section A — Runtime Version Verification
# ==================================================================
print("=" * 70)
print("SECTION A: RUNTIME VERSION VERIFICATION")
print("=" * 70)

# Get latest plan and episode timestamps
latest_plan = q("SELECT ts FROM agent_plans ORDER BY ts DESC LIMIT 1")
latest_ep = q("SELECT ts FROM agent_episodes ORDER BY ts DESC LIMIT 1")
latest_inj = q("SELECT ts FROM memory_injections ORDER BY ts DESC LIMIT 1")
latest_attr = q("SELECT ts FROM memory_attributions ORDER BY ts DESC LIMIT 1")
latest_adv = q("SELECT ts FROM memory_advice ORDER BY ts DESC LIMIT 1")
latest_pattern = q("SELECT last_seen FROM semantic_patterns ORDER BY last_seen DESC LIMIT 1")

latest_plan_ts = latest_plan[0]["ts"] if latest_plan else None
latest_ep_ts = latest_ep[0]["ts"] if latest_ep else None
latest_inj_ts = latest_inj[0]["ts"] if latest_inj else None
latest_attr_ts = latest_attr[0]["ts"] if latest_attr else None
latest_adv_ts = latest_adv[0]["ts"] if latest_adv else None
latest_pat_ts = latest_pattern[0]["last_seen"] if latest_pattern else None

print(f"Latest plan timestamp:       {latest_plan_ts}")
print(f"Latest episode timestamp:    {latest_ep_ts}")
print(f"Latest injection timestamp:  {latest_inj_ts}")
print(f"Latest attribution timestamp:{latest_attr_ts}")
print(f"Latest advice timestamp:     {latest_adv_ts}")
print(f"Latest pattern update:       {latest_pat_ts}")

# Check for evidence of NEW runtime behavior
has_new_behavior = True
evidence = []

# Evidence 1: Check if any episodes have debate_verdict != "unknown"
eps_with_real_verdict = q("SELECT COUNT(*) as cnt FROM agent_episodes WHERE debate_verdict != 'unknown'")
cnt = eps_with_real_verdict[0]["cnt"]
if cnt > 0:
    evidence.append(f"Episodes with real debate_verdict: {cnt}")
else:
    has_new_behavior = False
    evidence.append("STILL NO episodes with real debate_verdict")

# Evidence 2: Check if any injections exist
inj_count = q("SELECT COUNT(*) as cnt FROM memory_injections")[0]["cnt"]
if inj_count > 0:
    evidence.append(f"Memory injections exist: {inj_count}")
else:
    has_new_behavior = False
    evidence.append("STILL NO memory injections")

# Evidence 3: Check if any attributions exist
attr_count = q("SELECT COUNT(*) as cnt FROM memory_attributions")[0]["cnt"]
if attr_count > 0:
    evidence.append(f"Attribution records exist: {attr_count}")
else:
    has_new_behavior = False
    evidence.append("STILL NO attribution records")

# Evidence 4: Check if patterns exist
pat_count = q("SELECT COUNT(*) as cnt FROM semantic_patterns")[0]["cnt"]
if pat_count > 0:
    evidence.append(f"Patterns exist: {pat_count}")
    # Check checkpoints advancing
    max_cp = q("SELECT MAX(last_episode_id_processed) as mx FROM semantic_patterns WHERE active=true")
    if max_cp[0]["mx"] and max_cp[0]["mx"] > 0:
        evidence.append(f"Checkpoints advancing: max={max_cp[0]['mx']}")
else:
    evidence.append("STILL NO patterns (may need more loops)")

# Evidence 5: Check for advice records
adv_count = q("SELECT COUNT(*) as cnt FROM memory_advice")[0]["cnt"]
if adv_count > 0:
    evidence.append(f"Advice records exist: {adv_count}")
else:
    evidence.append("STILL NO advice records")

print()
print("Evidence of new runtime behavior:")
for e in evidence:
    print(f"  {'✅' if 'STILL' not in e else '❌'} {e}")

if has_new_behavior:
    print("\nRUNTIME_VERSION_STATUS = NEW_RUNTIME")
elif latest_plan_ts and ((now - latest_plan_ts).total_seconds() / 3600) < 1:
    print("\nRUNTIME_VERSION_STATUS = MIXED_RUNTIME (running but not enough data yet)")
else:
    print("\nRUNTIME_VERSION_STATUS = OLD_RUNTIME (agent has not been restarted with new code)")

# ==================================================================
# Section B — Warm-Up Mining Verification
# ==================================================================
print()
print("=" * 70)
print("SECTION B: WARM-UP MINING VERIFICATION")
print("=" * 70)

# Get total plans to estimate loop count
plans_count = len(q("SELECT id FROM agent_plans"))
print(f"Total plans ever:  {plans_count}")
print(f"Estimated loop count (all-time): ~{plans_count}")

# When was the latest pattern created/updated?
if latest_pat_ts:
    age_hours = (now - latest_pat_ts).total_seconds() / 3600
    print(f"Latest pattern:     {latest_pat_ts} ({age_hours:.1f}h ago)")
    print(f"Patterns count:     {pat_count}")
    # Check checkpoints
    cps = q("SELECT pattern_key, last_episode_id_processed, sample_size FROM semantic_patterns WHERE active=true ORDER BY last_episode_id_processed DESC")
    for p in cps:
        print(f"  {p['pattern_key']}: checkpoint={p['last_episode_id_processed']}, sample={p['sample_size']}")
    
    # Estimate mining interval: if patterns updated in last 50 min (10 ticks), warm-up is active
    if age_hours < 0.83:
        mining_status = "ACTIVE (warm-up 10-tick interval detected)"
    elif age_hours < 4.2:
        mining_status = "ACTIVE (50-tick interval, post warm-up)"
    else:
        mining_status = "ACTIVE"
    print(f"WARMUP_MINING_STATUS = {mining_status}")
else:
    print("No patterns found.")
    # Check when mining last ran - look at when episodes were created vs pattern timestamps
    if pat_count == 0 and plans_count > 0:
        print("WARMUP_MINING_STATUS = INACTIVE (no patterns despite plans existing)")
    else:
        print("WARMUP_MINING_STATUS = INACTIVE (no patterns)")

# ==================================================================
# Section C — Attribution Context Verification
# ==================================================================
print()
print("=" * 70)
print("SECTION C: ATTRIBUTION CONTEXT VERIFICATION")
print("=" * 70)

# Get NEW episodes with real debate_verdict
new_eps = q("SELECT id, plan_id, action_type, debate_verdict FROM agent_episodes WHERE debate_verdict != 'unknown' ORDER BY ts DESC LIMIT 10")
print(f"Episodes with real debate_verdict: {len(new_eps)}")
for e in new_eps:
    print(f"  ep={e['id']} plan={e['plan_id']} action={e['action_type']} verdict={e['debate_verdict']}")

# Check attribution records
all_attr = q("SELECT * FROM memory_attributions ORDER BY ts DESC LIMIT 20")
print(f"\nTotal attribution records: {len(all_attr)}")

if all_attr:
    unknown_v = sum(1 for a in all_attr if a.get("debate_verdict") == "unknown")
    has_rules = sum(1 for a in all_attr if int(a.get("memory_rules_count", 0)) > 0)
    has_conf = sum(1 for a in all_attr if float(a.get("memory_confidence", 0)) > 0)
    
    print(f"  debate_verdict=unknown:       {unknown_v}")
    print(f"  memory_rules_count>0:         {has_rules}")
    print(f"  memory_confidence>0:          {has_conf}")
    
    # Show sample records
    print("\n  Sample records (last 5 with real verdict):")
    real = [a for a in all_attr if a.get("debate_verdict") != "unknown"][:5]
    for a in real:
        print(f"    ep={a['episode_id']} verdict={a['debate_verdict']} rules={a['memory_rules_count']} "
              f"conf={a['memory_confidence']} quality={a['outcome_quality']} contrib={a['memory_contribution_score']}")
    
    if unknown_v < len(all_attr) / 2:
        ctx_status = "GOOD"
    elif len(all_attr) > 0:
        ctx_status = "WARNING"
    else:
        ctx_status = "BROKEN"
else:
    ctx_status = "BROKEN"

print(f"\nATTRIBUTION_CONTEXT_STATUS = {ctx_status}")

# ==================================================================
# Section D — Procedural Memory Verification
# ==================================================================
print()
print("=" * 70)
print("SECTION D: PROCEDURAL MEMORY VERIFICATION")
print("=" * 70)

inj = q("SELECT * FROM memory_injections ORDER BY ts DESC")
print(f"Total injections: {len(inj)}")

if inj:
    rule_counts = [int(i.get("rule_count", 0)) for i in inj]
    print(f"Avg rules/injection: {sum(rule_counts) / len(rule_counts):.1f}")
    print(f"Max rules: {max(rule_counts)}")
    print(f"Min rules: {min(rule_counts)}")
    
    # Show latest injections with pattern details
    print("\n  Latest injections:")
    for i in inj[:5]:
        rules_json = i.get("rules_json", "[]")
        if isinstance(rules_json, str):
            try:
                rules = json.loads(rules_json)
            except Exception:
                rules = []
        else:
            rules = rules_json or []
        print(f"  #{i['id']}: plan={i['plan_id']} rules={len(rules)}")
        for r in rules[:2]:
            print(f"    - {r.get('pattern_key', '?')} sr={r.get('success_rate', 0)} vs={r.get('validation_score', 0)}")
    
    pm_status = "ACTIVE"
else:
    pm_status = "INACTIVE"

print(f"\nPROCEDURAL_MEMORY_STATUS = {pm_status}")

# ==================================================================
# Section E — Attribution Lifecycle Verification
# ==================================================================
print()
print("=" * 70)
print("SECTION E: ATTRIBUTION LIFECYCLE VERIFICATION")
print("=" * 70)

# Get episode count
total_eps = q("SELECT COUNT(*) as cnt FROM agent_episodes")[0]["cnt"]
total_attr = len(all_attr)

print(f"Total episodes:      {total_eps}")
print(f"Total attributions:  {total_attr}")
if total_eps > 0:
    print(f"Ratio (attr/episode): {round(total_attr / total_eps, 2)} (1.0 = ideal)")

# Check for duplicates
cur.execute(
    "SELECT episode_id, COUNT(*) as cnt FROM memory_attributions "
    "GROUP BY episode_id HAVING COUNT(*) > 1"
)
dupes = cur.fetchall()
print(f"Duplicate episode_id in attributions: {len(dupes)}")
if dupes:
    for ep_id, cnt in dupes:
        print(f"  episode_id={ep_id}: {cnt} records")

# Check lifecycle states
if all_attr:
    pending = sum(1 for a in all_attr if a.get("outcome_quality") == "pending")
    resolved_attr = len(all_attr) - pending
    print(f"Pending attributions:    {pending}")
    print(f"Resolved attributions:   {resolved_attr}")

    if len(dupes) == 0 and total_attr <= total_eps + 2:
        lifecycle_status = "GOOD"
    elif len(dupes) == 0:
        lifecycle_status = "WARNING"
    else:
        lifecycle_status = "BROKEN"
else:
    lifecycle_status = "BROKEN" if total_eps > 0 else "GOOD (no episodes yet)"

print(f"ATTRIBUTION_LIFECYCLE_STATUS = {lifecycle_status}")

# ==================================================================
# Section F — First Pattern Audit
# ==================================================================
print()
print("=" * 70)
print("SECTION F: FIRST PATTERN AUDIT")
print("=" * 70)

patterns = q("SELECT * FROM semantic_patterns ORDER BY first_seen ASC")
print(f"Total patterns: {len(patterns)}")

if patterns:
    first = patterns[0]
    print(f"First pattern:")
    print(f"  Timestamp:      {first.get('first_seen')}")
    print(f"  Pattern key:    {first['pattern_key']}")
    print(f"  Sample size:    {first['sample_size']}")
    print(f"  Confidence:     {first['confidence_score']}")
    print(f"  Success rate:   {first['success_rate']}")
    print(f"  Validated:      {first['validated']}")
    print(f"  Validation scr: {first.get('validation_score', 0.0)}")
    print(f"  Checkpoint:     {first.get('last_episode_id_processed', 0)}")
    
    # Show all patterns
    print("\nAll patterns:")
    for p in patterns:
        print(f"  {p['pattern_key']}: ss={p['sample_size']} sr={p['success_rate']} "
              f"conf={p['confidence_score']} valid={p.get('validated')} "
              f"cp={p.get('last_episode_id_processed')}")
    
    fp_status = "OBSERVED"
else:
    # Explain why not
    total_resolved = q("SELECT COUNT(*) as cnt FROM agent_episodes WHERE CAST(resolved AS integer)=1")[0]["cnt"]
    print(f"Resolved episodes: {total_resolved}")
    print(f"MIN_SAMPLE_SIZE required: 5")
    
    # Check by action_type
    if total_resolved >= 5:
        print("Sufficient resolved episodes exist. Possible reasons patterns not created:")
        print("  1. Agent not restarted with new warm-up mining code")
        print("  2. Not enough episodes per (action, survival_mode) group")
        print("  3. Mining interval not yet reached")
        
        groups = q("SELECT action_type, survival_mode, COUNT(*) as cnt FROM agent_episodes WHERE CAST(resolved AS integer)=1 GROUP BY action_type, survival_mode")
        for g in groups:
            print(f"  Group {g['action_type']}+{g['survival_mode']}: {g['cnt']} episodes {'✅' if g['cnt'] >= 5 else '❌ needs ' + str(5 - g['cnt']) + ' more'}")
    else:
        print(f"Insufficient resolved episodes: {total_resolved}/5 needed per group.")
    
    fp_status = "NOT_OBSERVED"

print(f"\nFIRST_PATTERN_STATUS = {fp_status}")

# ==================================================================
# Section G — First Learning Cycle Status
# ==================================================================
print()
print("=" * 70)
print("SECTION G: FIRST LEARNING CYCLE STATUS")
print("=" * 70)

cycle_steps = {
    "Resolved Episode": q("SELECT COUNT(*) as cnt FROM agent_episodes WHERE CAST(resolved AS integer)=1")[0]["cnt"] > 0,
    "Pattern Created": pat_count > 0,
    "Pattern Validated": len([p for p in patterns if p.get("validated") in (True, 1)]) > 0 if patterns else False,
    "Memory Injection": inj_count > 0,
    "Attribution Recorded": attr_count > 0,
    "Memory Advice": adv_count > 0,
}

for step, ok in cycle_steps.items():
    print(f"  {step:<20s}: {'✅ YES' if ok else '❌ NO'}")

completed = sum(1 for v in cycle_steps.values() if v)
total = len(cycle_steps)

if completed == total:
    cycle_status = "COMPLETE"
elif completed >= 3:
    cycle_status = "PARTIAL"
elif completed >= 1:
    cycle_status = "PARTIAL (early)"
else:
    cycle_status = "NOT_OBSERVED"

print(f"\nFIRST_LEARNING_CYCLE = {cycle_status} ({completed}/{total} steps)")

# ==================================================================
# Section H — Runtime Readiness
# ==================================================================
print()
print("=" * 70)
print("SECTION H: RUNTIME READINESS")
print("=" * 70)

# Calculate hours since restart - use latest plan timestamp
if latest_plan_ts:
    hours_since_restart = (now - latest_plan_ts).total_seconds() / 3600
else:
    hours_since_restart = 0

# Episodes generated
eps_24h = q("SELECT COUNT(*) as cnt FROM agent_episodes WHERE ts >= NOW() - INTERVAL '24 hours'")[0]["cnt"]
eps_since_restart = eps_24h  # approximation

# Resolved since restart
resolved_since = q("SELECT COUNT(*) as cnt FROM agent_episodes WHERE CAST(resolved AS integer)=1 AND ts >= NOW() - INTERVAL '24 hours'")[0]["cnt"]

# Patterns generated since restart
if patterns and len(patterns) > 0:
    pat_since = len(patterns)
else:
    pat_since = 0

# Attributions generated since restart
if all_attr and len(all_attr) > 0:
    attr_since = len(all_attr)
else:
    attr_since = 0

# Injections since restart
if inj and len(inj) > 0:
    inj_since = len(inj)
else:
    inj_since = 0

print(f"Hours since latest plan:     {hours_since_restart:.1f}h")
print(f"Episodes in last 24h:        {eps_24h}")
print(f"Resolved episodes (recent):  {resolved_since}")
print(f"Patterns:                    {pat_since}")
print(f"Attributions:                {attr_since}")
print(f"Memory injections:           {inj_since}")
print(f"Memory advice:               {adv_count}")

# Calculate health score (0-100)
score = 0
score += min(25, eps_since_restart * 2)  # 12+ episodes = 25
score += min(25, pat_since * 5)           # 5 patterns = 25
score += min(15, resolved_since * 3)      # 5 resolved = 15
score += min(15, attr_since * 3)          # 5 attributions = 15
score += min(10, inj_since * 2)           # 5 injections = 10
score += min(10, adv_count * 2)           # 5 advice = 10
health_score = round(score, 1)

print(f"\nPHASE7_RUNTIME_HEALTH = {health_score}/100")

# READY_FOR_PHASE_8?
ready = (
    health_score >= 50
    and cycle_steps["Resolved Episode"]
    and cycle_steps["Pattern Created"]
    and cycle_steps["Pattern Validated"]
    and cycle_steps["Memory Injection"]
    and cycle_steps["Attribution Recorded"]
    and cycle_steps["Memory Advice"]
)

print(f"\nREADY_FOR_PHASE_8 = {'TRUE' if ready else 'FALSE'}")

if not ready:
    blockers = []
    if not cycle_steps["Resolved Episode"]:
        blockers.append("No resolved episodes (0/1)")
    if not cycle_steps["Pattern Created"]:
        blockers.append("No patterns created")
    if not cycle_steps["Pattern Validated"]:
        blockers.append("No validated patterns")
    if not cycle_steps["Memory Injection"]:
        blockers.append("No memory injections (ProceduralMemory.inject_for_plan not executing)")
    if not cycle_steps["Attribution Recorded"]:
        blockers.append("No attribution records")
    if not cycle_steps["Memory Advice"]:
        blockers.append("No memory advice records")
    if health_score < 50:
        blockers.append(f"Health score too low ({health_score}/50)")

    print("Remaining blockers:")
    for b in blockers:
        print(f"  - {b}")

    # Estimate remaining
    if not cycle_steps["Pattern Created"]:
        # Need ~5 resolved episodes per group THEN mining interval
        eps_needed = max(0, 5 - resolved_since)
        hours_needed = eps_needed * 0.5  # ~30 min per resolved episode
        print(f"\nEstimated remaining: {hours_needed:.1f}h for first pattern")
    elif not cycle_steps["Attribution Recorded"]:
        print(f"\nEstimated remaining: ~6h for attribution resolution cycle")
    else:
        eps_needed = max(0, 50 - total_eps)
        hours_needed = eps_needed * 0.5
        print(f"\nEstimated remaining: {hours_needed:.1f}h ({eps_needed} more episodes)")

conn.close()
print()
print("Audit complete. No code changes made.")