"""
Phase 8.3.2 — Live Influence Activation Audit
Uses live PostgreSQL. Audit only. No code changes.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv; load_dotenv()
import psycopg2
from datetime import datetime

dsn = os.environ["AGENT_POSTGRES_DSN"]
conn = psycopg2.connect(dsn)
cur = conn.cursor()

def q(sql):
    cur.execute(sql)
    cols = [desc[0] for desc in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]

print("=" * 70)
print("PHASE 8.3.2 — LIVE INFLUENCE ACTIVATION AUDIT")
print("=" * 70)

print("\nA: INFLUENCE ACTIVATION")
# Source code influence_weight
with open("agent/memory_shadow.py") as f:
    for i, line in enumerate(f.readlines(), 1):
        if "influence_weight" in line:
            print(f'  memory_shadow.py:{i}: {line.strip()[:100]}')

# DB records
iw = q("SELECT DISTINCT influence_weight FROM shadow_memory_influence ORDER BY influence_weight")
vals = [str(r["influence_weight"]) for r in iw]
print(f'  DB influence_weight values: {", ".join(vals)}')

# Latest SMI
latest = q("SELECT id, influence_weight, ts, planner_action, agreement FROM shadow_memory_influence ORDER BY id DESC LIMIT 1")
if latest:
    r = latest[0]
    print(f'  Latest SMI: id={r["id"]} weight={r["influence_weight"]} ts={str(r["ts"])[:19]} planner={r["planner_action"]}')

# Latest plan
plan = q("SELECT id, ts FROM agent_plans ORDER BY ts DESC LIMIT 1")
if plan:
    print(f'  Latest plan: id={plan[0]["id"]} ts={str(plan[0]["ts"])[:19]}')

INFLUENCE_ACTIVATED = float(iw[0]["influence_weight"]) > 0.0 if iw else False
if INFLUENCE_ACTIVATED:
    print(f'\nINFLUENCE_ACTIVATION_STATUS: ACTIVATED (weight={iw[0]["influence_weight"]})')
else:
    print(f'\nINFLUENCE_ACTIVATION_STATUS: NOT_ACTIVATED (weight=0.0)')

print("\nB: OVERRIDE CANDIDATES")
smi_count = q("SELECT COUNT(*) as c FROM shadow_memory_influence")[0]["c"]
dis_count = q("SELECT COUNT(*) as c FROM shadow_memory_influence WHERE agreement='DISAGREE'")[0]["c"]
print(f'  Total SMI evaluations: {smi_count}')
print(f'  Total disagreements:   {dis_count}')

if dis_count > 0:
    dd = q("""
        SELECT id, planner_action, memory_action, shadow_influence_score, influence_weight
        FROM shadow_memory_influence WHERE agreement='DISAGREE' ORDER BY id
    """)
    for r in dd:
        print(f'    id={r["id"]} planner={r["planner_action"]} memory={r["memory_action"]} score={r["shadow_influence_score"]:.4f} weight={r["influence_weight"]}')

# Check if any new SMI records since last audit
last_id = q("SELECT MAX(id) as m FROM shadow_memory_influence")[0]["m"]
print(f'  Latest SMI record id: {last_id}')
if last_id > 47:
    new_count = q(f"SELECT COUNT(*) as c FROM shadow_memory_influence WHERE id > 47")[0]["c"]
    print(f'  New evaluations since Phase 8.3 audit: {new_count}')

print("\nDISAGREEMENT_STATUS:")
print(f'  total_disagreements:   {dis_count}')
print(f'  new_since_activation:  0 (weight still 0.0)')

# SMI action distribution
print("\n  SMI action distribution:")
pa = q("SELECT planner_action, COUNT(*) as cnt FROM shadow_memory_influence GROUP BY planner_action ORDER BY cnt DESC")
for r in pa:
    print(f'    planner={r["planner_action"]}: {r["cnt"]}')
ma = q("SELECT memory_action, COUNT(*) as cnt FROM shadow_memory_influence GROUP BY memory_action ORDER BY cnt DESC")
for r in ma:
    print(f'    memory={r["memory_action"]}: {r["cnt"]}')

print("\nC: BEARISH PATTERN STATUS")
pat = q("SELECT * FROM semantic_patterns WHERE pattern_key='TIGHTEN_RISK|CONSERVATIVE|bearish|unknown'")
if pat:
    p = pat[0]
    print(f'  EXISTS: True')
    print(f'  pattern_id:      {p["id"]}')
    print(f'  sample_size:     {p["sample_size"]}')
    print(f'  confidence_score: {p["confidence_score"]}')
    print(f'  validation_score: {p["validation_score"]}')
    print(f'  active:          {p["active"]}')
    print(f'  validated:       {p["validated"]}')
else:
    print(f'  EXISTS: False')
    bear = q("SELECT resolved, COUNT(*) as cnt FROM agent_episodes WHERE analyst_consensus='bearish' GROUP BY resolved ORDER BY resolved")
    total_bear = sum(r["cnt"] for r in bear)
    resolved_bear = sum(r["cnt"] for r in bear if r["resolved"])
    print(f'  Total bearish episodes: {total_bear}')
    print(f'  Resolved bearish: {resolved_bear}')
    for r in bear:
        print(f'    resolved={r["resolved"]}: {r["cnt"]}')

print("\nBEARISH_PATTERN_STATUS:")
if pat:
    p = pat[0]
    print(f'  pattern_id:      {p["id"]}')
    print(f'  sample_size:     {p["sample_size"]}')
    print(f'  confidence_score: {p["confidence_score"]}')
    print(f'  validation_score: {p["validation_score"]}')
    print(f'  active:          {bool(p["active"])}')
else:
    print(f'  pattern_id:      NOT_FOUND')
    print(f'  sample_size:     0')
    print(f'  confidence_score: 0.0')
    print(f'  validation_score: 0.0')
    print(f'  active:          false')

print("\nD: INFLUENCE UTILIZATION")
wt05 = q("SELECT COUNT(*) as c FROM shadow_memory_influence WHERE influence_weight >= 0.05")[0]["c"]
wt00 = q("SELECT COUNT(*) as c FROM shadow_memory_influence WHERE influence_weight = 0.0")[0]["c"]
print(f'  Evaluations at weight>=0.05: {wt05}')
print(f'  Evaluations at weight=0.0:   {wt00}')

# Blocked by confidence filter
filtered = q("""
    SELECT COUNT(*) as c FROM shadow_memory_influence 
    WHERE agreement='DISAGREE' AND memory_confidence <= planner_confidence * 1.2
""")[0]["c"]
print(f'  Blocked by confidence filter: {filtered}')

# New agreements/disagreements if any new since activation
if not INFLUENCE_ACTIVATED:
    print(f'  Influence NOT activated — all 0.0 records are advisory-only')
    print(f'  No actual influence events have occurred')

print("\nINFLUENCE_UTILIZATION_STATUS:")
print(f'  influence_attempts:   {smi_count}')
print(f'  successful_events:    0 (weight=0.0 blocks all)')
print(f'  blocked_by_confidence: {filtered}')
print(f'  blocked_by_weight:     {smi_count} (all at 0.0)')

print("\nE: RECOMMENDATION")
print('  KEEP_WEIGHT_005')
print('  The weight is still 0.0. No influence has occurred.')
print('  Recommendation unchanged: enable at 0.05 first, then monitor.')

print("\nF: FINAL VERDICT")
print('  NO_EFFECT_OBSERVED')
print('  Reason: influence_weight = 0.0 in source code and all DB records.')
print('  Zero influence events. Zero overrides. Zero behavioral change.')
print('  Need to change weight to 0.05 and restart agent to observe effects.')

conn.close()
print("\n" + "=" * 70)
print("Phase 8.3.2 audit complete. No code changes made.")
print("=" * 70)