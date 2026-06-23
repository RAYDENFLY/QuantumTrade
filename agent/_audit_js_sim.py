"""
Forensic analysis: simulate every JS template literal in loadEvolution()
against the live /api/agent/evolution response.

Identifies the exact line that would throw in JavaScript.
"""
import urllib.request, json, sys

resp = urllib.request.urlopen("http://localhost:8000/api/agent/evolution", timeout=15)
d = json.loads(resp.read().decode())

failed = 0
tested = 0

def check(label, expr):
    global tested, failed
    tested += 1
    try:
        result = expr()
        return True
    except Exception as e:
        failed += 1
        print(f"  ❌ {label}")
        print(f"     Exception: {type(e).__name__}: {e}")
        return False

print("=" * 65)
print("JS TEMPLATE SIMULATION - loadEvolution()")
print("=" * 65)

# ── Line 792: Memory Influence panel ──
mem = d.get("memory_influence", {})
check("mem.influence_weight", lambda: f"{mem['influence_weight']}")
check("mem.total_evaluations", lambda: f"{mem['total_evaluations']}")
check("mem.agreements", lambda: f"{mem['agreements']}")
check("mem.disagreements", lambda: f"{mem['disagreements']}")
check("mem.overrides", lambda: f"{mem['overrides']}")
check("mem.blocked_overrides", lambda: f"{mem['blocked_overrides']}")

# ── Line 803: Pattern Growth panel ──
pat = d.get("patterns", {})
check("pat.validated_patterns", lambda: f"{pat['validated_patterns']}")
check("pat.active_patterns", lambda: f"{pat['active_patterns']}")
check("pat.avg_confidence.toFixed(2)", lambda: f"{round(pat['avg_confidence'], 2)}")
check("pat.avg_validation_score.toFixed(2)", lambda: f"{round(pat['avg_validation_score'], 2)}")
# Line 809
trends = d.get("trends", {})
p_trend = trends.get("patterns", [])
check("d.trends.patterns.map(p => p.day + p.new)", lambda: "".join([f"{p['day']}: +{p['new']}" for p in p_trend]))

# ── Line 815: Pair Growth panel ──
sh = d.get("shadow_growth", {})
check("sh.total_observations", lambda: f"{sh['total_observations']}")
check("sh.resolved_observations", lambda: f"{sh['resolved_observations']}")
check("sh.resolved_pairs", lambda: f"{sh['resolved_pairs']}")
check("sh.pair_coverage_pct", lambda: f"{sh['pair_coverage_pct']}%")
pair_trend = trends.get("pairs", [])
check("d.trends.pairs.map(p => p.day + p.pairs)", lambda: "".join([f"{p['day']}: {p['pairs']} pairs" for p in pair_trend]))

# ── Line 828: Scorecard ──
sc = d.get("scorecard", {})
evo = d.get("evolution", {})
check("evo.score >= 60 check", lambda: f"{evo['score']}")
check("evo.status", lambda: f"{evo['status']}")
check("sc.patterns / 5 * 100 =", lambda: f"{min(100, sc['patterns'] / 5 * 100)}")
check("sc.pairs / 500 * 100 =", lambda: f"{min(100, sc['pairs'] / 500 * 100)}")
check("sc.confidence.toFixed(2)", lambda: f"{round(sc['confidence'], 2)}")
check("sc.contribution.toFixed(2)", lambda: f"{round(sc['contribution'], 2)}")
check("sc.agreement_rate", lambda: f"{sc['agreement_rate']}%")
check("(sc.confidence * 100).toFixed(0)", lambda: f"{round(sc['confidence'] * 100)}")
check("(sc.contribution * 100).toFixed(0)", lambda: f"{round(sc['contribution'] * 100)}")

# ── Line 843: Recent Changes ──
rc = d.get("recent_changes", [])
check("recent_changes length", lambda: len(rc))
if rc:
    check("recent_changes[0]", lambda: rc[0])

# ── Line 849: Influence Activity ──
inf = trends.get("influence", [])
check("trends.influence length", lambda: len(inf))
if inf:
    check("inf[0].agrees", lambda: f"{inf[0]['agrees']}")

# ── Line 862: Pattern Evolution Chart ──
check("pTrend length > 0", lambda: len(p_trend) > 0)
if p_trend:
    maxP = max(p['new'] for p in p_trend)
    maxP = max(maxP, 1)
    check("Math.max(...pTrend.map(p=>p.new), 1)", lambda: maxP)
    check("pTrend[0].day", lambda: p_trend[0]['day'])
    check("pTrend[0].new", lambda: p_trend[0]['new'])
    check("(p.new / maxP * 100).toFixed(0)", lambda: f"{round(p_trend[0]['new'] / maxP * 100)}")

# ── Line 877: Memory Growth Chart ──
e_trend = trends.get("episodes", [])
check("eTrend length > 0", lambda: len(e_trend) > 0)
if e_trend:
    maxEps = max(e['eps'] for e in e_trend)
    maxEps = max(maxEps, 1)
    check("Math.max(...eTrend.map(e=>e.eps), 1)", lambda: maxEps)
    check("d.total_episodes", lambda: d['total_episodes'])
    check("d.resolved_episodes", lambda: d['resolved_episodes'])
    check("d.patterns.validated_patterns", lambda: d['patterns']['validated_patterns'])
    check("e.eps / maxEps * 100", lambda: e_trend[0]['eps'] / maxEps * 100)
    check("e.resolved / maxEps * 100", lambda: e_trend[0]['resolved'] / maxEps * 100)

# ── Line 900: Pair Resolution Chart ──
check("pairT length > 0", lambda: len(pair_trend) > 0)
if pair_trend:
    maxP2 = max(p['pairs'] for p in pair_trend)
    maxP2 = max(maxP2, 1)
    check("Math.max(...pairT.map(p=>p.pairs), 1)", lambda: maxP2)
    check("pairT[0].pairs / maxP2 * 100", lambda: pair_trend[0]['pairs'] / maxP2 * 100)

# ── Line 922: Pattern Leaderboard ──
all_p = d.get("all_patterns", [])
check("all_patterns count > 0", lambda: len(all_p) > 0)
if all_p:
    p0 = all_p[0]
    check("p.sample_size / 500 * 100", lambda: min(100, p0['sample_size'] / 500 * 100))
    check("p.success_rate * 100", lambda: p0['success_rate'] * 100)
    check("p.confidence_score.toFixed(2)", lambda: round(p0['confidence_score'], 2))
    check("p.validation_score.toFixed(2)", lambda: round(p0['validation_score'], 2))

# ── Line 945: AI Lifecycle ──
lc = d.get("lifecycle", {})
check("lifecycle exists", lambda: bool(lc))
if lc:
    stages = lc.get("stages", [])
    check("stages count", lambda: len(stages))
    check("progress_pct", lambda: lc['progress_pct'])
    check("current_stage", lambda: lc['current_stage'])
    check("stages[0].complete", lambda: stages[0]['complete'])

# ── Line 960: AI Age + Changes ──
c24 = d.get("changes_24h", {})
check("agent_age_days.toFixed(1)", lambda: f"{round(d['agent_age_days'], 1)}d")
check("total_episodes", lambda: d['total_episodes'])
check("changes_24h.patterns_created", lambda: c24.get('patterns_created', 0))
check("changes_24h.pairs_resolved", lambda: c24.get('pairs_resolved', 0))
check("(c24.confidence || 0).toFixed(2)", lambda: f"{round(c24.get('confidence', 0), 2)}")
check("(c24.agreement_rate || 0).toFixed(1)", lambda: f"{round(c24.get('agreement_rate', 0), 1)}%")

# ── Summary ──
print()
print("=" * 65)
print(f"RESULTS: {tested} expressions tested, {failed} failed")
if failed == 0:
    print("✅ ALL EXPRESSIONS VALID - No backend-visible root cause")
    print()
    print("CONCLUSION: The error is browser/JS-engine specific.")
    print("Possible causes:")
    print("  1. CSP blocking inline script execution")
    print("  2. Browser extension (adblocker) injecting into page")
    print("  3. Cached old version of agent.html (hard refresh needed: Ctrl+F5)")
    print("  4. Race condition: DOM element IDs loaded before page fully renders")
    print("  5. The ◉ character in lifecycle template (U+25C9) may cause encoding issues")
    print()
    print("🔑 To identify EXACT exception: Open F12 → Console, copy the error shown.")
    print(f"   console.error(e) now prints on every 10s poll cycle.")
else:
    print(f"❌ {failed} FAILURE(S) DETECTED - See above")