"""OpenTelemetry setup: spans exported over OTLP to Jaeger (D5)."""
from __future__ import annotations

import logging

from opentelemetry import propagate, trace

log = logging.getLogger("telemetry")


def setup_tracing(app, service: str, endpoint: str | None) -> None:
    if not endpoint:
        log.warning("OTEL_EXPORTER_OTLP_ENDPOINT not set; tracing disabled")
        return
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
    from opentelemetry.instrumentation.redis import RedisInstrumentor
    from opentelemetry.instrumentation.requests import RequestsInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": service}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True)))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app, excluded_urls="health,metrics,ui")
    RequestsInstrumentor().instrument()
    PsycopgInstrumentor().instrument(enable_commenter=False)
    RedisInstrumentor().instrument()


def current_trace_context() -> dict[str, str]:
    """W3C traceparent of the active span, stored on the run so the worker can continue the trace."""
    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    return carrier


def annotate(**attrs) -> None:
    span = trace.get_current_span()
    for k, v in attrs.items():
        if v is not None:
            span.set_attribute(k, v)
