import json
from pathlib import Path
from app.parser import load_process, build_graph
from app.metrics import compute_metrics
from app.heuristics import HEURISTICS, all_candidates

BASE_DIR = Path(__file__).parent.parent
FILE_PATH = BASE_DIR / "data" / "asIsProcess.json"

data = load_process(FILE_PATH)
g = build_graph(data)

print("Baseline:", compute_metrics(g))
print()
print("Valid actions found on As-Is process:")
for hid, target in all_candidates(g):
    print(f"  {hid:22s} -> {target}")

print()
print("=== Manual verification: apply activity_elimination to (995,) ===")
_, apply_fn = HEURISTICS["activity_elimination"]
g2 = apply_fn(g, (995,))
print("Before:", compute_metrics(g))
print("After: ", compute_metrics(g2))