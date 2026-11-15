"""Prometheus metrics for the retriever (names from shared contract A.9)."""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

SERVICE = "retriever"
LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)

http_requests = Counter("ecs_http_requests_total", "HTTP requests", ["service", "route", "code"])
http_latency = Histogram("ecs_http_latency_seconds", "HTTP latency", ["service", "route"], buckets=LATENCY_BUCKETS)
retrieval_latency = Histogram("ecs_retrieval_latency_seconds", "Search latency inside the retriever", ["mode"],
                              buckets=LATENCY_BUCKETS)
cache_hits = Counter("ecs_cache_hits_total", "Cache hits", ["cache"])
cache_misses = Counter("ecs_cache_misses_total", "Cache misses", ["cache"])
cache_errors = Counter("ecs_cache_errors_total", "Cache errors (Redis unreachable); the request still succeeds",
                       ["cache"])
index_chunks = Gauge("ecs_index_chunks", "Chunks in the active index")
index_built = Gauge("ecs_index_built_timestamp", "Unix time the active index content was built")
ingest_cps = Gauge("ecs_ingest_chunks_per_second", "Throughput of the last real ingestion build (parse + embed)")
index_loaded = Gauge("ecs_index_loaded", "1 when the retriever has an index loaded")
