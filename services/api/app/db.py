"""Postgres access. One pool per process; rows come back as dicts."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from app.config import settings

pool = ConnectionPool(settings.postgres_dsn, min_size=1, max_size=10, open=False, kwargs={"row_factory": dict_row})


@contextmanager
def conn() -> Iterator[Any]:
    with pool.connection() as c:
        yield c


def fetch_one(sql: str, params: tuple | dict = ()) -> dict | None:
    with conn() as c:
        return c.execute(sql, params).fetchone()


def fetch_all(sql: str, params: tuple | dict = ()) -> list[dict]:
    with conn() as c:
        return c.execute(sql, params).fetchall()


def execute(sql: str, params: tuple | dict = ()) -> int:
    with conn() as c:
        return c.execute(sql, params).rowcount


__all__ = ["Jsonb", "conn", "execute", "fetch_all", "fetch_one", "pool"]
