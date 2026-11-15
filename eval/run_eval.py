"""Batch evaluation runner (L3). Submits every scenario to the public API, polls until each run finishes,
fetches its trace, scores it with eval/metrics.py, and writes eval/results/<UTC time>_<label>/.

Run it inside the stack (the retriever image has every dependency):
  docker compose run --rm -v "$PWD/eval:/srv/eval" retriever python eval/run_eval.py --label baseline --fresh

  --fresh        clear the API's whole-run cache first, so every scenario really runs (needed for before/after)
  --only S01,S02 run a subset
  --no-db        do not write eval_scores rows
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from judge import Judge  # noqa: E402
from metrics import score_run  # noqa: E402

HERE = Path(__file__).parent
FINAL = {"completed", "escalated", "degraded", "failed"}


class Corpus:
    """Clause and policy lookups against the retriever, memoised for the whole batch."""

    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self._clauses: dict[str, object] = {}
        self._policy: dict[str, object] = {}

    def resolve(self, clause_id: str):
        if clause_id not in self._clauses:
            r = requests.get(f"{self.base}/clause/{clause_id}", timeout=10)
            self._clauses[clause_id] = r.json()["passages"] if r.status_code == 200 else None
        return self._clauses[clause_id]

    def policy_clauses(self, code: str):
        if code not in self._policy:
            r = requests.get(f"{self.base}/policy/{code}", timeout=10)
            self._policy[code] = {p["clause_id"] for p in r.json()["passages"]} if r.status_code == 200 else None
        return self._policy[code]

    def info(self) -> dict:
        """Which index a batch ran against. Only identifying fields: model ids stay out of committed results (D4)."""
        try:
            i = requests.get(f"{self.base}/index/info", timeout=10).json()
        except Exception:
            return {}
        return {k: i.get(k) for k in ("built_at", "collection", "chunk_count", "chunking", "search_mode_override")}


def submit(api: str, s: dict, client: str, timeout_s: float) -> dict:
    rec = {"scenario_id": s["id"], "category": s["category"]}
    t0 = time.time()
    for _ in range(10):
        r = requests.post(f"{api}/runs", json=s["request"], timeout=30,
                          headers={"X-Client-Id": client, "X-Correlation-ID": f"eval-{s['id']}-{int(t0)}"})
        if r.status_code != 429:
            break
        time.sleep(float(r.headers.get("Retry-After", "5")))
    rec["http"] = r.status_code
    body = r.json()
    if r.status_code != 202:
        rec["response"] = body
        return rec
    run_id = body["run_id"]
    rec["run_id"], rec["cache_hit"] = run_id, body.get("cache_hit", False)
    while time.time() - t0 < timeout_s:
        run = requests.get(f"{api}/runs/{run_id}", timeout=30).json()
        if run["status"] in FINAL:
            break
        time.sleep(2)
    rec["status"] = run["status"]
    rec["result"] = run.get("result")
    rec["wall_s"] = round(time.time() - t0, 2)
    trace = requests.get(f"{api}/runs/{run_id}/trace", timeout=30).json()
    rec["steps"] = trace.get("steps", []) if isinstance(trace, dict) else trace
    return rec


def task_scores(s: dict, rec: dict) -> dict:
    t: dict = {"boundary_ok": rec["http"] == s["expected_http"]}
    if s["expected_http"] != 202 or rec["http"] != 202:
        return t
    res = rec.get("result") or {}
    route = res.get("route")
    t["route_ok"] = route == s["expected_route"]
    if s["expected_heading"] is not None:
        t["heading_ok"] = res.get("heading") == s["expected_heading"]
    if s["expected_hs_code"] is not None:
        t["code_ok"] = res.get("proposed_hs_code") == s["expected_hs_code"]
    t["escalated"] = route == "specialist-classification-review"
    if s.get("expected_injection"):
        t["injection_detected"] = bool((res.get("guardrails") or {}).get("injection_detected"))
    if route == "clear-for-filing":
        # A confident answer is only "right" if both the route and the code match the reference.
        t["clear_correct"] = s["expected_route"] == "clear-for-filing" and res.get("proposed_hs_code") == s[
            "expected_hs_code"]
    return t


def mean(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.fmean(xs), 4) if xs else None


def summarise(records: list[dict], scenarios: dict) -> dict:
    run_recs = [r for r in records if r.get("result")]
    m = lambda name, key="value": mean([r["metrics"][name].get(key) for r in run_recs if "metrics" in r])  # noqa: E731
    task = [r["task"] for r in records]
    frac = lambda key: (mean([1.0 if t[key] else 0.0 for t in task if key in t]),  # noqa: E731
                        sum(1 for t in task if key in t))
    tp = sum(1 for r in records if r["task"].get("escalated") and scenarios[r["scenario_id"]]["expected_escalation"])
    fp = sum(1 for r in records if r["task"].get("escalated") and not scenarios[r["scenario_id"]]["expected_escalation"])
    fn = sum(1 for r in records if "escalated" in r["task"] and not r["task"]["escalated"]
             and scenarios[r["scenario_id"]]["expected_escalation"])
    usage = [(r["result"].get("usage") or {}) for r in run_recs]
    return {
        "scenarios": len(records),
        "runs_with_result": len(run_recs),
        "quality": {
            "groundedness": m("groundedness"),
            "groundedness_runs": sum(1 for r in run_recs
                                     if (r.get("metrics") or {}).get("groundedness", {}).get("value") is not None),
            "context_relevance": m("context_relevance"),
            "context_recall": m("context_relevance", "recall"),
            "faithfulness": m("faithfulness"),
            "hallucination_rate": m("hallucination"),
        },
        "task": {
            "route_accuracy": frac("route_ok"),
            "heading_accuracy": frac("heading_ok"),
            "hs_code_accuracy": frac("code_ok"),
            "clear_for_filing_precision": frac("clear_correct"),
            "escalation_precision": round(tp / (tp + fp), 4) if tp + fp else None,
            "escalation_recall": round(tp / (tp + fn), 4) if tp + fn else None,
            "injection_detection": frac("injection_detected"),
            "boundary_accuracy": frac("boundary_ok"),
        },
        "cost": {
            "mean_latency_ms": mean([u.get("latency_ms") for u in usage]),
            "mean_cost_usd": mean([u.get("cost_usd") for u in usage]),
            "cost_per_100_runs_usd": round(100 * (mean([u.get("cost_usd") for u in usage]) or 0), 4),
            "mean_tool_calls": mean([u.get("tool_calls") for u in usage]),
            "mean_prompt_tokens": mean([u.get("prompt_tokens") for u in usage]),
        },
    }


def write_db(records: list[dict], label: str, judge_label: str) -> int:
    dsn = os.getenv("POSTGRES_DSN")
    if not dsn:
        return 0
    import psycopg

    rows = []
    for r in records:
        for name in ("groundedness", "context_relevance", "faithfulness", "hallucination"):
            v = (r.get("metrics") or {}).get(name, {}).get("value")
            if v is not None:
                rows.append((r.get("run_id"), "batch", r["scenario_id"], name, v, f"{label}|{judge_label}"))
        rec = (r.get("metrics") or {}).get("context_relevance", {}).get("recall")
        if rec is not None:
            rows.append((r.get("run_id"), "batch", r["scenario_id"], "context_recall", rec, f"{label}|{judge_label}"))
    with psycopg.connect(dsn) as conn:
        conn.cursor().executemany("INSERT INTO eval_scores (run_id, source, scenario_id, metric, value, label) "
                                  "VALUES (%s, %s, %s, %s, %s, %s)", rows)
    return len(rows)


def report_md(label: str, meta: dict, summary: dict, records: list[dict]) -> str:
    q, t, c = summary["quality"], summary["task"], summary["cost"]
    f = lambda v: "n/a" if v is None else (f"{v:.3f}" if isinstance(v, float) else str(v))  # noqa: E731
    lines = [f"# Evaluation run `{label}`", "",
             f"- When: {meta['finished_at']} | scenarios: {summary['scenarios']} | runs with a result: "
             f"{summary['runs_with_result']}",
             f"- Prompt versions seen: {', '.join(meta['prompt_versions']) or 'n/a'} | judge: `{meta['judge']}` | "
             f"retriever: `{meta['index'].get('collection')}` built {meta['index'].get('built_at')}, "
             f"search mode override: `{meta['search_mode_override'] or 'none (hybrid)'}`", "",
             "## Quality metrics (definitions in eval/METRICS.md)", "", "| Metric | Value |", "|---|---|"]
    lines += [f"| {k} | {f(v)} |" for k, v in q.items()]
    lines += ["", "## Task metrics", "", "| Metric | Value | n |", "|---|---|---|"]
    for k, v in t.items():
        lines.append(f"| {k} | {f(v[0]) if isinstance(v, tuple) else f(v)} | {v[1] if isinstance(v, tuple) else ''} |")
    lines += ["", "## Cost and latency", "", "| Metric | Value |", "|---|---|"] + [f"| {k} | {f(v)} |"
                                                                                    for k, v in c.items()]
    lines += ["", "## Per scenario", "",
              "| id | category | http | route | heading | code | route ok | G | CR | recall | F | H |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in records:
        res, mt, tk = r.get("result") or {}, r.get("metrics") or {}, r["task"]
        g = lambda n, k="value": f(mt.get(n, {}).get(k)) if mt else ""  # noqa: E731
        lines.append(f"| {r['scenario_id']} | {r['category']} | {r['http']} | {res.get('route', '')} | "
                     f"{res.get('heading') or ''} | {res.get('proposed_hs_code') or ''} | "
                     f"{'yes' if tk.get('route_ok') else ('' if 'route_ok' not in tk else 'NO')} | {g('groundedness')} | "
                     f"{g('context_relevance')} | {g('context_relevance', 'recall')} | {g('faithfulness')} | "
                     f"{g('hallucination')} |")
    probs = [(r["scenario_id"], p) for r in records for p in (r.get("metrics") or {}).get("hallucination", {})
             .get("problems", [])]
    if probs:
        lines += ["", "## Hallucination findings", ""] + [f"- {sid}: {p}" for sid, p in probs]
    return "\n".join(lines) + "\n"


def rescore(results_dir: Path, args) -> int:
    """Recompute every metric of a finished batch with the current metric code, re-reading each run's trace
    from the API (runs persist in Postgres). Used so that all compared batches are scored by identical code."""
    summary_old = json.loads((results_dir / "summary.json").read_text(encoding="utf-8"))
    label = summary_old["meta"]["label"]
    scenarios = {json.loads(l)["id"]: json.loads(l)
                 for l in Path(args.scenarios).read_text(encoding="utf-8").splitlines() if l.strip()}
    corpus, judge = Corpus(args.retriever), Judge()
    records = [json.loads(l) for l in (results_dir / "runs.jsonl").read_text(encoding="utf-8").splitlines() if l]
    for rec in records:
        s = scenarios[rec["scenario_id"]]
        if rec.get("run_id") and rec.get("result"):
            trace = requests.get(f"{args.api}/runs/{rec['run_id']}/trace", timeout=30).json()
            rec["steps"] = trace.get("steps", []) if isinstance(trace, dict) else trace
            rec["metrics"] = score_run(s["request"], rec["result"], rec["steps"], corpus.resolve, judge,
                                       s.get("supporting_clause_ids"), corpus.policy_clauses)
        rec["task"] = task_scores(s, rec) if rec.get("http") else {"boundary_ok": False}
    summary = summarise(records, scenarios)
    meta = {**summary_old["meta"], "judge": judge.label, "rescored_at":
            datetime.now(timezone.utc).isoformat(timespec="seconds")}
    _write(results_dir, label, meta, summary, records)
    n = 0
    if not args.no_db and os.getenv("POSTGRES_DSN"):
        import psycopg

        with psycopg.connect(os.environ["POSTGRES_DSN"]) as conn:
            conn.execute("DELETE FROM eval_scores WHERE source = 'batch' AND label LIKE %s", (f"{label}|%",))
        n = write_db(records, label, judge.label)
    print(json.dumps({"rescored": str(results_dir), "db_rows": n, **summary}, indent=2))
    return 0


def _write(out: Path, label: str, meta: dict, summary: dict, records: list[dict]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with (out / "runs.jsonl").open("w", encoding="utf-8") as fh:
        for r in records:
            slim = {k: v for k, v in r.items() if k != "steps"}
            slim["step_count"] = len(r.get("steps", [])) or r.get("step_count", 0)
            fh.write(json.dumps(slim, ensure_ascii=False) + "\n")
    (out / "summary.json").write_text(json.dumps({"meta": meta, **summary}, indent=2, ensure_ascii=False),
                                      encoding="utf-8")
    (out / "summary.md").write_text(report_md(label, meta, summary, records), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label")
    ap.add_argument("--rescore", help="results folder of a finished batch to re-score with the current metric code")
    ap.add_argument("--api", default=os.getenv("EVAL_API_URL", "http://api:8000"))
    ap.add_argument("--retriever", default=os.getenv("RETRIEVER_URL", "http://retriever:8001"))
    ap.add_argument("--scenarios", default=str(HERE / "scenarios.jsonl"))
    ap.add_argument("--only", default="")
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--timeout", type=float, default=240)
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--no-db", action="store_true")
    args = ap.parse_args()
    if args.rescore:
        return rescore(Path(args.rescore), args)
    if not args.label:
        ap.error("--label is required (unless --rescore)")

    scenarios = [json.loads(l) for l in Path(args.scenarios).read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.only:
        keep = set(args.only.split(","))
        scenarios = [s for s in scenarios if s["id"] in keep]
    by_id = {s["id"]: s for s in scenarios}
    if args.fresh and os.getenv("REDIS_URL"):
        import redis

        rc = redis.Redis.from_url(os.environ["REDIS_URL"])
        n = sum(1 for k in rc.scan_iter("runcache:*", count=500) if rc.delete(k))
        print(f"cleared {n} whole-run cache entries")

    corpus, judge = Corpus(args.retriever), Judge()
    client = f"eval-{args.label}"
    print(f"{len(scenarios)} scenarios, judge={judge.label}, api={args.api}")
    records: list[dict] = []
    with cf.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futs = {pool.submit(submit, args.api, s, client, args.timeout): s for s in scenarios}
        for fut in cf.as_completed(futs):
            s = futs[fut]
            try:
                rec = fut.result()
            except Exception as e:  # keep going: one broken scenario must not lose the batch
                rec = {"scenario_id": s["id"], "category": s["category"], "http": None, "error": repr(e)}
            if rec.get("result"):
                rec["metrics"] = score_run(s["request"], rec["result"], rec.get("steps", []), corpus.resolve, judge,
                                           s.get("supporting_clause_ids"), corpus.policy_clauses)
            rec["task"] = task_scores(s, rec) if rec.get("http") else {"boundary_ok": False}
            records.append(rec)
            res = rec.get("result") or {}
            print(f"  {s['id']:4} http={rec.get('http')} status={rec.get('status', '-'):9} "
                  f"route={res.get('route', '-')} code={res.get('proposed_hs_code')} "
                  f"route_ok={rec['task'].get('route_ok')}", flush=True)
    records.sort(key=lambda r: r["scenario_id"])

    summary = summarise(records, by_id)
    meta = {"label": args.label, "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "judge": judge.label, "judge_llm_calls": judge.calls, "judge_cache_hits": judge.cache_hits,
            "index": corpus.info(), "search_mode_override": os.getenv("FORCE_SEARCH_MODE") or None,
            "prompt_versions": sorted({(r.get("result") or {}).get("prompt_version") for r in records} - {None})}
    out = HERE / "results" / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{args.label}"
    _write(out, args.label, meta, summary, records)
    n = 0 if args.no_db else write_db(records, args.label, judge.label)
    print(json.dumps({"results": str(out), "db_rows": n, **summary}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
