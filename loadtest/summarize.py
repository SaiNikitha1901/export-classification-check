"""Summarise Locust CSVs for one sweep label against the SLO. Usage: python3 loadtest/summarize.py <label>"""
import csv
import re
import sys
from pathlib import Path

SLO_P95_S = 60.0
SLO_FAIL = 0.01
label = sys.argv[1]
rows = []
for f in sorted(Path(__file__).parent.joinpath("results").glob(f"{label}_u*_stats.csv"),
                key=lambda p: int(re.search(r"_u(\d+)_", p.name).group(1))):
    users = int(re.search(r"_u(\d+)_", f.name).group(1))
    stats = {r["Name"]: r for r in csv.DictReader(f.open())}
    submitted = int((stats.get("POST /runs") or {}).get("Request Count") or 0)
    r = stats.get("complete_run")
    n = int(r["Request Count"]) if r else 0
    fails = int(r["Failure Count"]) if r else 0
    # Runs submitted but not finished when Locust stopped. Check them in Postgres after the sweep:
    # if any did not end completed/escalated they are failures; a run that finished just after the
    # stop is a cut-off, not a failure. Reported separately, never silently dropped.
    unfinished = max(0, submitted - n - int((stats.get("POST /runs") or {}).get("Failure Count") or 0))
    p50 = float(r["50%"]) / 1000 if r else float("nan")
    p95 = float(r["95%"]) / 1000 if r else float("nan")
    fail_rate = fails / n if n else 1.0
    met = n > 0 and p95 <= SLO_P95_S and fail_rate < SLO_FAIL
    rows.append((users, n, float(r["Requests/s"]) if r else 0.0, p50, p95, fail_rate, met, unfinished))
print(f"\nSweep '{label}'  (SLO: p95 <= {SLO_P95_S:.0f}s, failures < {SLO_FAIL:.0%})")
print("| users | runs finished | runs/s | p50 (s) | p95 (s) | cut off at stop | failed | SLO met |")
print("|---|---|---|---|---|---|---|---|")
for u, n, rps, p50, p95, fr, met, unf in rows:
    print(f"| {u} | {n} | {rps:.3f} | {p50:.1f} | {p95:.1f} | {unf} | {fr:.0%} | {'yes' if met else 'NO'} |")
fail_at = next((row[0] for row in rows if not row[6]), None)
print(f"\nFirst concurrency where the SLO fails: {fail_at if fail_at else 'not reached in this sweep'}")
