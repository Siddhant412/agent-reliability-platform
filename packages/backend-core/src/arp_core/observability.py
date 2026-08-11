from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_configured = False
_counters: dict[str, metrics.Counter] = {}


def configure_telemetry(*, service_name: str, endpoint: str | None) -> None:
    """Configure OTLP only when an explicit endpoint is supplied.

    Local unit tests and the default SQLite demo retain no-op OpenTelemetry
    providers; the Compose environment opts in through ARP_OTEL_ENDPOINT.
    """
    global _configured
    if not endpoint or _configured:
        return
    resource = Resource.create({"service.name": service_name})
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True))
    )
    trace.set_tracer_provider(tracer_provider)

    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=endpoint, insecure=True),
        export_interval_millis=5_000,
    )
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[metric_reader]))
    _configured = True


@contextmanager
def span(name: str, *, attributes: dict[str, Any] | None = None) -> Iterator[trace.Span]:
    with trace.get_tracer("arp.runtime").start_as_current_span(name) as active_span:
        if attributes:
            active_span.set_attributes(attributes)
        yield active_span


def record_worker_event(name: str, *, attributes: dict[str, Any]) -> None:
    counter = _counters.setdefault(name, metrics.get_meter("arp.worker").create_counter(name))
    counter.add(1, attributes)
