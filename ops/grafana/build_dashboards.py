"""Generates the provisioned Grafana dashboards (A6, D5, L6).

Edit the panel lists below and run:  python3 ops/grafana/build_dashboards.py
(stdlib only). The JSON files in ops/grafana/dashboards/ are committed so a clean
`docker compose up` shows the dashboards without any clicking.
"""
import json
from pathlib import Path

OUT = Path(__file__).parent / "dashboards"
DS = {"type": "prometheus", "uid": "prometheus"}


def panel(title, exprs, unit="short", kind="timeseries", desc="", legend=None, w=12, h=8):
    if isinstance(exprs, str):
        exprs = [exprs]
    legends = legend if isinstance(legend, list) else [legend] * len(exprs)
    p = {
        "type": kind,
        "title": title,
        "description": desc,
        "datasource": DS,
        "gridPos": {"w": w, "h": h},
        "fieldConfig": {"defaults": {"unit": unit}, "overrides": []},
        "options": {"legend": {"displayMode": "table", "placement": "bottom", "calcs": ["lastNotNull", "max"]}},
        "targets": [
            {"refId": chr(65 + i), "expr": e, "datasource": DS, **({"legendFormat": lg} if lg else {})}
            for i, (e, lg) in enumerate(zip(exprs, legends))
        ],
    }
    if kind == "stat":
        p["options"] = {"reduceOptions": {"calcs": ["lastNotNull"]}, "colorMode": "value"}
    return p


def row(title):
    return {"type": "row", "title": title, "collapsed": False, "gridPos": {"w": 24, "h": 1}, "panels": []}


def layout(panels):
    x = y = row_h = 0
    for i, p in enumerate(panels):
        p["id"] = i + 1
        g = p["gridPos"]
        if p["type"] == "row" or x + g["w"] > 24:
            x, y = 0, y + row_h
            row_h = 0
        g["x"], g["y"] = x, y
        x += g["w"]
        row_h = max(row_h, g["h"])
        if p["type"] == "row":
            x, y, row_h = 0, y + 1, 0
    return panels


def dashboard(uid, title, panels, refresh="10s"):
    return {
        "uid": uid,
        "title": title,
        "tags": ["ecs"],
        "timezone": "browser",
        "schemaVersion": 39,
        "refresh": refresh,
        "time": {"from": "now-30m", "to": "now"},
        "panels": layout(panels),
    }


Q95 = "histogram_quantile(0.95, sum by (le{by}) (rate({m}_bucket[2m])))"
Q50 = "histogram_quantile(0.50, sum by (le{by}) (rate({m}_bucket[2m])))"


def q(quant, metric, by=""):
    return quant.format(m=metric, by=f", {by}" if by else "")


service_health = dashboard("ecs-service-health", "ECS · Service health", [
    row("Traffic & latency (D5)"),
    panel("Throughput (requests/s) per service", "sum by (service) (rate(ecs_http_requests_total[1m]))", "reqps",
          legend="{{service}}"),
    panel("Error rate (5xx share) per service",
          'sum by (service) (rate(ecs_http_requests_total{code=~"5.."}[2m])) / '
          "sum by (service) (rate(ecs_http_requests_total[2m]))", "percentunit", legend="{{service}}"),
    panel("HTTP latency p50 / p95 per service",
          [q(Q50, "ecs_http_latency_seconds", "service"), q(Q95, "ecs_http_latency_seconds", "service")], "s",
          legend=["p50 {{service}}", "p95 {{service}}"]),
    panel("Complete run time p50 / p95 (submission → final result, D6)",
          [q(Q50, "ecs_run_e2e_seconds"), q(Q95, "ecs_run_e2e_seconds")], "s", legend=["p50", "p95"]),
    panel("Availability (scrape up) per target", "up", "percentunit", legend="{{job}} {{instance}}",
          desc="1 = Prometheus can scrape the service"),
    panel("Availability over 1h", "avg by (job) (avg_over_time(up[1h]))", "percentunit", kind="stat",
          legend="{{job}}"),
    row("Queue & capacity (bottleneck hunting)"),
    panel("Queue depth / live workers", ["ecs_queue_depth", "ecs_rq_workers"], legend=["queued jobs", "workers"]),
    panel("Runs submitted, quarantined, rate-limited (per min)",
          ["sum(rate(ecs_runs_submitted_total[1m])) * 60", "sum(rate(ecs_quarantine_total[1m])) * 60",
           "sum(rate(ecs_rate_limited_total[1m])) * 60"], legend=["submitted", "quarantined", "rate limited"]),
    row("Resources per container (docker-exporter)"),
    panel("CPU (cores) per container", "ecs_container_cpu_cores", legend="{{name}}"),
    panel("Memory per container", "ecs_container_memory_bytes", "bytes", legend="{{name}}"),
    panel("Containers running", "ecs_container_up", legend="{{name}}", desc="1 = running"),
])

agents = dashboard("ecs-agents", "ECS · Agents (A6)", [
    row("Per-agent outcomes"),
    panel("Task success rate per agent",
          'sum by (agent) (increase(ecs_agent_runs_total{outcome="success"}[15m])) / '
          "sum by (agent) (increase(ecs_agent_runs_total[15m]))", "percentunit", legend="{{agent}}",
          desc="outcome label values: success | escalated | degraded | failed"),
    panel("Runs per outcome per agent (per min)", "sum by (agent, outcome) (rate(ecs_agent_runs_total[1m])) * 60",
          legend="{{agent}} {{outcome}}"),
    panel("Steps per run (avg) per agent",
          "sum by (agent) (rate(ecs_agent_steps_per_run_sum[15m])) / sum by (agent) (rate(ecs_agent_steps_per_run_count[15m]))",
          legend="{{agent}}"),
    panel("Tool calls per run per agent",
          "sum by (agent) (increase(ecs_agent_tool_calls_total[15m])) / sum by (agent) (increase(ecs_agent_runs_total[15m]))",
          legend="{{agent}}"),
    row("Latency"),
    panel("End-to-end run latency p50 / p95", [q(Q50, "ecs_run_e2e_seconds"), q(Q95, "ecs_run_e2e_seconds")], "s",
          legend=["p50", "p95"]),
    panel("Per-step latency p95", q(Q95, "ecs_agent_step_latency_seconds", "agent, step"), "s",
          legend="{{agent}} / {{step}}"),
    row("Reliability"),
    panel("LLM retry rate (retries per run) per agent",
          "sum by (agent) (increase(ecs_llm_retries_total[15m])) / sum by (agent) (increase(ecs_agent_runs_total[15m]))",
          legend="{{agent}}"),
    panel("Circuit breaker state (0 closed, 1 half-open, 2 open)", "ecs_circuit_breaker_state",
          legend="{{provider}}"),
    panel("Worker container uptime", 'time() - process_start_time_seconds{job="agent-worker"}', "s",
          legend="{{instance}}"),
    panel("Uptime per container", "ecs_container_uptime_seconds", "s", legend="{{name}}"),
])

quality = dashboard("ecs-quality-cost", "ECS · Quality & cost (L5, L6, D7)", [
    row("Quality over time"),
    panel("Evaluation scores (live vs batch)", "ecs_eval_score", "percentunit", legend="{{source}} {{metric}}"),
    panel("Feedback: % satisfactory",
          'sum(ecs_feedback_total{satisfactory="true"}) / sum(ecs_feedback_total)', "percentunit", kind="stat"),
    row("Cost & tokens"),
    panel("Cost per run (USD, 1h window)",
          "sum(increase(ecs_llm_cost_usd_total[1h])) / sum(increase(ecs_run_e2e_seconds_count[1h]))", "currencyUSD"),
    panel("Cost per 100 runs (USD, 1h window)",
          "100 * sum(increase(ecs_llm_cost_usd_total[1h])) / sum(increase(ecs_run_e2e_seconds_count[1h]))",
          "currencyUSD", kind="stat"),
    panel("Tokens per minute by agent and kind", "sum by (agent, kind) (rate(ecs_llm_tokens_total[1m])) * 60",
          legend="{{agent}} {{kind}}"),
    panel("Cost per minute by agent (largest driver)", "sum by (agent) (rate(ecs_llm_cost_usd_total[5m])) * 60",
          "currencyUSD", legend="{{agent}}"),
    row("Caching (D7)"),
    panel("Cache hit rate per cache",
          "sum by (cache) (rate(ecs_cache_hits_total[5m])) / "
          "(sum by (cache) (rate(ecs_cache_hits_total[5m])) + sum by (cache) (rate(ecs_cache_misses_total[5m])))",
          "percentunit", legend="{{cache}}"),
    panel("Retrieval latency p95 by mode", q(Q95, "ecs_retrieval_latency_seconds", "mode"), "s", legend="{{mode}}"),
    row("Corpus freshness (D2)"),
    panel("Index chunks", "ecs_index_chunks", kind="stat", w=8),
    panel("Index age", "time() - ecs_index_built_timestamp", "s", kind="stat", w=8),
    panel("Ingest throughput (chunks/s)", "ecs_ingest_chunks_per_second", kind="stat", w=8),
])

if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for name, d in [("service-health", service_health), ("agents", agents), ("quality-cost", quality)]:
        (OUT / f"{name}.json").write_text(json.dumps(d, indent=2) + "\n")
        print(f"wrote {name}.json ({len(d['panels'])} panels)")
