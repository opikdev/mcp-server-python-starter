import httpx2
import pytest

from mcp_app.upstream.notes_client import NotesClient, UpstreamError
from tests.fake_notes_api import FakeNotesApi

pytestmark = pytest.mark.anyio

TOKEN = "upstream-token-0123"


def client(
    transport: httpx2.AsyncBaseTransport, base_url: str = "http://notes.test"
) -> NotesClient:
    return NotesClient(base_url=base_url, token=TOKEN, timeout_seconds=0.5, transport=transport)


async def test_lists_a_page_and_sends_the_token() -> None:
    api = FakeNotesApi(TOKEN)
    api.add("One")
    page = await client(httpx2.ASGITransport(app=api.app)).list(limit=5)
    assert [note.title for note in page.data] == ["One"]
    assert api.requests[0].headers["authorization"] == f"Bearer {TOKEN}"
    assert api.requests[0].query_params["limit"] == "5"


async def test_follows_a_cursor() -> None:
    api = FakeNotesApi(TOKEN)
    api.add("Old")
    api.add("New")
    notes = client(httpx2.ASGITransport(app=api.app))
    first = await notes.list(limit=1)
    second = await notes.list(limit=1, cursor=first.meta.next_cursor)
    assert [note.title for note in second.data] == ["Old"]


async def test_keeps_a_base_path() -> None:
    seen: list[str] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.url.path)
        return httpx2.Response(200, json={"data": [], "meta": {"nextCursor": None}})

    await client(httpx2.MockTransport(handle), "http://notes.test/api").list(limit=1)
    assert seen == ["/api/v1/notes"]


async def test_creates_a_note() -> None:
    api = FakeNotesApi(TOKEN)
    note = await client(httpx2.ASGITransport(app=api.app)).create(title="Hi", body="There")
    assert (note.title, api.notes[0]["body"]) == ("Hi", "There")


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (httpx2.ReadTimeout("slow"), "didn't answer within 0.5 seconds"),
        (httpx2.ConnectError("down"), "Couldn't reach the notes API"),
    ],
)
async def test_reports_a_slow_or_unreachable_api(error: Exception, message: str) -> None:
    def handle(_: httpx2.Request) -> httpx2.Response:
        raise error

    with pytest.raises(UpstreamError, match=message):
        await client(httpx2.MockTransport(handle)).list(limit=1)


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx2.Response(200, json={"unexpected": True}), "doesn't understand"),
        (httpx2.Response(429, headers={"Retry-After": "soon"}), "Retry in 60 seconds"),
        (httpx2.Response(400, text="not json"), "refused the request: HTTP 400"),
    ],
)
async def test_explains_odd_responses(response: httpx2.Response, message: str) -> None:
    with pytest.raises(UpstreamError, match=message):
        await client(httpx2.MockTransport(lambda _: response)).list(limit=1)
