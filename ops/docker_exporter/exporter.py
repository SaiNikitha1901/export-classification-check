"""Per-container CPU, memory and uptime from the Docker Engine API (D5, A6).

Replaces cAdvisor, which cannot see containers on Docker Desktop for Mac (see docs/incident_log.md).
Reads /var/run/docker.sock every POLL_S seconds and exposes, per compose service and container:
  ecs_container_cpu_cores, ecs_container_memory_bytes, ecs_container_memory_limit_bytes,
  ecs_container_uptime_seconds, ecs_container_up
"""
import http.client
import json
import logging
import os
import socket
import threading
import time
import urllib.parse
from datetime import datetime

from prometheus_client import start_http_server
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import REGISTRY, Collector

SOCK = os.environ.get("DOCKER_SOCK", "/var/run/docker.sock")
PROJECT = os.environ.get("COMPOSE_PROJECT", "ecs")
POLL_S = float(os.environ.get("POLL_S", "5"))
log = logging.getLogger("docker_exporter")


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path: str):
        super().__init__("localhost", timeout=10)
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(10)
        self.sock.connect(self.path)


def docker_get(path: str):
    conn = UnixHTTPConnection(SOCK)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        return json.loads(resp.read())
    finally:
        conn.close()


def parse_ts(value: str) -> float:
    # Docker gives RFC3339 with nanoseconds; trim to microseconds for fromisoformat.
    head, _, frac = value.rstrip("Z").partition(".")
    return datetime.fromisoformat(f"{head}.{(frac or '0')[:6]}+00:00").timestamp()


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.rows: dict[str, dict] = {}
        self.prev_cpu: dict[str, tuple[float, float]] = {}


state = State()


def poll_once():
    filt = json.dumps({"label": [f"com.docker.compose.project={PROJECT}"]})
    containers = docker_get(f"/containers/json?all=true&filters={urllib.parse.quote(filt)}")
    rows = {}
    now = time.time()
    for c in containers:
        cid = c["Id"]
        name = (c.get("Names") or ["/?"])[0].lstrip("/")
        service = c.get("Labels", {}).get("com.docker.compose.service", "unknown")
        running = c.get("State") == "running"
        row = {"service": service, "name": name, "up": 1.0 if running else 0.0}
        if running:
            stats = docker_get(f"/containers/{cid}/stats?stream=false&one-shot=true")
            inspect = docker_get(f"/containers/{cid}/json")
            total = stats["cpu_stats"]["cpu_usage"]["total_usage"] / 1e9  # seconds of CPU
            prev = state.prev_cpu.get(cid)
            state.prev_cpu[cid] = (total, now)
            if prev and now > prev[1]:
                row["cpu"] = max(0.0, (total - prev[0]) / (now - prev[1]))
            mem = stats.get("memory_stats", {})
            usage = mem.get("usage", 0) - mem.get("stats", {}).get("inactive_file", 0)
            row["mem"] = float(max(usage, 0))
            row["mem_limit"] = float(mem.get("limit", 0))
            row["uptime"] = now - parse_ts(inspect["State"]["StartedAt"])
        rows[cid] = row
    with state.lock:
        state.rows = rows


class DockerCollector(Collector):
    def collect(self):
        labels = ["service", "name"]
        fams = {
            "up": GaugeMetricFamily("ecs_container_up", "1 if the container is running", labels=labels),
            "cpu": GaugeMetricFamily("ecs_container_cpu_cores", "CPU cores used (rate over last poll)", labels=labels),
            "mem": GaugeMetricFamily("ecs_container_memory_bytes", "Memory in use (excl. page cache)", labels=labels),
            "mem_limit": GaugeMetricFamily("ecs_container_memory_limit_bytes", "Memory limit", labels=labels),
            "uptime": GaugeMetricFamily("ecs_container_uptime_seconds", "Seconds since container start", labels=labels),
        }
        with state.lock:
            rows = list(state.rows.values())
        for r in rows:
            for key, fam in fams.items():
                if key in r:
                    fam.add_metric([r["service"], r["name"]], r[key])
        yield from fams.values()


def main():
    logging.basicConfig(level="INFO", format='{"service":"docker-exporter","level":"%(levelname)s","msg":"%(message)s"}')
    REGISTRY.register(DockerCollector())
    start_http_server(9417)
    while True:
        try:
            poll_once()
        except Exception as exc:
            log.warning("poll failed: %s", exc)
        time.sleep(POLL_S)


if __name__ == "__main__":
    main()
