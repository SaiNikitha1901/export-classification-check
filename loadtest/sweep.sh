#!/usr/bin/env bash
# Concurrency sweep (D6). Usage: loadtest/sweep.sh <label> [users...]   e.g. loadtest/sweep.sh workers1 1 5 10 20
# Run from the repo root with the stack up and LLM_BASE_URL pointing at llm-stub.
set -euo pipefail
label=${1:?label}; shift
users=${*:-1 5 10 20 40 80}
run_time=${RUN_TIME:-3m}
api_port=${API_HOST_PORT:-8000}
drain() {  # each step starts from an empty queue, so a backlog never carries into the next step
  until python3 -c "import json,sys,urllib.request; s=json.load(urllib.request.urlopen('http://localhost:$api_port/admin/stats')); sys.exit(0 if s['queue_length']==0 else 1)" 2>/dev/null \
     && [ "$(docker compose exec -T postgres psql -U "${POSTGRES_USER:-ecs}" -d "${POSTGRES_DB:-ecs}" -tAc "select count(*) from runs where status in ('queued','running')")" = "0" ]; do
    sleep 5
  done
}
for u in $users; do
  drain
  echo "== $label: $u users for $run_time"
  docker compose --profile loadtest run --rm -e CACHE_MODE="${CACHE_MODE:-unique}" locust \
    -f locustfile.py --headless -u "$u" -r "$u" --run-time "$run_time" --host http://api:8000 \
    --csv "results/${label}_u${u}" --only-summary --stop-timeout "${STOP_TIMEOUT:-300}" || true
done
python3 loadtest/summarize.py "$label"
