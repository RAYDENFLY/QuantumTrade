"""
Quick diagnostic: test /api/agent/evolution endpoint.
Run: python agent/_audit_evolution.py
"""
import urllib.request, json, traceback, sys

url = "http://localhost:8000/api/agent/evolution"

print("=" * 60)
print("DIAGNOSTIC: /api/agent/evolution")
print("=" * 60)

try:
    req = urllib.request.Request(url)
    resp = urllib.request.urlopen(req, timeout=15)
    print(f"\n[OK] Status: {resp.status} {resp.reason}")
    raw = resp.read().decode("utf-8")
    data = json.loads(raw)
    
    if "error" in data and data["error"]:
        print(f"\n[FAIL] Backend returned error:")
        print(f"  error: {data['error']}")
        print(f"\nFull response:")
        print(json.dumps(data, indent=2)[:2000])
    else:
        print(f"\n[OK] Response keys: {list(data.keys())}")
        print(f"  patterns.validated_patterns: {data.get('patterns', {}).get('validated_patterns', 'MISSING')}")
        print(f"  memory_influence.total_evaluations: {data.get('memory_influence', {}).get('total_evaluations', 'MISSING')}")
        print(f"  shadow_growth.total_observations: {data.get('shadow_growth', {}).get('total_observations', 'MISSING')}")
        print(f"  scorecard: {data.get('scorecard', {})}")
        print(f"  evolution.score: {data.get('evolution', {}).get('score', 'MISSING')}")
        print(f"  trends keys: {list(data.get('trends', {}).keys())}")
        print(f"  agent_age_days: {data.get('agent_age_days', 'MISSING')}")
        print(f"  total_episodes: {data.get('total_episodes', 'MISSING')}")
        print(f"  lifecycle present: {bool(data.get('lifecycle'))}")
        print(f"  all_patterns count: {len(data.get('all_patterns', []))}")
        print(f"  override_candidates count: {len(data.get('override_candidates', []))}")
        print(f"  recent_changes: {data.get('recent_changes', [])}")
except urllib.error.HTTPError as e:
    print(f"\n[FAIL] HTTP Error: {e.code} {e.reason}")
    print(f"  Body: {e.read().decode()[:1000]}")
except urllib.error.URLError as e:
    print(f"\n[FAIL] URL Error: {e.reason}")
    print("  Is the dashboard server running?")
    print("  Try: uvicorn dashboard.app:app --reload --port 8000")
except Exception as e:
    print(f"\n[FAIL] Unexpected error: {type(e).__name__}: {e}")
    traceback.print_exc()

print()
print("=" * 60)
print("DIAGNOSTIC: /api/agent/performance-over-time")
print("=" * 60)

try:
    req = urllib.request.Request("http://localhost:8000/api/agent/performance-over-time")
    resp = urllib.request.urlopen(req, timeout=15)
    print(f"\n[OK] Status: {resp.status} {resp.reason}")
    raw = resp.read().decode("utf-8")
    data = json.loads(raw)
    
    if "error" in data and data["error"]:
        print(f"\n[FAIL] Backend returned error:")
        print(f"  error: {data['error']}")
        if "traceback" in data:
            print(f"  traceback: {data['traceback'][:2000]}")
    else:
        print(f"\n[OK] Response keys: {list(data.keys())}")
        print(f"  learning_curve days: {len(data.get('learning_curve', []))}")
        print(f"  intelligence_scores days: {len(data.get('intelligence_scores', []))}")
        print(f"  today_score: {data.get('today_score', 'MISSING')}")
        print(f"  yesterday_score: {data.get('yesterday_score', 'MISSING')}")
        print(f"  score_delta: {data.get('score_delta', 'MISSING')}")
        print(f"  score_7day_trend: {data.get('score_7day_trend', [])}")
        print(f"  pattern_births entries: {len(data.get('pattern_births', []))}")
        print(f"  memory_effectiveness entries: {len(data.get('memory_effectiveness', []))}")
        print(f"  improvement_status: {data.get('improvement_status', 'MISSING')}")
        print(f"  improvement_signals: {data.get('improvement_signals', {})}")
        print(f"  forecast keys: {list(data.get('forecast', {}).keys())}")
except urllib.error.HTTPError as e:
    print(f"\n[FAIL] HTTP Error: {e.code} {e.reason}")
    print(f"  Body: {e.read().decode()[:1000]}")
except urllib.error.URLError as e:
    print(f"\n[FAIL] URL Error: {e.reason}")
except Exception as e:
    print(f"\n[FAIL] Unexpected error: {type(e).__name__}: {e}")
    traceback.print_exc()