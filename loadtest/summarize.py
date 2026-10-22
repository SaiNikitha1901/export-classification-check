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
    for r in csv.DictReader(f.open()):
        if r["Name"] == "complete_run":
            n, fails = int(r["Request Count"]), int(r["Failure Count"])
            p50, p95 = float(r["50%"]) / 1000, float(r["95%"]) / 1000
            fail_rate = fails / n if n else 1.0
            met = n > 0 and p95 <= SLO_P95_S and fail_rate < SLO_FAIL
            rows.append((users, n, float(r["Requests/s"]), p50, p95, fail_rate, met))
print(f"\nSweep '{label}'  (SLO: p95 <= {SLO_P95_S:.0f}s, failures < {SLO_FAIL:.0%})")
print("| users | runs | runs/s | p50 (s) | p95 (s) | failed | SLO met |")
print("|---|---|---|---|---|---|---|")
for u, n, rps, p50, p95, fr, met in rows:
    print(f"| {u} | {n} | {rps:.2f} | {p50:.1f} | {p95:.1f} | {fr:.1%} | {'yes' if met else 'NO'} |")
fail_at = next((u for u, *_, met in rows if not met), None)
print(f"\nFirst concurrency where the SLO fails: {fail_at if fail_at else 'not reached in this sweep'}")
