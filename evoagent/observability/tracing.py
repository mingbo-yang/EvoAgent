"""Lightweight, dependency-optional tracing for agent observability.

Provides a :class:`Tracer` that always records spans in-memory (so traces are
inspectable and testable with no third-party dependency) and, when
``use_otel=True`` and the ``opentelemetry`` packages are installed, also emits
real OpenTelemetry spans to the configured exporter.

Spans are produced for the agent turn, each LLM call, and each tool execution
by the ReAct engine when a tracer is supplied.
"""

import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Span:
    name: str
    attributes: dict[str, Any] = field(default_factory=dict)
    status: str = "ok"  # ok | error
    error: str | None = None
    start_ns: int = 0
    end_ns: int = 0
    duration_ms: float = 0.0


def _otel_tracer(service_name: str):
    """Return an OpenTelemetry tracer if the API is importable, else None."""
    try:
        from opentelemetry import trace
    except Exception:
        return None
    return trace.get_tracer(service_name)


class Tracer:
    """Records spans in-memory and optionally mirrors them to OpenTelemetry."""

    def __init__(self, service_name: str = "evoagent", use_otel: bool = False,
                 max_spans: int = 1000):
        self.service_name = service_name
        self._spans: deque[Span] = deque(maxlen=max_spans)
        self._otel = _otel_tracer(service_name) if use_otel else None

    @property
    def finished_spans(self) -> list[Span]:
        return list(self._spans)

    def spans_named(self, name: str) -> list[Span]:
        return [s for s in self._spans if s.name == name]

    def clear(self) -> None:
        self._spans.clear()

    @contextmanager
    def span(self, name: str, **attributes: Any):
        """Context manager recording a span; yields it so attributes can be set."""
        sp = Span(name=name, attributes=dict(attributes), start_ns=time.monotonic_ns())
        otel_cm = None
        otel_span = None
        if self._otel is not None:
            try:
                otel_cm = self._otel.start_as_current_span(name)
                otel_span = otel_cm.__enter__()
                for k, v in attributes.items():
                    otel_span.set_attribute(k, _otel_value(v))
            except Exception:
                otel_cm = otel_span = None
        try:
            yield sp
        except Exception as e:
            sp.status = "error"
            sp.error = str(e)
            if otel_span is not None:
                try:
                    from opentelemetry.trace import Status, StatusCode
                    otel_span.set_status(Status(StatusCode.ERROR, str(e)))
                    otel_span.record_exception(e)
                except Exception:
                    pass
            raise
        finally:
            sp.end_ns = time.monotonic_ns()
            sp.duration_ms = (sp.end_ns - sp.start_ns) / 1e6
            if otel_span is not None:
                try:
                    for k, v in sp.attributes.items():
                        otel_span.set_attribute(k, _otel_value(v))
                except Exception:
                    pass
                try:
                    otel_cm.__exit__(None, None, None)
                except Exception:
                    pass
            self._spans.append(sp)


def _otel_value(v: Any) -> Any:
    """Coerce attribute values to OTel-acceptable scalar types."""
    if isinstance(v, (str, bool, int, float)):
        return v
    return str(v)


def configure_otel(service_name: str = "evoagent", exporter: Any = None) -> bool:
    """Best-effort setup of an OpenTelemetry TracerProvider.

    Returns True if OpenTelemetry SDK was available and configured. Uses the
    provided span exporter, or a console exporter if none is given. Safe to call
    when the SDK is absent (returns False).
    """
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            ConsoleSpanExporter,
        )
    except Exception:
        return False
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(BatchSpanProcessor(exporter or ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    return True
