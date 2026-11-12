"""OpenTelemetry traces and metrics over OTLP/HTTP, on only when OTEL_EXPORTER_OTLP_ENDPOINT is set."""

import os
import time
from dataclasses import dataclass
from typing import Any

from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.shared.exceptions import MCPError
from mcp.types import CallToolResult
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricReader, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from pydantic import ValidationError

from mcp_app import __version__

SERVICE_NAME = "mcp-server-python-starter"
INVALID_PARAMS = "-32602"


@dataclass(frozen=True)
class Telemetry:
    tracer_provider: TracerProvider
    meter_provider: MeterProvider

    def shutdown(self) -> None:
        """Flushes the spans and metrics still buffered, then stops exporting."""
        self.tracer_provider.shutdown()
        self.meter_provider.shutdown()


def start_telemetry(
    span_processor: SpanProcessor | None = None, metric_reader: MetricReader | None = None
) -> Telemetry | None:
    """Exports the SDK's MCP spans, HTTP spans, and metrics. Returns None when nothing exports."""
    if span_processor is None:
        if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
            return None
        span_processor = BatchSpanProcessor(OTLPSpanExporter())
        metric_reader = PeriodicExportingMetricReader(OTLPMetricExporter())
    resource = Resource.create({"service.name": SERVICE_NAME, "service.version": __version__})
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(span_processor)
    meter_provider = MeterProvider(
        resource=resource, metric_readers=[metric_reader] if metric_reader else []
    )
    # The SDK creates its spans with the global tracer, so set the providers globally.
    trace.set_tracer_provider(tracer_provider)
    metrics.set_meter_provider(meter_provider)
    return Telemetry(tracer_provider, meter_provider)


class OperationMetrics:
    """Records `mcp.server.operation.duration` for each request, by method and tool.

    The histogram's count is the call count, and `error.type` marks failed calls, including
    tool results with `isError`. Names follow the OpenTelemetry MCP semantic conventions.
    """

    def __init__(self, meter_provider: MeterProvider) -> None:
        self._duration = meter_provider.get_meter(__name__, __version__).create_histogram(
            "mcp.server.operation.duration",
            unit="s",
            description="Duration of MCP requests, by method and tool",
        )

    async def __call__(
        self, ctx: ServerRequestContext[Any, Any], call_next: CallNext
    ) -> HandlerResult:
        if ctx.request_id is None:
            return await call_next(ctx)
        attributes: dict[str, str] = {"mcp.method.name": ctx.method}
        name = ctx.params.get("name") if ctx.params else None
        if ctx.method == "tools/call" and isinstance(name, str):
            attributes["gen_ai.tool.name"] = name
        start = time.perf_counter()
        try:
            result = await call_next(ctx)
        except MCPError as error:
            attributes["error.type"] = str(error.error.code)
            raise
        except ValidationError:
            attributes["error.type"] = INVALID_PARAMS
            raise
        except Exception as error:
            attributes["error.type"] = type(error).__qualname__
            raise
        else:
            match result:
                case CallToolResult(is_error=True) | {"isError": True}:
                    attributes["error.type"] = "tool_error"
                case _:
                    pass
            return result
        finally:
            self._duration.record(time.perf_counter() - start, attributes)
