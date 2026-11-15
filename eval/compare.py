"""Compare two evaluation runs (for BEFORE_AFTER.md and PROMPT_COMPARISON.md).

  python eval/compare.py eval/results/<before_dir> eval/results/<after_dir> [--title "..."]

Prints a markdown table: every quality, task and cost metric before, after, and the change.
For hallucination rate, latency and cost, lower is better; for everything else, higher is better.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

LOWER_IS_BETTER = {"hallucination_rate", "mean_latency_ms", "mean_cost_usd", "cost_per_100_runs_usd",
                   "mean_tool_calls", "mean_prompt_tokens"}


def load(d: str) -> dict:
    return json.loads((Path(d) / "summary.json").read_text(encoding="utf-8"))


def val(v):
    return v[0] if isinstance(v, list) else v


def rows(a: dict, b: dict):
    for group in ("quality", "task", "cost"):
        for k in a[group]:
            x, y = val(a[group][k]), val(b[group].get(k))
            if x is None and y is None:
                continue
            delta = None if x is None or y is None else round(y - x, 4)
            better = None
            if delta not in (None, 0) and not k.endswith("_runs"):   # *_runs are coverage counts, not scores
                better = (delta < 0) if k in LOWER_IS_BETTER else (delta > 0)
            yield group, k, x, y, delta, better


def table(a: dict, b: dict, la: str, lb: str) -> str:
    f = lambda v: "n/a" if v is None else (f"{v:.3f}" if isinstance(v, float) else str(v))  # noqa: E731
    out = [f"| Group | Metric | {la} | {lb} | Change | Better? |", "|---|---|---|---|---|---|"]
    for g, k, x, y, d, better in rows(a, b):
        sign = "" if d is None else ("+" if d > 0 else "")
        out.append(f"| {g} | {k} | {f(x)} | {f(y)} | {sign}{f(d)} | "
                   f"{'' if better is None else ('yes' if better else 'no')} |")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("before")
    ap.add_argument("after")
    ap.add_argument("--title", default="Comparison")
    args = ap.parse_args()
    a, b = load(args.before), load(args.after)
    la, lb = a["meta"]["label"], b["meta"]["label"]
    print(f"## {args.title}\n")
    print(f"- `{la}`: {Path(args.before).name} (judge `{a['meta']['judge']}`, prompts "
          f"{', '.join(a['meta']['prompt_versions'])}, search override `{a['meta']['search_mode_override']}`)")
    print(f"- `{lb}`: {Path(args.after).name} (judge `{b['meta']['judge']}`, prompts "
          f"{', '.join(b['meta']['prompt_versions'])}, search override `{b['meta']['search_mode_override']}`)\n")
    print(table(a, b, la, lb))


if __name__ == "__main__":
    main()
