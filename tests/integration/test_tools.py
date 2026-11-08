import sys
from collections.abc import AsyncIterator

import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters
from mcp.types import ResourceLink, TextContent, TextResourceContents

from mcp_app.server import create_server
from tests.helpers import FIXED_NOW

pytestmark = pytest.mark.anyio


@pytest.fixture
async def client() -> AsyncIterator[Client]:
    async with Client(create_server(transport="stdio", now=lambda: FIXED_NOW)) as connected:
        yield connected


def text(content: object) -> str:
    assert isinstance(content, TextContent)
    return content.text


async def test_serves_tools_from_a_real_process() -> None:
    process = StdioServerParameters(command=sys.executable, args=["-m", "mcp_app"])
    async with Client(process) as client:
        result = await client.call_tool("whoami", {})
    assert result.structured_content == {"transport": "stdio", "clientId": None, "scopes": []}


@pytest.mark.parametrize(("mode", "version"), [("auto", "2026-07-28"), ("legacy", "2025-11-25")])
async def test_serves_both_protocol_eras(mode: str, version: str) -> None:
    async with Client(create_server(transport="stdio"), mode=mode) as client:
        assert client.session.protocol_version == version
        assert (await client.call_tool("get_time", {})).is_error is False


async def test_lists_tools_with_schemas_and_annotations(client: Client) -> None:
    tools = {tool.name: tool for tool in (await client.list_tools()).tools}
    assert sorted(tools) == ["get_time", "search_docs", "whoami"]
    for tool in tools.values():
        assert tool.title
        assert tool.description
        assert "\n" not in tool.description
        assert tool.output_schema is not None
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
    assert tools["search_docs"].input_schema["required"] == ["query"]


async def test_returns_the_time_in_a_time_zone(client: Client) -> None:
    result = await client.call_tool("get_time", {"timezone": "Asia/Jakarta"})
    assert result.structured_content == {
        "iso": "2026-11-08T12:30:00Z",
        "timezone": "Asia/Jakarta",
        "local": "Sunday, November 8, 2026 at 19:30:00 WIB",
    }
    assert text(result.content[0]) == "Sunday, November 8, 2026 at 19:30:00 WIB (Asia/Jakarta)"


async def test_defaults_to_utc(client: Client) -> None:
    result = await client.call_tool("get_time", {})
    assert result.structured_content is not None
    assert result.structured_content["timezone"] == "UTC"


@pytest.mark.parametrize("zone", ["Mars/Olympus", "../../etc/passwd", ""])
async def test_reports_an_unknown_time_zone_as_a_tool_error(client: Client, zone: str) -> None:
    result = await client.call_tool("get_time", {"timezone": zone})
    assert result.is_error is True
    assert f'Unknown time zone "{zone}". Use an IANA name' in text(result.content[0])


async def test_rejects_invalid_arguments_before_running_the_tool(client: Client) -> None:
    result = await client.call_tool("search_docs", {"query": "   ", "limit": 11})
    assert result.is_error is True
    assert "query" in text(result.content[0])


async def test_finds_docs_and_links_to_them(client: Client) -> None:
    result = await client.call_tool("search_docs", {"query": "OAuth tokens"})
    assert result.structured_content is not None
    assert result.structured_content["results"][0]["uri"] == "docs://authentication"
    link = result.content[1]
    assert isinstance(link, ResourceLink)
    assert str(link.uri) == "docs://authentication"


async def test_respects_the_result_limit(client: Client) -> None:
    result = await client.call_tool("search_docs", {"query": "tools server", "limit": 1})
    assert result.structured_content is not None
    assert len(result.structured_content["results"]) == 1


async def test_says_so_when_nothing_matches(client: Client) -> None:
    result = await client.call_tool("search_docs", {"query": "kubernetes"})
    assert result.structured_content == {"results": []}
    assert text(result.content[0]) == 'No docs match "kubernetes".'


async def test_lists_and_reads_docs_resources(client: Client) -> None:
    listed = {str(resource.uri) for resource in (await client.list_resources()).resources}
    assert listed == {"docs://getting-started", "docs://authentication", "docs://adding-tools"}
    templates = (await client.list_resource_templates()).resource_templates
    assert [template.uri_template for template in templates] == ["docs://{slug}"]
    contents = (await client.read_resource("docs://adding-tools")).contents
    assert isinstance(contents[0], TextResourceContents)
    assert contents[0].text.startswith("# Adding tools\n")


async def test_fails_clearly_for_an_unknown_doc(client: Client) -> None:
    with pytest.raises(Exception, match="No doc at docs://missing"):
        await client.read_resource("docs://missing")
