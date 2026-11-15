"""Live quality monitoring (L6, automatic scoring). A background loop inside the retriever container:

1. Every LIVE_SCORING_INTERVAL_S, read runs that finished since the last look (Postgres `runs`).
2. Keep a deterministic ~LIVE_SCORING_SAMPLE_RATE sample (hash of run_id), skipping whole-run cache hits.
3. Score each sampled run with the SAME metric code as the batch runner (eval/metrics.py). Live runs have no
   reference answer, so only groundedness, context relevance, faithfulness and hallucination are scored.
4. Write one eval_scores row per metric (source='live') and refresh the gauge ecs_eval_score{metric,source}
   for both 'live' (mean of the last hour) and 'batch' (latest batch run), which Grafana charts over time.
"""
from __future__ import annotations

import hashlib
import logging
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

from prometheus_client import Gauge

log = logging.getLogger("live_scoring")
eval_score = Gauge("ecs_eval_score", "Evaluation score (mean)", ["metric", "source"])
live_scored = Gauge("ecs_eval_live_scored_runs", "Live runs scored since the retriever started")
METRICS = ("groundedness", "context_relevance", "faithfulness", "hallucination")


def _sampled(run_id: str, rate: float) -> bool:
    return int(hashlib.sha256(str(run_id).encode()).hexdigest()[:8], 16) % 10_000 < rate * 10_000


class LiveScorer(threading.Thread):
    def __init__(self, index, dsn: str) -> None:
        super().__init__(daemon=True, name="live-scorer")
        self.index, self.dsn = index, dsn
        self.rate = float(os.getenv("LIVE_SCORING_SAMPLE_RATE", "0.1"))
        self.interval = float(os.getenv("LIVE_SCORING_INTERVAL_S", "30"))
        self.watermark = datetime.now(timezone.utc) - timedelta(hours=1)
        self.scored = 0
        eval_dir = os.getenv("EVAL_DIR", "/srv/eval")
        if eval_dir not in sys.path:
            sys.path.insert(0, eval_dir)
        from judge import Judge
        from metrics import score_run

        self.judge, self.score_run = Judge(), score_run

    # lookups backed by the loaded index (no HTTP round-trip to ourselves)
    def _resolve(self, clause_id: str):
        try:
            return self.index.clause(clause_id) or None
        except Exception:
            return None

    def _policy(self, code: str):
        out = self.index.policy(code)
        return {p["clause_id"] for p in out["passages"]} if out else None

    def run(self) -> None:
        log.info("live scoring started", extra={"event": "live_scoring_start", "rate": self.rate,
                                                "judge": self.judge.label})
        while True:
            try:
                self.tick()
            except Exception:
                log.exception("live scoring tick failed", extra={"event": "live_scoring_error"})
            time.sleep(self.interval)

    def tick(self) -> None:
        import psycopg
        from psycopg.rows import dict_row

        if self.index.ensure_loaded() is None:
            return
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            rows = conn.execute(
                "SELECT run_id, request, result, updated_at, COALESCE(cache_hit, false) AS cache_hit FROM runs "
                "WHERE updated_at > %s AND status IN ('completed','escalated','degraded') AND result IS NOT NULL "
                # Batch-evaluation runs (client eval-*) are scored by eval/run_eval.py; live = real traffic only.
                "AND COALESCE(client_id, '') NOT LIKE 'eval-%%' "
                "ORDER BY updated_at LIMIT 200", (self.watermark,)).fetchall()
            for r in rows:
                self.watermark = max(self.watermark, r["updated_at"])
                if r["cache_hit"] or not _sampled(r["run_id"], self.rate):
                    continue
                done = conn.execute("SELECT 1 FROM eval_scores WHERE run_id = %s AND source = 'live' LIMIT 1",
                                    (r["run_id"],)).fetchone()
                if done:
                    continue
                steps = conn.execute("SELECT step_no, agent, kind, name, input, output, status FROM run_steps "
                                     "WHERE run_id = %s ORDER BY step_no", (r["run_id"],)).fetchall()
                scores = self.score_run(r["request"] or {}, r["result"], steps, self._resolve, self.judge,
                                        None, self._policy)
                for name in METRICS:
                    v = scores[name].get("value")
                    if v is not None:
                        conn.execute("INSERT INTO eval_scores (run_id, source, metric, value, label) "
                                     "VALUES (%s, 'live', %s, %s, %s)", (r["run_id"], name, v, self.judge.label))
                conn.commit()
                self.scored += 1
                live_scored.set(self.scored)
                log.info("live run scored", extra={"event": "live_scored", "run_id": str(r["run_id"]),
                                                   **{n: scores[n].get("value") for n in METRICS}})
            self._refresh_gauges(conn)

    def _refresh_gauges(self, conn) -> None:
        for row in conn.execute("SELECT metric, avg(value) AS v FROM eval_scores WHERE source = 'live' "
                                "AND scored_at > now() - interval '1 hour' GROUP BY metric").fetchall():
            eval_score.labels(row["metric"], "live").set(float(row["v"]))
        last = conn.execute("SELECT label FROM eval_scores WHERE source = 'batch' ORDER BY scored_at DESC "
                            "LIMIT 1").fetchone()
        if last:
            for row in conn.execute("SELECT metric, avg(value) AS v FROM eval_scores WHERE source = 'batch' "
                                    "AND label = %s GROUP BY metric", (last["label"],)).fetchall():
                eval_score.labels(row["metric"], "batch").set(float(row["v"]))


def start(index) -> None:
    dsn = os.getenv("POSTGRES_DSN")
    if os.getenv("LIVE_SCORING_ENABLED", "true").lower() != "true" or not dsn:
        log.info("live scoring disabled", extra={"event": "live_scoring_off"})
        return
    try:
        LiveScorer(index, dsn).start()
    except Exception:
        log.exception("live scoring could not start", extra={"event": "live_scoring_error"})
