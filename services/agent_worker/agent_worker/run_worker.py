"""Worker entrypoint: Prometheus on :9100, then an RQ SimpleWorker on queue "runs".
SimpleWorker runs jobs in-process (no fork), so metrics recorded inside a job are scraped and the
toxicity model is loaded once per container. Replicas share nothing but Redis and Postgres."""
import os

from prometheus_client import start_http_server
from redis import Redis
from rq import Queue, SimpleWorker

from agent_worker import config, guardrails, telemetry
from agent_worker.llm.breaker import CircuitBreaker
from ecs_common import setup_logging


def main() -> None:
    setup_logging("agent-worker", os.environ.get("LOG_LEVEL", "INFO"))
    telemetry.setup("agent-worker")
    start_http_server(9100)
    conn = Redis.from_url(os.environ["REDIS_URL"])
    s = config.load()
    for p in s.providers:   # publish breaker state from the first scrape on
        CircuitBreaker(conn, p.name, s.cb_threshold, s.cb_window_s, s.cb_open_s).state()
    guardrails.warm_up()
    SimpleWorker([Queue("runs", connection=conn)], connection=conn).work(with_scheduler=False)


if __name__ == "__main__":
    main()
