"""
Deep field-by-field audit: simulate loadEvolution() in Python
to find which property access causes the JS TypeError.

Run: python agent/_audit_fields.py
"""
import urllib.request, json, traceback

def audit_evolution():
    print("=" * 70)
    print("FIELD AUDIT: /api/agent/evolution")
    print("=" * 70)
    
    resp = urllib.request.urlopen("http://localhost:8000/api/agent/evolution", timeout=15)
    d = json.loads(resp.read().decode())
    
    errors = []
    
    # ── Row 5: Memory Influence ──
    print("\n--- Memory Influence ---")
    mem = d.get("memory_influence")
    if not isinstance(mem, dict):
        errors.append(f"memory_influence missing or not dict: {type(mem)}")
    else:
        for field, label in [("influence_weight","Weight"),("total_evaluations","Evals"),
                             ("agreements","Agree"),("disagreements","Disagree"),
                             ("overrides","Overrides"),("blocked_overrides","Blocked")]:
            val = mem.get(field)
            if val is None:
                errors.append(f"memory_influence.{field} is None")
            else:
                print(f"  ✓ {field} = {val}")
    
    # ── Row 5: Pattern Growth ──
    print("\n--- Pattern Growth ---")
    pat = d.get("patterns")
    if not isinstance(pat, dict):
        errors.append(f"patterns missing or not dict: {type(pat)}")
    else:
        for field, label in [("validated_patterns","Validated"),("active_patterns","Active"),
                             ("avg_confidence","AvgConf"),("avg_validation_score","AvgVal")]:
            val = pat.get(field)
            if val is None:
                errors.append(f"patterns.{field} is None")
            else:
                print(f"  ✓ {field} = {val}")
    
    # ── Row 5: Pair Growth ──
    print("\n--- Pair Growth ---")
    sh = d.get("shadow_growth")
    if not isinstance(sh, dict):
        errors.append(f"shadow_growth missing or not dict: {type(sh)}")
    else:
        for field in ["total_observations","resolved_observations","resolved_pairs","pair_coverage_pct"]:
            val = sh.get(field)
            if val is None:
                errors.append(f"shadow_growth.{field} is None")
            else:
                print(f"  ✓ {field} = {val}")
    
    # ── Row 5: Evolution Scorecard ──
    print("\n--- Scorecard ---")
    sc = d.get("scorecard")
    if not isinstance(sc, dict):
        errors.append(f"scorecard missing or not dict: {type(sc)}")
    else:
        for field in ["patterns","pairs","confidence","contribution","agreement_rate"]:
            val = sc.get(field)
            if val is None:
                errors.append(f"scorecard.{field} is None")
            else:
                # Check toFixed() compatibility (must be number)
                if not isinstance(val, (int, float)):
                    errors.append(f"scorecard.{field} not a number: {type(val)} = {val}")
                else:
                    print(f"  ✓ {field} = {val}")
    
    evo = d.get("evolution")
    if not isinstance(evo, dict):
        errors.append(f"evolution missing or not dict: {type(evo)}")
    else:
        score = evo.get("score")
        if score is None:
            errors.append("evolution.score is None")
        else:
            print(f"  ✓ evolution.score = {score}")
        status = evo.get("status")
        if status is None:
            errors.append("evolution.status is None")
        else:
            print(f"  ✓ evolution.status = {status}")
    
    # ── Row 6: Recent Changes ──
    print("\n--- Recent Changes ---")
    rc = d.get("recent_changes")
    if not isinstance(rc, list):
        errors.append(f"recent_changes not a list: {type(rc)}")
    else:
        print(f"  ✓ recent_changes = {rc}")
    
    # ── Row 6: Influence Activity (trends.influence) ──
    print("\n--- Influence Trends ---")
    trends = d.get("trends")
    if not isinstance(trends, dict):
        errors.append(f"trends missing or not dict: {type(trends)}")
    else:
        inf = trends.get("influence")
        if not isinstance(inf, list):
            errors.append(f"trends.influence not a list: {type(inf)}")
        else:
            print(f"  ✓ trends.influence entries = {len(inf)}")
            for i, t in enumerate(inf[:2]):
                for field in ["day","agrees","disagrees","overrides"]:
                    if t.get(field) is None:
                        errors.append(f"trends.influence[{i}].{field} is None")
    
    # ── Row 7: Pattern Evolution (trends.patterns) ──
    print("\n--- Pattern Trends ---")
    pTrend = trends.get("patterns") if isinstance(trends, dict) else None
    if not isinstance(pTrend, list):
        errors.append(f"trends.patterns not a list: {type(pTrend)}")
    else:
        print(f"  ✓ trends.patterns entries = {len(pTrend)}")
        if pTrend:
            # Check map() will work
            for i, p in enumerate(pTrend[:2]):
                if p.get("new") is None:
                    errors.append(f"trends.patterns[{i}].new is None")
    
    # ── Row 7: Memory Growth (trends.episodes) ──
    print("\n--- Episode Trends ---")
    eTrend = trends.get("episodes") if isinstance(trends, dict) else None
    if not isinstance(eTrend, list):
        errors.append(f"trends.episodes not a list: {type(eTrend)}")
    else:
        print(f"  ✓ trends.episodes entries = {len(eTrend)}")
        if eTrend:
            for i, e in enumerate(eTrend[:2]):
                for field in ["eps","resolved"]:
                    if e.get(field) is None:
                        errors.append(f"trends.episodes[{i}].{field} is None")
    
    total_eps = d.get("total_episodes")
    if total_eps is None:
        errors.append("total_episodes is None")
    else:
        print(f"  ✓ total_episodes = {total_eps}")
    
    resolved_eps = d.get("resolved_episodes")
    if resolved_eps is None:
        errors.append("resolved_episodes is None")
    else:
        print(f"  ✓ resolved_episodes = {resolved_eps}")
    
    # ── Row 8: Pair Resolution (trends.pairs) ──
    print("\n--- Pair Trends ---")
    pairT = trends.get("pairs") if isinstance(trends, dict) else None
    if not isinstance(pairT, list):
        errors.append(f"trends.pairs not a list: {type(pairT)}")
    else:
        print(f"  ✓ trends.pairs entries = {len(pairT)}")
        if pairT:
            for i, p in enumerate(pairT[:2]):
                if p.get("pairs") is None:
                    errors.append(f"trends.pairs[{i}].pairs is None")
    
    # ── Row 8: Pattern Leaderboard (all_patterns) ──
    print("\n--- All Patterns ---")
    all_p = d.get("all_patterns")
    if not isinstance(all_p, list):
        errors.append(f"all_patterns not a list: {type(all_p)}")
    else:
        print(f"  ✓ all_patterns count = {len(all_p)}")
        for i, p in enumerate(all_p[:2]):
            for field in ["pattern_key","sample_size","success_rate","confidence_score","validation_score","active","validated"]:
                if p.get(field) is None:
                    errors.append(f"all_patterns[{i}].{field} is None")
    
    # ── Row 9: Lifecycle ──
    print("\n--- Lifecycle ---")
    lc = d.get("lifecycle")
    if not isinstance(lc, dict):
        errors.append(f"lifecycle missing or not dict: {type(lc)}")
    else:
        stages = lc.get("stages")
        if not isinstance(stages, list):
            errors.append("lifecycle.stages not a list")
        else:
            print(f"  ✓ lifecycle.stages count = {len(stages)}")
            for i, s in enumerate(stages):
                for field in ["stage","name","complete","pct"]:
                    if s.get(field) is None:
                        errors.append(f"lifecycle.stages[{i}].{field} is None")
        if lc.get("progress_pct") is None:
            errors.append("lifecycle.progress_pct is None")
        else:
            print(f"  ✓ lifecycle.progress_pct = {lc.get('progress_pct')}")
        if lc.get("current_stage") is None:
            errors.append("lifecycle.current_stage is None")
        else:
            print(f"  ✓ lifecycle.current_stage = {lc.get('current_stage')}")
    
    # ── Row 9: AI Age + 24h Changes (changes_24h) ──
    print("\n--- AI Age + Changes ---")
    age = d.get("agent_age_days")
    if age is None:
        errors.append("agent_age_days is None")
    else:
        print(f"  ✓ agent_age_days = {age}")
    
    c24 = d.get("changes_24h")
    if not isinstance(c24, dict):
        errors.append("changes_24h missing")
    else:
        for field in ["patterns_created","pairs_resolved","confidence","agreement_rate","override_count"]:
            val = c24.get(field)
            if val is None:
                errors.append(f"changes_24h.{field} is None")
            else:
                print(f"  ✓ changes_24h.{field} = {val}")
    
    # ── Summary ──
    print("\n" + "=" * 70)
    if errors:
        print(f"\n❌ {len(errors)} ERRORS FOUND:")
        for e in errors:
            print(f"   - {e}")
    else:
        print("\n✅ ALL FIELDS VALID - No missing/null values")

if __name__ == "__main__":
    try:
        audit_evolution()
    except Exception as e:
        print(f"\n❌ SCRIPT FAILED: {type(e).__name__}: {e}")
        traceback.print_exc()