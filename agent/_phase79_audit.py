"""
Phase 7.9 — First Learning Cycle Audit
Audit only — no code modifications.
"""
import json
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

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


# ==================================================================
# Section A — Episode Audit
# ==================================================================
print("=" * 60)
print("SECTION A: EPISODE AUDIT")
print("=" * 60)

eps = q("SELECT * FROM agent_episodes ORDER BY ts")
total_eps = len(eps)
resolved = sum(1 for e in eps if e.get("resolved") in (True, 1))
unresolved = total_eps - resolved

print(f"Total episodes:      {total_eps}")
print(f"Resolved:            {resolved}")
print(f"Unresolved:          {unresolved}")
print(f"Resolution rate:     {round(resolved / max(1, total_eps) * 100, 1)}%")

if eps:
    from collections import Counter

    actions = Counter(e["action_type"] for e in eps)
    print(f"Action distribution: {dict(actions)}")

    modes = Counter(e.get("survival_mode", "unknown") for e in eps)
    print(f"Survival modes:      {dict(modes)}")

    consensus = Counter(e.get("analyst_consensus", "unknown") for e in eps)
    print(f"Analyst consensus:   {dict(consensus)}")

    verdicts = Counter(e.get("debate_verdict", "unknown") for e in eps)
    print(f"Debate verdicts:     {dict(verdicts)}")

    # Average episode age (hours)
    from datetime import datetime, timezone

    now = datetime.now(tz=timezone.utc)
    ages = []
    for e in eps:
        try:
            ts_str = str(e.get("ts", "")).replace("Z", "+00:00").replace(" ", "T")
            ts = datetime.fromisoformat(ts_str)
            ages.append((now - ts).total_seconds() / 3600)
        except Exception:
            pass
    if ages:
        print(f"Avg episode age:     {sum(ages) / len(ages):.1f}h")
        print(f"Min age:             {min(ages):.1f}h")
        print(f"Max age:             {max(ages):.1f}h")

ep_health = "GOOD" if resolved > 0 else ("WARNING" if total_eps > 0 else "BROKEN")
print(f"EPISODIC_MEMORY_HEALTH = {ep_health}")

# ==================================================================
# Section B — Pattern Mining Audit
# ==================================================================
print()
print("=" * 60)
print("SECTION B: PATTERN MINING AUDIT")
print("=" * 60)

patterns = q("SELECT * FROM semantic_patterns")
print(f"Total patterns:    {len(patterns)}")
active = [p for p in patterns if p.get("active") in (True, 1)]
inactive = [p for p in patterns if p.get("active") in (False, 0)]
print(f"Active patterns:   {len(active)}")
print(f"Inactive patterns: {len(inactive)}")

if active:
    avg_size = sum(int(p.get("sample_size", 0)) for p in active) / len(active)
    avg_conf = sum(float(p.get("confidence_score", 0)) for p in active) / len(active)
    print(f"Avg sample size:         {avg_size:.1f}")
    print(f"Avg confidence score:    {avg_conf:.4f}")

    by_success = sorted(
        active, key=lambda x: float(x.get("success_rate", 0)), reverse=True
    )
    best = by_success[0]
    print(f"Strongest positive:      {best['pattern_key']} sr={best['success_rate']} conf={best['confidence_score']}")
    worst = by_success[-1]
    print(f"Strongest negative:      {worst['pattern_key']} sr={worst['success_rate']} conf={worst['confidence_score']}")

    # Checkpoints
    with_cp = sum(
        1 for p in active if int(p.get("last_episode_id_processed", 0)) > 0
    )
    max_cp = (
        max(int(p.get("last_episode_id_processed", 0)) for p in active)
        if active
        else 0
    )
    print(f"Patterns with checkpoints: {with_cp}/{len(active)}")
    print(f"Max checkpoint:            {max_cp}")

    # Duplicate / coverage
    total_sample = sum(int(p.get("sample_size", 0)) for p in active)
    print(f"Total sample across patterns: {total_sample}")
    print(f"Total resolved episodes:      {resolved}")
    if resolved > 0:
        ratio = round(total_sample / resolved, 2)
        print(f"Coverage ratio:               {ratio}  {'OK' if ratio <= 1.5 else 'DUPLICATION RISK'}")
else:
    print("No active patterns found.")

sm_health = "GOOD" if len(active) >= 5 else ("WARNING" if len(active) > 0 else "BROKEN")
print(f"SEMANTIC_MEMORY_HEALTH = {sm_health}")

# ==================================================================
# Section C — Pattern Validation Audit
# ==================================================================
print()
print("=" * 60)
print("SECTION C: PATTERN VALIDATION AUDIT")
print("=" * 60)

validated = [p for p in patterns if p.get("validated") in (True, 1)]
rejected = [p for p in patterns if p.get("validated") in (False, 0) and p.get("active") in (True, 1)]
print(f"Total validated patterns: {len(validated)}")
print(f"Total rejected patterns:  {len(rejected)}")
print(f"Validation rate:          {round(len(validated) / max(1, len(patterns)) * 100, 1)}%")

if validated:
    avg_vscore = sum(float(p.get("validation_score", 0)) for p in validated) / len(validated)
    vscores = sorted(float(p.get("validation_score", 0)) for p in validated)
    print(f"Avg validation score:  {avg_vscore:.4f}")
    print(f"Highest validation:    {vscores[-1]:.4f}")
    print(f"Lowest validation:     {vscores[0]:.4f}")

    # Check rules enforced
    violations = 0
    for p in validated:
        ss = int(p.get("sample_size", 0))
        cs = float(p.get("confidence_score", 0))
        sr = float(p.get("success_rate", 0))
        if not (ss >= 10 and cs >= 0.60 and sr >= 0.70):
            violations += 1
            print(f"  RULE VIOLATION: {p['pattern_key']} ss={ss} cs={cs} sr={sr}")
    print(f"Validation rule violations: {violations}")

pv_health = "GOOD" if len(validated) >= 3 else ("WARNING" if len(validated) > 0 else "BROKEN")
print(f"PATTERN_VALIDATION_HEALTH = {pv_health}")

# ==================================================================
# Section D — Procedural Memory Audit
# ==================================================================
print()
print("=" * 60)
print("SECTION D: PROCEDURAL MEMORY AUDIT")
print("=" * 60)

inj = q("SELECT * FROM memory_injections ORDER BY ts")
print(f"Total injections: {len(inj)}")

if inj:
    rule_counts = [int(i.get("rule_count", 0)) for i in inj]
    print(f"Avg rules/injection: {sum(rule_counts) / len(rule_counts):.1f}")
    print(f"Max rules:           {max(rule_counts)}")
    print(f"Min rules:           {min(rule_counts)}")
    planner_used = sum(
        1 for i in inj if i.get("planner_used_memory") in (True, 1)
    )
    print(f"planner_used_memory: {planner_used} (MUST be 0)")
    # Check if rules originate from validated patterns
    for i in inj:
        rules_json = i.get("rules_json", "[]")
        if isinstance(rules_json, str):
            try:
                rules = json.loads(rules_json)
            except Exception:
                rules = []
        else:
            rules = rules_json or []
        if len(rules) > 0:
            print(f"  Injection #{i['id']}: {len(rules)} rules with pattern keys")
            for r in rules[:3]:
                print(f"    - {r.get('pattern_key', '?')} sr={r.get('success_rate', 0)}")
            if len(rules) > 3:
                print(f"    ... and {len(rules) - 3} more")
else:
    print("No memory injections found.")

pm_health = "GOOD" if len(inj) >= 5 else ("WARNING" if len(inj) > 0 else "BROKEN")
print(f"PROCEDURAL_MEMORY_HEALTH = {pm_health}")

# ==================================================================
# Section E — Memory Advice Audit
# ==================================================================
print()
print("=" * 60)
print("SECTION E: MEMORY ADVICE AUDIT")
print("=" * 60)

adv = q("SELECT * FROM memory_advice ORDER BY ts")
print(f"Total advice records: {len(adv)}")

if adv:
    # difference_detected is INTEGER in PG (0/1)
    agree = sum(1 for a in adv if a.get("difference_detected") in (False, 0))
    disagree = len(adv) - agree
    print(f"Agreements:   {agree}")
    print(f"Disagreements: {disagree}")
    print(f"Agreement rate: {round(agree / max(1, len(adv)) * 100, 1)}%")
    avg_conf = sum(float(a.get("confidence", 0)) for a in adv) / len(adv)
    print(f"Avg confidence: {avg_conf:.4f}")

ma_health = "GOOD" if len(adv) >= 5 else ("WARNING" if len(adv) > 0 else "BROKEN")
print(f"MEMORY_ADVISOR_HEALTH = {ma_health}")

# ==================================================================
# Section F — Attribution Audit
# ==================================================================
print()
print("=" * 60)
print("SECTION F: ATTRIBUTION AUDIT")
print("=" * 60)

attr = q("SELECT * FROM memory_attributions ORDER BY ts")
print(f"Total attribution records: {len(attr)}")

if attr:
    pending = sum(1 for a in attr if a.get("outcome_quality") == "pending")
    pos = sum(1 for a in attr if a.get("outcome_quality") == "positive")
    neg = sum(1 for a in attr if a.get("outcome_quality") == "negative")
    neu = sum(1 for a in attr if a.get("outcome_quality") == "neutral")
    print(f"Pending:   {pending}")
    print(f"Positive:  {pos}")
    print(f"Negative:  {neg}")
    print(f"Neutral:   {neu}")

    contribs = [float(a.get("memory_contribution_score", 0)) for a in attr]
    print(f"Avg contribution: {sum(contribs) / len(contribs):.4f}")
    print(f"Max contribution: {max(contribs):.4f}")
    print(f"Min contribution: {min(contribs):.4f}")

    # 1:1 episode check
    cur.execute(
        """SELECT episode_id, COUNT(*) as cnt
           FROM memory_attributions
           GROUP BY episode_id
           HAVING COUNT(*) > 1"""
    )
    dupes = cur.fetchall()
    print(f"Duplicate attributions (same episode_id): {len(dupes)}")
    if dupes:
        for ep_id_row, cnt in dupes:
            print(f"  episode_id={ep_id_row}: {cnt} records")

    # Debate verdict audit
    unknown_v = sum(1 for a in attr if a.get("debate_verdict") == "unknown")
    print(f"Attributions with debate_verdict=unknown: {unknown_v}")

    # Memory context audit
    has_rules = sum(1 for a in attr if int(a.get("memory_rules_count", 0)) > 0)
    has_conf = sum(1 for a in attr if float(a.get("memory_confidence", 0)) > 0)
    print(f"Attributions with memory_rules_count>0: {has_rules}")
    print(f"Attributions with memory_confidence>0:   {has_conf}")

    # Episode count vs attribution count
    print(f"Episode count:     {total_eps}")
    print(f"Attribution count: {len(attr)}")
    print(f"Ratio:             {round(len(attr) / max(1, total_eps), 2)} (should be ~1:1)")

    # Show some detail
    print()
    print("Sample attribution records (last 5):")
    for a in attr[-5:]:
        print(
            f"  ep={a['episode_id']} planner={a['planner_decision']} "
            f"verdict={a['debate_verdict']} rules={a['memory_rules_count']} "
            f"conf={a['memory_confidence']} quality={a['outcome_quality']} "
            f"contrib={a['memory_contribution_score']}"
        )
else:
    print("No attribution records found.")

ath_health = (
    "GOOD"
    if len(attr) >= 5 and (len(attr) / max(1, total_eps)) >= 0.5
    else ("WARNING" if len(attr) > 0 else "BROKEN")
)
print(f"ATTRIBUTION_HEALTH = {ath_health}")

# ==================================================================
# Section G — First Learning Cycle
# ==================================================================
print()
print("=" * 60)
print("SECTION G: FIRST LEARNING CYCLE")
print("=" * 60)

cycle_steps = {
    "Resolved Episode": resolved > 0,
    "Pattern Created": len(active) > 0,
    "Pattern Validated": len(validated) > 0,
    "Memory Injection": len(inj) > 0,
    "Memory Advice": len(adv) > 0,
    "Attribution Recorded": len(attr) > 0,
}

for step, ok in cycle_steps.items():
    print(f"  {step:<20s}: {'YES' if ok else 'NO'}")

completed = sum(1 for v in cycle_steps.values() if v)
total = len(cycle_steps)

if completed == total:
    cycle_status = "COMPLETE"
elif completed >= 3:
    cycle_status = "PARTIAL"
else:
    cycle_status = "NOT_OBSERVED"

print(f"FIRST_LEARNING_CYCLE = {cycle_status} ({completed}/{total} steps)")

# ==================================================================
# Section H — Statistical Sufficiency
# ==================================================================
print()
print("=" * 60)
print("SECTION H: STATISTICAL SUFFICIENCY")
print("=" * 60)

print(f"{'Metric':<24s} {'Current':<10s} {'Minimum':<10s} {'Status':<8s}")
print("-" * 52)

thresholds = [
    ("Resolved Episodes", resolved, 100),
    ("Validated Patterns", len(validated), 5),
    ("Advice Records", len(adv), 20),
    ("Attribution Records", len(attr), 20),
]

all_sufficient = True
for name, cur_val, min_val in thresholds:
    status = "OK" if cur_val >= min_val else "LOW"
    if status == "LOW":
        all_sufficient = False
    print(f"{name:<24s} {cur_val:<10d} {min_val:<10d} {status:<8s}")

if attr:
    avg_c = sum(float(a.get("memory_contribution_score", 0)) for a in attr) / max(
        1, len(attr)
    )
    c_status = "OK" if avg_c > 0.30 else "LOW"
    if c_status == "LOW":
        all_sufficient = False
    print(f"{'Avg Contribution':<24s} {avg_c:<10.4f} {'>0.30':<10s} {c_status:<8s}")
else:
    print(f"{'Avg Contribution':<24s} {'N/A':<10s} {'>0.30':<10s} {'LOW':<8s}")
    all_sufficient = False

ds_status = "SUFFICIENT" if all_sufficient else ("PARTIAL" if resolved >= 20 else "INSUFFICIENT")
print(f"DATASET_SUFFICIENCY = {ds_status}")

# ==================================================================
# Section I — Memory Readiness Score
# ==================================================================
print()
print("=" * 60)
print("SECTION I: MEMORY READINESS SCORE")
print("=" * 60)

# Weights + scores on 0-100
def layer_score(name, ok_count, total_count, weight):
    if total_count == 0:
        return 0
    pct = min(100, ok_count / total_count * 100)
    return pct * weight


scores = {}

# Episodic (25%): resolved/total ratio * 100
ep_score = min(100, (resolved / max(1, total_eps)) * 100) if total_eps > 0 else 0
scores["Episodic (25%)"] = ep_score * 0.25

# Semantic (25%): patterns that exist and have quality
sm_raw = min(100, len(active) * 20)  # 5 patterns = 100
scores["Semantic (25%)"] = sm_raw * 0.25

# Validation (15%): validated/total ratio * 100
pv_raw = min(100, (len(validated) / max(1, len(patterns))) * 100) if patterns else 0
scores["Validation (15%)"] = pv_raw * 0.15

# Procedural (15%): injections exist with rules
pm_raw = min(100, (len(inj) / 5) * 100) if inj else 0
scores["Procedural (15%)"] = pm_raw * 0.15

# Advice (10%): advice records exist
ma_raw = min(100, (len(adv) / 5) * 100) if adv else 0
scores["Advice (10%)"] = ma_raw * 0.10

# Attribution (10%): records with real data
if attr:
    has_data = sum(
        1
        for a in attr
        if a.get("debate_verdict") != "unknown"
        and int(a.get("memory_rules_count", 0)) > 0
    )
    ath_raw = min(100, (has_data / max(1, len(attr))) * 100)
else:
    ath_raw = 0
scores["Attribution (10%)"] = ath_raw * 0.10

for layer, weighted in scores.items():
    print(f"  {layer:<20s} = {weighted:.1f}")

total_score = round(sum(scores.values()), 1)
print(f"\n  MEMORY_READINESS_SCORE = {total_score}/100")
print(f"  Assessment: {'LOW' if total_score < 30 else 'MEDIUM' if total_score < 70 else 'HIGH'}")

# ==================================================================
# Section J — Final Verdict
# ==================================================================
print()
print("=" * 60)
print("SECTION J: FINAL VERDICT")
print("=" * 60)

ready = (
    total_score >= 50
    and resolved >= 50
    and len(validated) >= 3
    and len(attr) >= 10
    and len(inj) >= 5
)

if ready:
    print("READY_FOR_PHASE_8 = TRUE")
    print()
    print("Recommendations:")
    print("  - Activate Phase 8 with 5% memory influence (conservative start)")
    print("  - Monitor attribution contribution scores weekly")
    print("  - Rollback if >2 consecutive negative attribution cycles")
    print("  - Increase memory influence to 10% after 50 validated patterns")
else:
    print("READY_FOR_PHASE_8 = FALSE")
    print()

    blockers = []
    if resolved < 50:
        blockers.append(f"Resolved episodes: {resolved}/50")
    if len(validated) < 3:
        blockers.append(f"Validated patterns: {len(validated)}/3")
    if len(attr) < 10:
        blockers.append(f"Attribution records: {len(attr)}/10")
    if len(inj) < 5:
        blockers.append(f"Memory injections: {len(inj)}/5")
    if total_score < 50:
        blockers.append(f"Memory readiness score: {total_score}/50")

    print("Remaining Blockers:")
    for b in blockers:
        print(f"  - {b}")

    if resolved > 0:
        # Estimate additional runtime
        eps_needed = max(0, 50 - resolved)
        patterns_needed = max(0, 3 - len(validated))
        attr_needed = max(0, 10 - len(attr))

        # With 5-min loop, ~12 resolved per day (6h resolution window)
        days_episodes = eps_needed / 12 if eps_needed > 0 else 0
        # With warm-up mining, ~5 patterns per 50 loops (4h)
        days_patterns = patterns_needed * 4 / 24 if patterns_needed > 0 else 0
        # Attribution tracks episodes, same timing
        days_attr = attr_needed / 12 if attr_needed > 0 else 0

        est_days = max(days_episodes, days_patterns, days_attr)
        print(f"\nEstimated additional runtime needed: {est_days:.1f} days")
        print(f"Estimated additional resolved episodes: {eps_needed}")

conn.close()
print()
print("Audit complete. No code changes made.")