"""Prometheus metrics for the API (names from shared contract A.9)."""
from __future__ import annotations

from prometheus_client import Counter, Histogram
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import REGISTRY, Collector

SERVICE = "api"
LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)

http_requests = Counter("ecs_http_requests_total", "HTTP requests", ["service", "route", "code"])
http_latency = Histogram("ecs_http_latency_seconds", "HTTP latency", ["service", "route"], buckets=LATENCY_BUCKETS)
quarantined = Counter("ecs_quarantine_total", "Requests rejected at the boundary and quarantined")
rate_limited = Counter("ecs_rate_limited_total", "Requests rejected by the per-client rate limit")
cache_hits = Counter("ecs_cache_hits_total", "Cache hits", ["cache"])
cache_misses = Counter("ecs_cache_misses_total", "Cache misses", ["cache"])
feedback_total = Counter("ecs_feedback_total", "Feedback received", ["satisfactory"])
runs_submitted = Counter("ecs_runs_submitted_total", "Runs accepted and enqueued")
callbacks = Counter("ecs_callbacks_total", "Callback deliveries", ["outcome"])
runs_timed_out = Counter("ecs_runs_timed_out_total", "Runs marked failed by the API watchdog")


class QueueCollector(Collector):
    """Reads queue depth and live worker count from Redis at scrape time (for bottleneck analysis)."""

    def __init__(self, redis_conn, queue_name: str) -> None:
        self.redis = redis_conn
        self.queue_name = queue_name

    def collect(self):
        from rq import Queue, Worker

        depth = GaugeMetricFamily("ecs_queue_depth", "Jobs waiting in the run queue")
        workers = GaugeMetricFamily("ecs_rq_workers", "Live RQ workers")
        try:
            q = Queue(self.queue_name, connection=self.redis)
            depth.add_metric([], len(q))
            workers.add_metric([], Worker.count(connection=self.redis))
        except Exception:  # Redis down: report nothing rather than fail the scrape
            return
        yield depth
        yield workers


def register_queue_collector(redis_conn, queue_name: str) -> None:
    REGISTRY.register(QueueCollector(redis_conn, queue_name))
