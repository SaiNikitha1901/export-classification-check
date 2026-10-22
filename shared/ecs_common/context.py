"""Context variables carried through a request or a run, and picked up by the JSON logger."""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional

CORRELATION_HEADER = "X-Correlation-ID"

_FIELDS = ("run_id", "correlation_id", "agent", "step")
_vars: dict[str, ContextVar[Optional[str]]] = {f: ContextVar(f, default=None) for f in _FIELDS}


def new_correlation_id() -> str:
    return uuid.uuid4().hex


def correlation_id() -> Optional[str]:
    return _vars["correlation_id"].get()


def current_context() -> dict[str, Optional[str]]:
    return {f: v.get() for f, v in _vars.items()}


@contextmanager
def bind(**values: Optional[str]) -> Iterator[None]:
    """Set run_id / correlation_id / agent / step for the duration of a block."""
    tokens = [(_vars[k], _vars[k].set(v)) for k, v in values.items() if k in _vars]
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)
