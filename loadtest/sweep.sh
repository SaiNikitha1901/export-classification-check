#!/usr/bin/env bash
# Concurrency sweep (D6). Usage: loadtest/sweep.sh <label> [users...]   e.g. loadtest/sweep.sh workers1 1 5 10 20
# Run from the repo root with the stack up and LLM_BASE_URL pointing at llm-stub.
set -euo pipefail
label=${1:?label}; shift
users=${*:-1 5 10 20 40 80}
run_time=${RUN_TIME:-3m}
for u in $users; do
  echo "== $label: $u users for $run_time"
  docker compose --profile loadtest run --rm -e CACHE_MODE="${CACHE_MODE:-unique}" locust \
    -f locustfile.py --headless -u "$u" -r "$u" --run-time "$run_time" --host http://api:8000 \
    --csv "results/${label}_u${u}" --only-summary || true
done
python3 loadtest/summarize.py "$label"
