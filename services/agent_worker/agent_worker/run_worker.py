"""PLACEHOLDER worker entrypoint (Member 1 skeleton; Member 3 owns this folder).

Starts the Prometheus endpoint on :9100, then an RQ worker on queue "runs".
SimpleWorker runs jobs in-process (no fork), so metrics recorded inside a job are scraped.
"""
import os

from prometheus_client import start_http_server
from redis import Redis
from rq import Queue, SimpleWorker

from ecs_common import setup_logging


def main() -> None:
    setup_logging("agent-worker", os.environ.get("LOG_LEVEL", "INFO"))
    start_http_server(9100)
    conn = Redis.from_url(os.environ["REDIS_URL"])
    SimpleWorker([Queue("runs", connection=conn)], connection=conn).work(with_scheduler=False)


if __name__ == "__main__":
    main()
