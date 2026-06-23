"""
Phase 8.4.2C — Decision Flow Visualization Plan
Backend: enrich /api/agent/evolution with milestones + brain map data
Frontend: 4 new panels in agent.html (Rows 10-11)
"""
import os, sys, psycopg2
from dotenv import load_dotenv; load_dotenv()
from datetime import datetime, timezone

dsn = os.environ["AGENT_POSTGRES_DSN"]
conn = psycopg2.connect(dsn)
cur = conn.cursor()

print("=== MILESTONE QUERIES ===\n")

# First episode
cur.execute("SELECT MIN(ts), COUNT(*) FROM agent_episodes")
r = cur.fetchone()
print(f"First episode: {str(r[0])[:19] if r[0] else 'N/A'} (total: {r[1]})")

# First pattern
cur.execute("SELECT MIN(first_seen), COUNT(*) FROM semantic_patterns")
r = cur.fetchone()
print(f"First pattern: {str(r[0])[:19] if r[0] else 'N/A'} (total: {r[1]})")

# First validated pattern
cur.execute("SELECT MIN(first_seen) FROM semantic_patterns WHERE validated=TRUE")
r = cur.fetchone()
print(f"First validated pattern: {str(r[0])[:19] if r[0] else 'N/A'}")

# First resolved pair (shadow_observation RESOLVED + attribution)
cur.execute("""
    SELECT MIN(so.ts) FROM shadow_observations so
    JOIN memory_attributions ma ON ma.plan_id = so.plan_id
    WHERE so.status='RESOLVED'
""")
r = cur.fetchone()
print(f"First resolved pair: {str(r[0])[:19] if r[0] else 'N/A'}")

# First resolved episode
cur.execute("SELECT MIN(ts) FROM agent_episodes WHERE resolved=TRUE")
r = cur.fetchone()
print(f"First resolved episode: {str(r[0])[:19] if r[0] else 'N/A'}")

# First disagreement
cur.execute("SELECT MIN(ts) FROM shadow_memory_influence WHERE agreement='DISAGREE'")
r = cur.fetchone()
print(f"First disagreement: {str(r[0])[:19] if r[0] else 'N/A'}")

# Memory brain map data: patterns grouped by survival_mode and analyst_consensus
cur.execute("""
    SELECT condition_json FROM semantic_patterns WHERE active=TRUE
""")
print("\n=== BRAIN MAP CONDITIONS ===")
for r in cur.fetchall():
    print(f"  {r[0]}")

# Pattern distribution by action_type, survival_mode
cur.execute("""
    SELECT action_type, COUNT(*) as cnt, 
           COUNT(*) FILTER (WHERE validated=TRUE) as validated,
           AVG(confidence_score) as avg_conf
    FROM semantic_patterns GROUP BY action_type ORDER BY cnt DESC
""")
print("\n=== PATTERNS BY ACTION ===")
for r in cur.fetchall():
    print(f"  {r[0]}: {r[1]} patterns, {r[2]} validated, avg_conf={round(r[3] or 0, 4)}")

# Count patterns by analyst_consensus from condition_json
cur.execute("""
    SELECT 
        condition_json->>'analyst_consensus' as consensus,
        condition_json->>'survival_mode' as mode,
        COUNT(*) as cnt
    FROM semantic_patterns WHERE active=TRUE
    GROUP BY consensus, mode ORDER BY consensus, mode
""")
print("\n=== BRAIN MAP HIERARCHY ===")
for r in cur.fetchall():
    print(f"  consensus={r[0]} mode={r[1]}: {r[2]} pattern(s)")

# Episode counts per mode
cur.execute("""
    SELECT survival_mode, analyst_consensus, COUNT(*) 
    FROM agent_episodes 
    GROUP BY survival_mode, analyst_consensus 
    ORDER BY survival_mode, analyst_consensus
""")
print("\n=== EPISODES BY MODE/CONSENSUS ===")
for r in cur.fetchall():
    print(f"  mode={r[0]} consensus={r[1]}: {r[2]} episodes")

conn.close()
print("\n=== PLAN CONFIRMED ===")
print("Backend: Add milestones[], all_patterns_hierarchy to /api/agent/evolution")
print("Frontend: 4 new panels (Row 10-11)")