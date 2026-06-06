"""Observability — dependency-optional tracing for agent runs."""

from evoagent.observability.tracing import Span, Tracer, configure_otel

__all__ = ["Span", "Tracer", "configure_otel"]
