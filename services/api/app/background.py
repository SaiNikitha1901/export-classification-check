"""Housekeeping loop inside the API process (runs every 2 s):

1. watchdog  - a run whose RQ job died, was lost or never finished is marked 'failed', so a
               client never waits forever and never gets a half-finished answer (A5).
2. cache fill - completed runs are copied into the whole-run cache (D7).
3. callbacks - runs submitted with callback_url get their final result POSTed, with
               bounded retries and exponential backoff (A4).
"""
from __future__ import annotations

import logging
import threading

import requests
from rq.job import Job, JobStatus

from app import db, metrics, runcache
from app.config import settings
from ecs_common import CORRELATION_HEADER, bind

log = logging.getLogger("background")

FINAL = ("completed", "escalated", "degraded", "failed")
CALLBACK_MAX_ATTEMPTS = 5
WATCHDOG_GRACE_S = 30


def _watchdog(redis_conn) -> None:
    stale = db.fetch_all(
        "SELECT run_id, correlation_id FROM runs WHERE status IN ('queued','running') AND cache_hit = false "
        "AND created_at < now() - make_interval(secs => %s) LIMIT 100",
        (settings.run_timeout_s + WATCHDOG_GRACE_S,),
    )
    for row in stale:
        run_id = str(row["run_id"])
        try:
            job = Job.fetch(run_id, connection=redis_conn)
            status = job.get_status()
        except Exception:
            job, status = None, None
        if status in (JobStatus.QUEUED, JobStatus.STARTED, JobStatus.DEFERRED, JobStatus.SCHEDULED):
            continue  # still legitimately waiting or running (e.g. a long queue under load)
        reason = f"run did not reach a final status (job status: {status or 'missing'})"
        updated = db.execute(
            "UPDATE runs SET status='failed', error=%s, updated_at=now() "
            "WHERE run_id=%s AND status IN ('queued','running')",
            (reason, run_id),
        )
        if updated:
            metrics.runs_timed_out.inc()
            with bind(run_id=run_id, correlation_id=row["correlation_id"]):
                log.warning(reason, extra={"event": "run_watchdog_failed"})


def _fill_cache(redis_conn) -> None:
    rows = db.fetch_all(
        "SELECT run_id, cache_key, result FROM runs WHERE status='completed' AND cache_key IS NOT NULL "
        "AND NOT cache_stored AND NOT cache_hit AND result IS NOT NULL LIMIT 50"
    )
    for row in rows:
        runcache.put(redis_conn, row["cache_key"], {"run_id": str(row["run_id"]), "result": row["result"]},
                     settings.run_cache_ttl_s)
        db.execute("UPDATE runs SET cache_stored=true WHERE run_id=%s", (row["run_id"],))


def _deliver_callbacks() -> None:
    with db.conn() as c:
        rows = c.execute(
            "SELECT run_id, correlation_id, status, result, callback_url, callback_attempts FROM runs "
            "WHERE callback_state='pending' AND status = ANY(%s) "
            "AND (callback_next_at IS NULL OR callback_next_at <= now()) "
            "LIMIT 20 FOR UPDATE SKIP LOCKED",
            (list(FINAL),),
        ).fetchall()
        for row in rows:
            attempts = row["callback_attempts"] + 1
            body = {"run_id": str(row["run_id"]), "status": row["status"], "result": row["result"]}
            try:
                resp = requests.post(row["callback_url"], json=body, timeout=5,
                                     headers={CORRELATION_HEADER: row["correlation_id"] or ""})
                ok = 200 <= resp.status_code < 300
            except requests.RequestException:
                ok = False
            if ok:
                state = "delivered"
            elif attempts >= CALLBACK_MAX_ATTEMPTS:
                state = "failed"
            else:
                state = "pending"
            c.execute(
                "UPDATE runs SET callback_state=%s, callback_attempts=%s, "
                "callback_next_at = now() + make_interval(secs => %s) WHERE run_id=%s",
                (state, attempts, 2 ** attempts, row["run_id"]),
            )
            metrics.callbacks.labels(outcome=state if state != "pending" else "retry").inc()


def _loop(stop: threading.Event, redis_conn) -> None:
    while not stop.wait(2.0):
        for task in (lambda: _watchdog(redis_conn), lambda: _fill_cache(redis_conn), _deliver_callbacks):
            try:
                task()
            except Exception:
                log.exception("background task failed", extra={"event": "background_error"})


def start(redis_conn) -> threading.Event:
    stop = threading.Event()
    threading.Thread(target=_loop, args=(stop, redis_conn), name="housekeeping", daemon=True).start()
    return stop
