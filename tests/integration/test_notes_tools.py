from collections.abc import AsyncIterator

import httpx2
import pytest
from mcp import Client
from mcp.types import CallToolResult, TextContent
from starlette.responses import JSONResponse

from mcp_app.server import create_server
from mcp_app.upstream.notes_client import NotesClient
from tests.fake_notes_api import FakeNotesApi

pytestmark = pytest.mark.anyio

UPSTREAM_TOKEN = "upstream-secret-token-123"


@pytest.fixture
def api() -> FakeNotesApi:
    return FakeNotesApi(UPSTREAM_TOKEN)


@pytest.fixture
async def client(api: FakeNotesApi) -> AsyncIterator[Client]:
    notes = NotesClient(
        base_url="http://notes.test",
        token=UPSTREAM_TOKEN,
        timeout_seconds=5,
        transport=httpx2.ASGITransport(app=api.app),
    )
    async with Client(create_server(transport="stdio", notes=notes)) as connected:
        yield connected
    await notes.aclose()


def text(result: CallToolResult) -> str:
    content = result.content[0]
    assert isinstance(content, TextContent)
    return content.text


async def test_appear_only_when_an_upstream_is_configured(client: Client) -> None:
    async with Client(create_server(transport="stdio")) as plain:
        names = {tool.name for tool in (await plain.list_tools()).tools}
    assert "list_notes" not in names
    tools = {tool.name: tool for tool in (await client.list_tools()).tools}
    assert tools["create_note"].annotations is not None
    assert tools["create_note"].annotations.read_only_hint is False
    assert tools["create_note"].annotations.open_world_hint is True


async def test_lists_notes_then_the_next_page(client: Client, api: FakeNotesApi) -> None:
    for title in ("First", "Second", "Third"):
        api.add(title)
    first = await client.call_tool("list_notes", {"limit": 2})
    assert first.structured_content is not None
    assert [note["title"] for note in first.structured_content["notes"]] == ["Third", "Second"]
    cursor = first.structured_content["nextCursor"]
    second = await client.call_tool("list_notes", {"limit": 2, "cursor": cursor})
    assert second.structured_content is not None
    assert [note["title"] for note in second.structured_content["notes"]] == ["First"]
    assert second.structured_content["nextCursor"] is None
    assert "1 note(s):\n- First (note_0001)" in text(second)


async def test_creates_a_note_the_api_then_lists(client: Client) -> None:
    created = await client.call_tool("create_note", {"title": "  Buy milk ", "body": "2 litres"})
    assert created.structured_content is not None
    assert created.structured_content["title"] == "Buy milk"
    assert created.structured_content["createdAt"] == "2026-11-08T12:00:00.000Z"
    listed = await client.call_tool("list_notes", {})
    assert listed.structured_content is not None
    assert listed.structured_content["notes"][0]["id"] == created.structured_content["id"]


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("create_note", {"title": "   "}),
        ("create_note", {"title": "x" * 201}),
        ("list_notes", {"limit": 51}),
    ],
)
async def test_rejects_bad_input_before_calling_the_api(
    client: Client, api: FakeNotesApi, tool: str, arguments: dict[str, object]
) -> None:
    result = await client.call_tool(tool, arguments)
    assert result.is_error is True
    assert api.requests == []


@pytest.mark.parametrize(
    ("status", "headers", "body", "message"),
    [
        (401, {}, {}, "rejected this server's credentials"),
        (429, {"Retry-After": "30"}, {}, "Retry in 30 seconds"),
        (422, {}, {"detail": "Title is taken"}, "refused the request: Title is taken"),
        (503, {}, {}, "failed with HTTP 503. Try again later"),
    ],
)
async def test_turns_api_failures_into_messages_without_leaking_the_token(
    client: Client,
    api: FakeNotesApi,
    status: int,
    headers: dict[str, str],
    body: dict[str, str],
    message: str,
) -> None:
    api.next_response = JSONResponse(body, status_code=status, headers=headers)
    result = await client.call_tool("list_notes", {})
    assert result.is_error is True
    assert message in text(result)
    assert UPSTREAM_TOKEN not in text(result)


@pytest.mark.parametrize("error", [httpx2.ReadTimeout("slow"), httpx2.RemoteProtocolError("cut")])
async def test_says_a_write_without_an_answer_may_have_happened(error: Exception) -> None:
    def handle(_: httpx2.Request) -> httpx2.Response:
        raise error

    notes = NotesClient(
        base_url="http://notes.test",
        token=UPSTREAM_TOKEN,
        timeout_seconds=5,
        transport=httpx2.MockTransport(handle),
    )
    async with Client(create_server(transport="stdio", notes=notes)) as connected:
        created = await connected.call_tool("create_note", {"title": "Buy milk"})
        listed = await connected.call_tool("list_notes", {})
    await notes.aclose()
    assert created.is_error is True
    assert text(created).endswith(
        "The notes API didn't answer in time, so the note may or may not exist. "
        "Call list_notes to check before retrying."
    )
    assert listed.is_error is True
    assert "Try again later" in text(listed)
