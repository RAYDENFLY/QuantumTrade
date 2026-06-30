"""
Project Rebranding Script: QuantumTrade → Astel Research - TradingAgents

Updates all user-facing strings. Does NOT modify:
  - Python package names
  - Import paths
  - Database schemas
  - API endpoints
  - Environment variable names
  - Configuration keys
"""
import os
import glob

FILES = [
    "README.md",
    "live_runner.py",
    "dashboard/app.py",
    "dashboard/templates/agent.html",
    "dashboard/templates/index.html",
    "docs/PROJECT_DOCUMENTATION.md",
    "design-sistem.md",
    "planning.md",
]

OLD = "QuantumTrade"
NEW = "Astel Research - TradingAgents"

total = 0
for fpath in FILES:
    if not os.path.exists(fpath):
        print(f"SKIP: {fpath} not found")
        continue
    content = open(fpath, "r", encoding="utf-8").read()
    count = content.count(OLD)
    if count == 0:
        print(f"OK:   {fpath} — no occurrences")
        continue
    new_content = content.replace(OLD, NEW)
    open(fpath, "w", encoding="utf-8").write(new_content)
    total += count
    print(f"UPDATED: {fpath} — {count}x '{OLD}' -> '{NEW}'")

print(f"\nTotal: {total} replacements across {len(FILES)} files")
print("Rebranding complete.")