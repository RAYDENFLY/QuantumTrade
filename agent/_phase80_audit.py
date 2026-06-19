"""Phase 8.0 — Memory Influence Readiness Audit. Live DB only. No code changes."""
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv; load_dotenv()
import psycopg2
from datetime import datetime, timezone
from collections import Counter

dsn = os.environ["AGENT_POSTGRES_DSN"]
conn = psycopg2.connect(dsn)
cur = conn.cursor()
now = datetime.now(timezone.utc)

def q(sql):
    cur.execute(sql)
    cols = [desc[0] for desc in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]

print("="*70)
print("PHASE 8.0 — MEMORY INFLUENCE READINESS AUDIT")
print("="*70)

# ===== SECTION A: Dataset Sufficiency =====
print("\n--- SECTION A: DATASET SUFFICIENCY ---")
eps = q("SELECT * FROM agent_episodes ORDER BY ts")
total_eps = len(eps)
resolved = sum(1 for e in eps if e.get("resolved") in (True, 1, "true"))
unresolved = total_eps - resolved
patterns = q("SELECT * FROM semantic_patterns")
validated = [p for p in patterns if p.get("validated") in (True, 1)]
inj = q("SELECT * FROM memory_injections")
adv = q("SELECT * FROM memory_advice")
attr = q("SELECT * FROM memory_attributions")
print(f"Total episodes:      {total_eps}")
print(f"Resolved:            {resolved}")
print(f"Unresolved:          {unresolved}")
print(f"Total patterns:      {len(patterns)}")
print(f"Validated patterns:  {len(validated)}")
print(f"Memory injections:   {len(inj)}")
print(f"Memory advice:       {len(adv)}")
print(f"Attribution records: {len(attr)}")
# Sufficiency buckets (0-100)
pts = 0
pts += min(25, resolved * 0.5)  # 50 eps = 25pt
pts += min(20, len(validated) * 6.67)  # 3 = 20pt
pts += min(20, len(inj) * 4)  # 5 = 20pt
pts += min(20, len(attr) * 2)  # 10 = 20pt
pts += min(15, len(adv) * 1.5)  # 10 = 15pt
dataset_score = pts
if dataset_score >= 70: ds_status = "HIGH"
elif dataset_score >= 35: ds_status = "MEDIUM"
else: ds_status = "LOW"
print(f"DATASET_SUFFICIENCY = {ds_status} ({dataset_score:.0f}/100)")

# ===== SECTION B: Pattern Diversity =====
print("\n--- SECTION B: PATTERN DIVERSITY ---")
if validated:
    print(f"\nAll validated patterns:")
    for p in validated:
        ojson = p.get("condition_json", "{}")
        if isinstance(ojson, str):
            try: cond = json.loads(ojson)
            except: cond = {}
        else: cond = ojson or {}
        print(f"  {p['pattern_key']}: ss={p['sample_size']} sr={p['success_rate']} "
              f"conf={p['confidence_score']} vscore={p.get('validation_score',0)} mode={cond.get('survival_mode','?')} "
              f"consensus={cond.get('analyst_consensus','?')} verdict={cond.get('debate_verdict','?')}")
    # Group diversity
    actions = set(p.get('action_type','?') for p in validated)
    modes = set(json.loads(p.get('condition_json','{}')).get('survival_mode','?') for p in validated if isinstance(p.get('condition_json','{}'),str))
    consensus = set(json.loads(p.get('condition_json','{}')).get('analyst_consensus','?') for p in validated if isinstance(p.get('condition_json','{}'),str))
    verdicts = set(json.loads(p.get('condition_json','{}')).get('debate_verdict','?') for p in validated if isinstance(p.get('condition_json','{}'),str))
    print(f"\nUnique action types:     {len(actions)}")
    print(f"Unique survival modes:   {len(modes)}")
    print(f"Unique consensus:        {len(consensus)}")
    print(f"Unique debate verdicts:  {len(verdicts)}")
    # Dominance check
    if len(validated) > 1:
        largest = max(validated, key=lambda p: int(p.get('sample_size',0)))
        largest_share = int(largest.get('sample_size',0)) / max(1, sum(int(p.get('sample_size',0)) for p in validated)) * 100
        print(f"\nLargest pattern share:   {largest_share:.0f}% ({largest['pattern_key']})")
        dominance_risk = "HIGH" if largest_share > 80 else "MEDIUM" if largest_share > 60 else "LOW"
    else:
        dominance_risk = "HIGH (only 1 pattern)"
        print(f"\nOnly 1 pattern — 100% dominance")
    # Diversity score
    div_score = min(30, len(actions)*10) + min(30, len(modes)*10) + min(20, len(consensus)*10) + min(20, len(verdicts)*10)
    if len(validated) <= 1:
        div_score *= 0.5  # Penalty for single pattern
    print(f"PATTERN_DIVERSITY_SCORE = {div_score:.0f}/100")
    if validated:
        by_sr = sorted(validated, key=lambda p: float(p.get('success_rate',0)), reverse=True)
        print(f"Dominant pattern:        {by_sr[0]['pattern_key']} sr={by_sr[0]['success_rate']} ss={by_sr[0]['sample_size']}")
        print(f"Weakest pattern:         {by_sr[-1]['pattern_key']} sr={by_sr[-1]['success_rate']} ss={by_sr[-1]['sample_size']}")
    else:
        print("No patterns to analyze.")
else:
    print("No validated patterns.")
    div_score = 0
    dominance_risk = "N/A"

# ===== SECTION C: Debate Verdict Distribution =====
print("\n--- SECTION C: DEBATE VERDICT DISTRIBUTION ---")
ep_verdicts = Counter(e.get('debate_verdict','?') for e in eps)
attr_verdicts = Counter(a.get('debate_verdict','?') for a in attr)
print("Episode debate verdicts:")
for v, c in sorted(ep_verdicts.items()): print(f"  {v}: {c}")
print("Attribution debate verdicts:")
for v, c in sorted(attr_verdicts.items()): print(f"  {v}: {c}")

unknown_pct = ep_verdicts.get('unknown',0) / max(1,total_eps) * 100
if unknown_pct > 80: debate_status = "POOR"
elif unknown_pct > 50: debate_status = "WARNING"
else: debate_status = "GOOD"
print(f"Unknown verdict share:   {unknown_pct:.0f}%")
print(f"DEBATE_DIVERSITY_STATUS = {debate_status}")

# ===== SECTION D: Attribution Quality =====
print("\n--- SECTION D: ATTRIBUTION QUALITY ---")
if attr:
    pending = sum(1 for a in attr if a.get('outcome_quality') == 'pending')
    pos = sum(1 for a in attr if a.get('outcome_quality') == 'positive')
    neg = sum(1 for a in attr if a.get('outcome_quality') == 'negative')
    neu = sum(1 for a in attr if a.get('outcome_quality') == 'neutral')
    print(f"Pending:   {pending}")
    print(f"Positive:  {pos}")
    print(f"Negative:  {neg}")
    print(f"Neutral:   {neu}")
    avg_rules = sum(int(a.get('memory_rules_count',0)) for a in attr) / max(1,len(attr))
    avg_conf = sum(float(a.get('memory_confidence',0)) for a in attr) / max(1,len(attr))
    contribs = [float(a.get('memory_contribution_score',0)) for a in attr if a.get('outcome_quality') != 'pending']
    avg_contrib = sum(contribs) / max(1,len(contribs)) if contribs else 0
    print(f"Avg memory_rules_count:        {avg_rules:.2f}")
    print(f"Avg memory_confidence:         {avg_conf:.4f}")
    print(f"Avg memory_contribution_score: {avg_contrib:.4f}")
    # duplicates
    cur.execute("SELECT episode_id, COUNT(*) FROM memory_attributions GROUP BY episode_id HAVING COUNT(*) > 1")
    dupes = cur.fetchall()
    print(f"Duplicate episode_id:           {len(dupes)}")
    contrib_pos = sum(1 for c in contribs if c > 0)
    print(f"Contributions > 0:              {contrib_pos}/{len(contribs) if contribs else 0}")
    conf_pos = sum(1 for a in attr if float(a.get('memory_confidence',0)) > 0)
    print(f"Confidence > 0:                 {conf_pos}/{len(attr)}")
    # Quality score
    aq_score = min(20, len(attr)*2)  # 10 = 20pt
    aq_score += min(20, (pos/max(1,pos+neg+neu))*20) if pos+neg+neu > 0 else 0
    aq_score += min(20, avg_conf * 30)
    aq_score += min(20, avg_contrib * 50)
    aq_score += 20 if len(dupes) == 0 else 0
    print(f"ATTRIBUTION_QUALITY_SCORE = {aq_score:.0f}/100")
else:
    print("No attribution records.")
    aq_score = 0

# ===== SECTION E: Memory Influence Analysis =====
print("\n--- SECTION E: MEMORY INFLUENCE ANALYSIS ---")
if attr and contribs:
    print(f"Average contribution:           {avg_contrib:.4f}")
    pos_contrib = sum(1 for c in contribs if c > 0)
    neg_contrib = sum(1 for c in contribs if c <= 0)
    print(f"Positive contributions:         {pos_contrib}")
    print(f"Non-positive contributions:     {neg_contrib}")
    if contribs:
        print(f"Highest contribution:           {max(contribs):.4f}")
        print(f"Lowest contribution:            {min(contribs):.4f}")
    if avg_contrib > 0.3 and pos_contrib > neg_contrib:
        mem_effect = "POSITIVE"
    elif avg_contrib > 0:
        mem_effect = "NEUTRAL (slightly positive)"
    else:
        mem_effect = "NEGATIVE"
else:
    mem_effect = "NEGATIVE (no resolved attribution data)"
print(f"MEMORY_EFFECTIVENESS = {mem_effect}")

# ===== SECTION F: Overfitting Risk =====
print("\n--- SECTION F: OVERFITTING RISK ---")
if validated:
    # Action concentration
    act_counts = Counter(p.get('action_type','?') for p in validated)
    top_action = act_counts.most_common(1)[0]
    action_conc = top_action[1] / max(1,len(validated)) * 100
    print(f"Action concentration:           {action_conc:.0f}% ({top_action[0]})")
    # Consensus concentration
    conc_list = []
    for p in validated:
        cj = p.get('condition_json','{}')
        if isinstance(cj, str):
            try: c = json.loads(cj).get('analyst_consensus','?')
            except: c = '?'
        else: c = '?'
        conc_list.append(c)
    top_consensus = Counter(conc_list).most_common(1)[0] if conc_list else ('?',0)
    consensus_conc = top_consensus[1] / max(1,len(validated)) * 100 if top_consensus else 0
    print(f"Consensus concentration:        {consensus_conc:.0f}%")
    # Verdict concentration
    ver_list = []
    for p in validated:
        cj = p.get('condition_json','{}')
        if isinstance(cj, str):
            try: v = json.loads(cj).get('debate_verdict','?')
            except: v = '?'
        else: v = '?'
        ver_list.append(v)
    top_verdict = Counter(ver_list).most_common(1)[0] if ver_list else ('?',0)
    verdict_conc = top_verdict[1] / max(1,len(validated)) * 100 if top_verdict else 0
    print(f"Verdict concentration:          {verdict_conc:.0f}%")
    # Overall risk
    risk_factors = 0
    if action_conc > 80: risk_factors += 1
    if consensus_conc > 80: risk_factors += 1
    if verdict_conc > 80: risk_factors += 1
    if len(validated) <= 1: risk_factors += 2
    if risk_factors >= 3: of_risk = "HIGH"
    elif risk_factors >= 1: of_risk = "MEDIUM"
    else: of_risk = "LOW"
    print(f"OVERFITTING_RISK = {of_risk}")
else:
    action_conc = consensus_conc = verdict_conc = 0
    of_risk = "HIGH (no validated patterns)"
    print(f"OVERFITTING_RISK = {of_risk}")

# ===== SECTION G: Readiness For Planner Influence =====
print("\n--- SECTION G: READINESS FOR PLANNER INFLUENCE ---")
thresholds = {
    "resolved >= 50": (resolved >= 50, f"{resolved}/50"),
    "validated patterns >= 3": (len(validated) >= 3, f"{len(validated)}/3"),
    "pattern diversity >= 3 groups": (len(set(p.get('action_type','?') for p in validated)) >= 3 if validated else False, f"{len(set(p.get('action_type','?') for p in validated)) if validated else 0}/3"),
    "avg contribution > 0.30": (avg_contrib > 0.30 if attr and contribs else False, f"{avg_contrib:.4f}" if attr and contribs else "N/A"),
    "no dominant pattern > 80%": (action_conc <= 80 if validated else False, f"{action_conc:.0f}%"),
}
for name, (passed, detail) in thresholds.items():
    status = "PASS" if passed else "FAIL"
    print(f"  {name:<45s} {status:4s} ({detail})")

all_pass = all(p for p,_ in thresholds.values())
print(f"\nMEMORY_INFLUENCE_READY = {'TRUE' if all_pass else 'FALSE'}")

# Comprehensive readiness
influence_ready = all_pass and ds_status in ("MEDIUM","HIGH") and mem_effect in ("POSITIVE","NEUTRAL")

# ===== SECTION H: Recommended Next Action =====
print("\n--- SECTION H: RECOMMENDED NEXT ACTION ---")
if influence_ready:
    rec = "4. Ready for full Phase 8 experimentation"
elif dataset_score >= 50 and len(validated) >= 1:
    rec = "2. Enable advisory memory influence (limited scope)"
elif dataset_score >= 30:
    rec = "1. Continue passive learning only (accumulate more data)"
else:
    rec = "1. Continue passive learning only (insufficient data)"
print(f"Recommended: {rec}")
print(f"Justification: dataset_sufficiency={ds_status}({dataset_score:.0f}/100), "
      f"validated={len(validated)} patterns, avg_contrib={avg_contrib:.4f}, "
      f"diversity={'inadequate' if len(validated) < 3 else 'adequate'}, "
      f"overfitting_risk={of_risk}")

# ===== FINAL SCORE COMPUTATION =====
print("\n" + "="*70)
print("FINAL VERDICT")
print("="*70)
mem_health = (dataset_score * 0.25 + div_score * 0.20 + aq_score * 0.20 +
              (100 if mem_effect in ("POSITIVE","NEUTRAL (slightly positive)") else 30) * 0.20 +
              (100 if of_risk == "LOW" else 50 if of_risk == "MEDIUM" else 20) * 0.15)
mem_health = round(mem_health, 1)
print(f"\n1. Memory system health:        {mem_health:.0f}/100 "
      f"({'GOOD' if mem_health >= 70 else 'FAIR' if mem_health >= 40 else 'POOR'})")
has_resolved_attr = any(a.get('outcome_quality') not in ('pending','unknown') and a.get('outcome_quality') is not None for a in attr)
print(f"2. Learning statistically meaningful? {'YES' if has_resolved_attr and avg_contrib > 0 else 'NO (data accumulating, no resolved cycles yet)'}")
print(f"3. Memory effectiveness:       {mem_effect}")
missing = []
if resolved < 50: missing.append(f"{50-resolved} more resolved episodes")
if len(validated) < 3: missing.append(f"{3-len(validated)} more validated pattern groups")
if not has_resolved_attr and attr: missing.append("first attribution resolution cycle (~6h)")
print(f"4. Biggest bottleneck:         {missing[0] if missing else 'None — waiting on runtime'}")
print(f"5. Ready for influence:       {'YES' if influence_ready else 'NO — needs more data diversity'}")
hours_est = max(0, (50-resolved)*0.5) if resolved < 50 else 0
print(f"6. Est. time to Phase 8:       {hours_est:.1f}h ({max(0,50-resolved)} more resolved episodes)")

ph8_status = "READY" if influence_ready else "PARTIAL" if dataset_score >= 50 else "NOT_READY"
print(f"\nMEMORY_HEALTH_SCORE = {mem_health}/100")
print(f"PHASE_8_READINESS = {ph8_status}")
conn.close()
print()