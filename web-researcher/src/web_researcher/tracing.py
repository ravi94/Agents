"""Phoenix / OpenInference tracing.

Opt-in observability. Importing this module is cheap; the heavy Phoenix and
OpenTelemetry deps are only loaded inside ``init_tracing`` so a run with
``TRACING_ENABLED=false`` (the default) has zero overhead and zero hard
dependency on the observability stack.

Design notes:
- Embedded mode only — ``phoenix.launch_app()`` starts the UI in-process so the
  CLI stays single-command and local-first. Switch to an external Phoenix
  server by setting ``PHOENIX_COLLECTOR_ENDPOINT`` env var instead.
- We instrument ``langchain``; that covers LangGraph's ReAct loop, ChatOllama
  calls, and StructuredTool invocations — i.e. every interesting span.
- ``init_tracing`` is idempotent: a second call within the same process is a
  no-op (Phoenix only needs one session, OTel only needs one tracer provider).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from web_researcher.config import Settings

# Module-level guard so re-initializing in the same process is a no-op.
_INITIALIZED = False


@dataclass
class TracingHandle:
    """Returned from init_tracing so the CLI can show the user the UI URL."""

    ui_url: str
    project_name: str


def init_tracing(settings: Settings) -> Optional[TracingHandle]:
    """Launch embedded Phoenix and wire OpenInference LangChain instrumentation.

    Returns ``None`` when tracing is disabled. Returns a ``TracingHandle`` with
    the Phoenix UI URL when active so the caller can print it.

    Raises ``ImportError`` with an actionable message if the observability
    deps aren't installed — failing loud here is fine because the user
    explicitly asked for tracing.
    """
    global _INITIALIZED
    if not settings.tracing_enabled:
        return None
    if _INITIALIZED:
        # Already wired in this process; just hand back the URL again.
        return TracingHandle(
            ui_url=f"http://{settings.phoenix_host}:{settings.phoenix_port}",
            project_name=settings.phoenix_project_name,
        )

    try:
        import phoenix as px
        from openinference.instrumentation.langchain import LangChainInstrumentor
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    except ImportError as e:  # pragma: no cover — exercised only without deps
        raise ImportError(
            "Tracing is enabled but the observability deps aren't installed. "
            "Run: uv sync  (or: uv add arize-phoenix "
            "openinference-instrumentation-langchain opentelemetry-exporter-otlp "
            "opentelemetry-sdk)"
        ) from e

    # Two modes:
    # 1. External (preferred for the CLI): a standalone `phoenix serve` is
    #    already running. We DON'T launch our own server — embedded mode uses an
    #    in-memory DB that dies with this short-lived CLI process, so traces
    #    would vanish before you could view them. We just point OTel at it.
    # 2. Embedded: launch Phoenix in-process. Fine for notebooks / long-lived
    #    processes; for the one-shot CLI you usually want mode 1.
    if settings.phoenix_collector_endpoint:
        base_url = settings.phoenix_collector_endpoint.rstrip("/")
    else:
        # Embed Phoenix in this process. Phoenix listens on phoenix_port for both
        # the web UI and the OTLP HTTP collector (/v1/traces).
        session = px.launch_app(host=settings.phoenix_host, port=settings.phoenix_port)
        base_url = getattr(
            session, "url", f"http://{settings.phoenix_host}:{settings.phoenix_port}"
        ).rstrip("/")

    # Point OTel at the collector. Phoenix's OTLP endpoint follows the standard
    # OTLP/HTTP path.
    endpoint = f"{base_url}/v1/traces"
    resource = Resource.create({"service.name": settings.phoenix_project_name})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)

    # One call wires up tracing for every LangChain / LangGraph component the
    # agent uses: ChatOllama, StructuredTool, the ReAct graph nodes, etc.
    LangChainInstrumentor().instrument()

    _INITIALIZED = True
    return TracingHandle(ui_url=base_url, project_name=settings.phoenix_project_name)
