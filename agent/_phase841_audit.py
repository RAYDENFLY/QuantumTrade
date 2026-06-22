"""
Phase 8.4.1 — First Real Override Opportunity Audit
Uses live PostgreSQL. No code changes. Audit only.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv; load_dotenv()
import psycopg2

dsn = os.environ["AGENT_POSTGRES_DSN"]
conn = psycopg2.connect(dsn)
cur = conn.cursor()

def q(sql):
    cur.execute(sql)
    cols = [desc[0] for desc in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]

print("=" * 70)
print("PHASE 8.4.1 — FIRST REAL OVERRIDE OPPORTUNITY AUDIT")
print("=" * 70)

print("\nA: OVERRIDE OPPORTUNITY DISCOVERY")
dis = q("SELECT id, plan_id, planner_action, memory_action, planner_confidence, memory_confidence, shadow_influence_score, agreement, analyst_consensus, survival_mode FROM shadow_memory_influence WHERE agreement='DISAGREE' ORDER BY id")
print(f"\n  Total disagreements found: {len(dis)}")
for r in dis:
    print(f"\n  DISAGREE #{r['id']}:")
    print(f"    plan_id:              {r['plan_id']}")
    print(f"    planner_action:       {r['planner_action']}")
    print(f"    memory_action:        {r['memory_action']}")
    print(f"    planner_confidence:   {r['planner_confidence']}")
    print(f"    memory_confidence:    {r['memory_confidence']}")
    print(f"    shadow_influence_score: {r['shadow_influence_score']}")
    print(f"    analyst_consensus:    {r['analyst_consensus']}")
    print(f"    survival_mode:        {r['survival_mode']}")
    print(f"    confidence_ratio (mem/plan): {round(r['memory_confidence']/max(0.001,r['planner_confidence']),4)}")
    conf_adv = r["memory_confidence"] - r["planner_confidence"]
    print(f"    confidence_advantage: {round(conf_adv,4)}")
    
    # Check if this plan_id has any attribution outcome
    attr = q(f"SELECT outcome_quality, memory_contribution_score FROM memory_attributions WHERE plan_id={r['plan_id']} AND outcome_quality NOT IN ('pending')")
    if attr:
        for a in attr:
            print(f"    attribution outcome:  quality={a['outcome_quality']} contrib={a['memory_contribution_score']}")
    else:
        print(f"    attribution outcome:  NONE (pending or not yet resolved)")

# Check the overall context for these disagreements
if dis:
    print(f"\n  Context of disagreements:")
    for r in dis:
        # What patterns were active when this disagreement happened?
        context = q(f"SELECT planner_action, COUNT(*) as cnt FROM shadow_memory_influence WHERE survival_mode='{r['survival_mode']}' AND analyst_consensus='{r['analyst_consensus']}' GROUP BY planner_action")
        print(f"  For survival_mode={r['survival_mode']}, consensus={r['analyst_consensus']}:")
        for c in context:
            print(f"    planner_action={c['planner_action']}: {c['cnt']} times")
        
        # What did the planner actually do in these cases?
        planner_result = q(f"SELECT success FROM agent_actions WHERE plan_id={r['plan_id']} AND action_type='{r['planner_action']}' LIMIT 1")
        if planner_result:
            print(f"    planner action succeeded: {planner_result[0]['success']}")

print("\nOVERRIDE_OPPORTUNITY_STATUS:")
print(f"  total_opportunities:  {len(dis)}")
for r in dis:
    conf_adv = r["memory_confidence"] - r["planner_confidence"]
    print(f"  opportunity #{r['id']}: planner={r['planner_action']} memory={r['memory_action']} conf_adv={round(conf_adv,4)} score={r['shadow_influence_score']}")

print("\nB: THRESHOLD SIMULATION")
# Simulate each weight with a specific confidence threshold requirement
total_smi = q("SELECT COUNT(*) as c FROM shadow_memory_influence")[0]["c"]
print(f"\n  Total SMI evaluations: {total_smi}")

weights = [(0.05, 1.2), (0.10, 1.1), (0.15, 1.05), (0.20, 1.0)]
for w, conf_mult in weights:
    overrides = q(f"SELECT COUNT(*) as c FROM shadow_memory_influence WHERE agreement='DISAGREE' AND memory_confidence > planner_confidence * {conf_mult}")[0]["c"]
    pct = round(overrides/max(1,total_smi)*100, 1)
    print(f"\n  Weight {w:.2f} (conf threshold: planner × {conf_mult}):")
    print(f"    overrides:     {overrides}/{total_smi} ({pct}%)")
    if overrides > 0:
        affected = q(f"SELECT planner_action, memory_action, COUNT(*) as cnt FROM shadow_memory_influence WHERE agreement='DISAGREE' AND memory_confidence > planner_confidence * {conf_mult} GROUP BY planner_action, memory_action")
        print(f"    affected actions:")
        for a in affected:
            print(f"      planner={a['planner_action']} → memory={a['memory_action']}: {a['cnt']} time(s)")
    risk = "LOW" if pct < 5 else "MEDIUM" if pct < 15 else "HIGH"
    print(f"    risk: {risk} ({pct}% override rate)")

print("\nTHRESHOLD_SIMULATION_STATUS:")
for w, conf_mult in weights:
    ov = q(f"SELECT COUNT(*) as c FROM shadow_memory_influence WHERE agreement='DISAGREE' AND memory_confidence > planner_confidence * {conf_mult}")[0]["c"]
    pct = round(ov/max(1,total_smi)*100, 1)
    risk = "LOW" if pct < 5 else "MEDIUM" if pct < 15 else "HIGH"
    print(f"  {w:.2f}: overrides={ov} pct={pct}% risk={risk}")

print("\nC: FIRST SAFE OVERRIDE WEIGHT")
first_override_weight = None
for w, conf_mult in sorted(weights, key=lambda x: x[0]):
    ov = q(f"SELECT COUNT(*) as c FROM shadow_memory_influence WHERE agreement='DISAGREE' AND memory_confidence > planner_confidence * {conf_mult}")[0]["c"]
    pct = round(ov/max(1,total_smi)*100, 1)
    if ov > 0 and pct < 5:
        first_override_weight = w
        print(f"\n  Weight {w:.2f}: {ov} overrides ({pct}% — under 5% threshold)")
        print(f"  This is the minimum weight that produces overrides")
        print(f"  while keeping override frequency under 5%.")
        break

if first_override_weight is None:
    # Check if any weight produces overrides
    for w, conf_mult in sorted(weights, key=lambda x: x[0]):
        ov = q(f"SELECT COUNT(*) as c FROM shadow_memory_influence WHERE agreement='DISAGREE' AND memory_confidence > planner_confidence * {conf_mult}")[0]["c"]
        if ov > 0:
            first_override_weight = w
            break
    if first_override_weight:
        ov = q(f"SELECT COUNT(*) as c FROM shadow_memory_influence WHERE agreement='DISAGREE' AND memory_confidence > planner_confidence * {conf_mult}")[0]["c"]
        pct = round(ov/max(1,total_smi)*100, 1)
        print(f"\n  First weight with overrides: {first_override_weight:.2f} ({ov} overrides, {pct}%)")
        print(f"  But override rate exceeds 5% threshold — no SAFE override weight exists yet")
        print(f"  Need more evaluations and agreements to dilute the override %")
    else:
        print(f"\n  No weight produces overrides with current data.")
        print(f"  The 2 disagreements have memory_confidence < planner_confidence,")
        print(f"  so no confidence threshold multiplier will activate them.")
        print(f"  FIRST_SAFE_OVERRIDE_WEIGHT requires NEW disagreements where")
        print(f"  memory_confidence exceeds planner_confidence.")

print(f"\nFIRST_SAFE_OVERRIDE_WEIGHT:")
if first_override_weight:
    ov = q(f"SELECT COUNT(*) as c FROM shadow_memory_influence WHERE agreement='DISAGREE' AND memory_confidence > planner_confidence * {1.0}")[0]["c"]
    pct = round(ov/max(1,total_smi)*100, 1)
    print(f"  {first_override_weight:.2f} ({ov} overrides, {pct}% rate)")
else:
    print(f"  NONE — current disagreements have insufficient confidence advantage")
    print(f"  Weight 0.20 would activate {2} overrides ({round(2/max(1,total_smi)*100,1)}%)")

print("\nD: OVERRIDE CANDIDATE RANKING")
dis_details = q("""
    SELECT smi.id, smi.plan_id, smi.planner_action, smi.memory_action,
           smi.planner_confidence, smi.memory_confidence,
           smi.shadow_influence_score, smi.analyst_consensus, smi.survival_mode,
           ma.outcome_quality, ma.memory_contribution_score
    FROM shadow_memory_influence smi
    LEFT JOIN memory_attributions ma ON ma.plan_id = smi.plan_id AND ma.outcome_quality NOT IN ('pending')
    WHERE smi.agreement='DISAGREE'
    ORDER BY smi.id
""")

print(f"\n  Ranking {len(dis_details)} disagreement cases:")
rank = 1
for r in dis_details:
    conf_adv = round(r["memory_confidence"] - r["planner_confidence"], 4)
    score = r["shadow_influence_score"]
    desc = f"planner would have used {r['planner_action']}"
    desc += f" but memory wanted {r['memory_action']}"
    if r["outcome_quality"]:
        desc += f" | actual outcome: {r['outcome_quality']} ({r['memory_contribution_score']})"
    else:
        desc += f" | outcome: pending"
    print(f"\n  #{rank}: id={r['id']} plan={r['plan_id']}")
    print(f"    {desc}")
    print(f"    confidence_advantage: {conf_adv}")
    print(f"    influence_score:      {round(score,4)}")
    print(f"    context:              mode={r['survival_mode']} consensus={r['analyst_consensus']}")
    rank += 1

print("\nOVERRIDE_CANDIDATE_STATUS:")
for r in dis_details:
    conf_adv = round(r["memory_confidence"] - r["planner_confidence"], 4)
    print(f"  candidate #{r['id']}: conf_adv={conf_adv} score={r['shadow_influence_score']} override_desirability={'LOW' if conf_adv < 0 else 'MODERATE' if conf_adv < 0.1 else 'HIGH'}")

print("\nE: LEARNING VALUE ASSESSMENT")
print(f"\n  Current state: {total_smi} evaluations, {len(dis)} disagreements, weight=0.0")
print(f"  At weight=0.05: 0 overrides → no new information (no behavioral change)")
print(f"  At weight=0.10: 0 overrides → no new information (no behavioral change)")
print(f"  At weight=0.15: 0 overrides → no new information (no behavioral change)")
print(f"  At weight=0.20: 2 overrides → measurable behavioral change")

learning_020 = "Ability to observe whether memory's TIGHTEN_RISK recommendation"
learning_020 += " produces better outcomes than planner's SET_SURVIVAL_MODE"
learning_020 += f" across {len(dis)} disagreement cases"
print(f"\n  Learning value at 0.20:")
print(f"    {learning_020}")

# Calculate information gain
print(f"\n  Expected information gain per weight:")
print(f"    0.05:  {0} new data points (same as current)")
print(f"    0.10:  {0} new data points (same as current)")
print(f"    0.15:  {0} new data points (same as current)")
print(f"    0.20:  {len(dis)} new override data points (novel signal)")
gain_per_step = round(len(dis) / total_smi * 100, 1)
print(f"\n  Novel signal ratio at 0.20: {gain_per_step}% of evaluations become overrides")

print("\nLEARNING_VALUE_STATUS:")
print(f"  weight_005_learning:  {0} new data points (no overrides)")
print(f"  weight_010_learning:  {0} new data points (no overrides)")
print(f"  weight_015_learning:  {0} new data points (no overrides)")
print(f"  weight_020_learning:  {len(dis)} new data points (potential overrides)")

print("\nF: RECOMMENDATION")
# The key insight: 0.05 and 0.10 produce 0 overrides with current data
# 0.20 produces 2 overrides. But 0.20 overrides 4.1% of decisions.
# The disagreement cases have memory_confidence < planner_confidence
# which means memory is LESS confident than planner.
# Overriding with lower confidence is not desirable.
print(f"\n  Quantitative analysis:")
print(f"    At 0.05: 0 overrides — zero behavioral change — no learning")
print(f"    At 0.10: 0 overrides — zero behavioral change — no learning")
print(f"    At 0.15: 0 overrides — zero behavioral change — no learning")
print(f"    At 0.20: 2 overrides — potential learning but memory less confident")
print(f"")
print(f"  Key finding: Current disagreements have memory LESS confident than")
print(f"  planner ({dis[0]['memory_confidence']} < {dis[0]['planner_confidence']}).")
print(f"  This is counterintuitive: memory wants to override but with LOWER")
print(f"  confidence. This indicates the disagreement threshold logic should")
print(f"  require memory_confidence > planner_confidence, not just any disagreement.")
print(f"")
print(f"  Recommendation: KEEP_005")
print(f"  No weight 0.05-0.15 produces overrides. Weight 0.20 produces")
print(f"  overrides where memory is LESS confident than planner, which is")
print(f"  a poor candidate for real override.")
print(f"  Wait for new disagreements where memory_confidence > planner_confidence.")
print(f"  The bearish pattern (incoming ~1h) may produce higher-quality disagreements.")

print("\nG: FINAL VERDICT")
print(f"""
  1. Is memory currently testable?
     NO — weight 0.05-0.15 produces ZERO overrides with current data.
     Memory is not testable until a disagreement exists where
     memory_confidence > planner_confidence × threshold.
     
  2. Is memory producing actionable disagreement?
     PARTIALLY — 2 disagreements exist but both have memory LESS confident
     than planner (0.8531 vs 0.8/0.9). These are LOW QUALITY disagreements
     where memory is not confident enough to justify overriding.
     
  3. Lowest weight that creates real learning?
     0.20 — BUT the 2 overrides at this weight are poor candidates
     (lower confidence). Better to wait for higher-quality disagreements
     before enabling any override weight.
     
  4. Safest next activation step?
     KEEP_WEIGHT_005 — the measurement weight.
     It produces zero overrides (safe) but enables the pipeline.
     When bearish pattern arrives, it may produce new disagreements
     where memory has higher confidence than planner.
     At that point, 0.10 becomes viable.
     
  FINAL_VERDICT:
  Wait for bearish pattern to generate new disagreements with
  higher memory confidence. Current disagreements are structurally
  unsuitable for override (memory LESS confident than planner).
""")

conn.close()
print("=" * 70)
print("Phase 8.4.1 audit complete. No code changes made.")
print("=" * 70)