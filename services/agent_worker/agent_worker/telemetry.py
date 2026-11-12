"""OpenTelemetry for the worker: one span per run (joined to the API's submit trace through
runs.trace_context), child spans per agent step and tool call, trace headers on retriever calls."""
from __future__ import annotations

import os

from opentelemetry import propagate, trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

tracer = trace.get_tracer("agent-worker")


def setup(service: str = "agent-worker") -> None:
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

    provider = TracerProvider(resource=Resource.create({"service.name": service}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True)))
    trace.set_tracer_provider(provider)


def extract(carrier: dict | None):
    return propagate.extract(carrier or {})


def inject(headers: dict) -> dict:
    propagate.inject(headers)
    return headers
