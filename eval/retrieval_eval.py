"""Retrieval-only evaluation (no LLM): does a single search for the product text bring back the right heading?
Isolates the retriever from the agents, so the effect of a retrieval change is measured directly.

  docker compose run --rm -v "$PWD/eval:/srv/eval" retriever python eval/retrieval_eval.py [--k 8]

For every scenario with an expected heading, query = product_description (+ intended_use), and for each mode
(dense, keyword, hybrid) it reports:
  hit@1 / hit@k  the expected heading (HDG-xxxx or one of its TL-xxxx…) is in the top 1 / top k
  MRR            mean reciprocal rank of the first passage of the expected heading
  recall@k       share of the scenario's supporting HDG/TL/notes clause IDs in the top k (GRI and EXP excluded:
                 the agent fetches those by ID, not by search)
Writes eval/results/<UTC time>_retrieval/retrieval_summary.{json,md}.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
from datetime import datetime, timezone
from pathlib import Path

import requests

HERE = Path(__file__).parent
MODES = ("dense", "keyword", "hybrid")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--retriever", default=os.getenv("RETRIEVER_URL", "http://retriever:8001"))
    ap.add_argument("--k", type=int, default=8)
    args = ap.parse_args()
    scenarios = [json.loads(l) for l in (HERE / "scenarios.jsonl").read_text(encoding="utf-8").splitlines() if l]
    scenarios = [s for s in scenarios if s.get("expected_heading")]
    rows, per_mode = [], {m: {"hit1": [], "hitk": [], "rr": [], "recall": []} for m in MODES}
    for s in scenarios:
        q = " ".join(filter(None, [s["request"]["product_description"], s["request"].get("intended_use")]))
        h = s["expected_heading"]
        want = [c for c in s["supporting_clause_ids"] if not c.startswith(("GRI-", "EXP-"))]
        row = {"id": s["id"], "heading": h}
        for mode in MODES:
            r = requests.post(f"{args.retriever}/search", json={"query": q, "k": args.k, "mode": mode}, timeout=30)
            ids = [p["clause_id"] for p in r.json()["passages"]]
            ranks = [i for i, c in enumerate(ids) if c == f"HDG-{h}" or c.startswith(f"TL-{h}")]
            rank = ranks[0] + 1 if ranks else None
            rec = len([c for c in want if c in ids]) / len(want) if want else None
            per_mode[mode]["hit1"].append(1.0 if rank == 1 else 0.0)
            per_mode[mode]["hitk"].append(1.0 if rank else 0.0)
            per_mode[mode]["rr"].append(1.0 / rank if rank else 0.0)
            if rec is not None:
                per_mode[mode]["recall"].append(rec)
            row[mode] = {"rank": rank, "top3": ids[:3]}
        rows.append(row)
    summary = {m: {"hit@1": round(statistics.fmean(v["hit1"]), 3), f"hit@{args.k}": round(statistics.fmean(v["hitk"]), 3),
                   "mrr": round(statistics.fmean(v["rr"]), 3),
                   f"recall@{args.k}": round(statistics.fmean(v["recall"]), 3) if v["recall"] else None}
               for m, v in per_mode.items()}
    out = HERE / "results" / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_retrieval"
    out.mkdir(parents=True, exist_ok=True)
    (out / "retrieval_summary.json").write_text(json.dumps({"k": args.k, "n": len(rows), "summary": summary,
                                                            "rows": rows}, indent=2), encoding="utf-8")
    md = [f"# Retrieval-only evaluation (k={args.k}, {len(rows)} scenarios with an expected heading)", "",
          "| Mode | hit@1 | hit@k | MRR | recall@k |", "|---|---|---|---|---|"]
    for m in MODES:
        v = summary[m]
        md.append(f"| {m} | {v['hit@1']} | {v[f'hit@{args.k}']} | {v['mrr']} | {v[f'recall@{args.k}']} |")
    md += ["", "| id | expected | dense rank | keyword rank | hybrid rank | dense top-3 |", "|---|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['id']} | {r['heading']} | {r['dense']['rank']} | {r['keyword']['rank']} | "
                  f"{r['hybrid']['rank']} | {', '.join(r['dense']['top3'])} |")
    (out / "retrieval_summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md[:7]))
    print(f"\nwritten to {out}")


if __name__ == "__main__":
    main()
