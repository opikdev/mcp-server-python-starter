import json
import logging
from collections.abc import Iterator

import httpx2
import pytest
from opentelemetry import trace
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from mcp_app.config import load_http_config
from mcp_app.log import JsonFormatter
from mcp_app.telemetry import Telemetry, start_telemetry
from tests.fake_notes_api import FakeNotesApi
from tests.helpers import free_port, http_app, http_client, notes_client, serve

pytestmark = pytest.mark.anyio

UPSTREAM_TOKEN = "upstream-secret-token-123"


@pytest.fixture(scope="module")
def exported() -> Iterator[tuple[Telemetry, InMemorySpanExporter, InMemoryMetricReader]]:
    spans = InMemorySpanExporter()
    reader = InMemoryMetricReader()
    telemetry = start_telemetry(SimpleSpanProcessor(spans), reader)
    assert telemetry is not None
    yield telemetry, spans, reader
    telemetry.shutdown()


def durations(reader: InMemoryMetricReader, name: str) -> list[dict[str, object]]:
    data = reader.get_metrics_data()
    assert data is not None
    return [
        {**(point.attributes or {}), "count": getattr(point, "count", None)}
        for resource in data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
        if metric.name == name
        for point in metric.data.data_points
    ]


def test_exports_nothing_without_an_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    assert start_telemetry() is None


async def test_traces_and_measures_http_requests_and_tool_calls(
    exported: tuple[Telemetry, InMemorySpanExporter, InMemoryMetricReader],
) -> None:
    telemetry, spans, reader = exported
    port = free_port()
    config = load_http_config({"PORT": str(port), "MCP_AUTH_MODE": "none"})
    with serve(http_app(config, verifier=None, telemetry=telemetry), port) as url:
        async with http_client(f"{url}/mcp") as client:
            await client.call_tool("get_time", {"timezone": "Mars/Olympus"})
            await client.call_tool("get_time", {})
        async with httpx2.AsyncClient() as http:
            await http.get(f"{url}/healthz")
    names = [span.name for span in spans.get_finished_spans()]
    assert names.count("tools/call get_time") == 2
    assert "POST /mcp" in names
    assert not any("healthz" in name for name in names)
    tool_calls = [
        point
        for point in durations(reader, "mcp.server.operation.duration")
        if point.get("gen_ai.tool.name") == "get_time"
    ]
    assert sorted(tool_calls, key=str) == sorted(
        [
            {"mcp.method.name": "tools/call", "gen_ai.tool.name": "get_time", "count": 1},
            {
                "mcp.method.name": "tools/call",
                "gen_ai.tool.name": "get_time",
                "error.type": "tool_error",
                "count": 1,
            },
        ],
        key=str,
    )
    assert durations(reader, "http.server.duration") or durations(
        reader, "http.server.request.duration"
    )


async def test_sends_traceparent_to_the_upstream(
    exported: tuple[Telemetry, InMemorySpanExporter, InMemoryMetricReader],
) -> None:
    api = FakeNotesApi(UPSTREAM_TOKEN)
    notes = notes_client(UPSTREAM_TOKEN, httpx2.ASGITransport(app=api.app))
    with trace.get_tracer(__name__).start_as_current_span("caller") as span:
        await notes.list(limit=1)
    await notes.aclose()
    trace_id = format(span.get_span_context().trace_id, "032x")
    traceparent = api.requests[0].headers["traceparent"]
    assert traceparent.split("-")[1] == trace_id


def test_logs_the_trace_and_span_ids_inside_a_span(
    exported: tuple[Telemetry, InMemorySpanExporter, InMemoryMetricReader],
) -> None:
    record = logging.makeLogRecord({"msg": "inside", "levelname": "INFO"})
    outside = json.loads(JsonFormatter().format(record))
    with trace.get_tracer(__name__).start_as_current_span("work") as span:
        inside = json.loads(JsonFormatter().format(record))
    context = span.get_span_context()
    assert "trace_id" not in outside
    assert (inside["trace_id"], inside["span_id"]) == (
        format(context.trace_id, "032x"),
        format(context.span_id, "016x"),
    )
