"""Runs the notes tools against the example backend in compose.upstream.yaml."""

import json
import os
import subprocess
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx2
import pytest
from mcp import Client

from mcp_app.server import create_server
from mcp_app.upstream.credentials import StaticCredentials
from mcp_app.upstream.notes_client import NotesClient
from tests.helpers import free_port

ROOT = Path(__file__).parents[2]
PROJECT = "notes-upstream-python-e2e"

pytestmark = pytest.mark.anyio


def compose(*args: str, env: dict[str, str]) -> None:
    subprocess.run(
        ["docker", "compose", "--project-name", PROJECT, "-f", "compose.upstream.yaml", *args],
        cwd=ROOT,
        env={**os.environ, **env},
        check=True,
        capture_output=True,
    )


@pytest.fixture(scope="module")
def api() -> Iterator[str]:
    env = {"API_PORT": str(free_port())}
    compose("up", "--detach", "--wait", "api", env=env)
    try:
        yield f"http://localhost:{env['API_PORT']}"
    finally:
        compose("down", "--volumes", env=env)


@pytest.fixture
def token(api: str) -> str:
    response = httpx2.post(
        f"{api}/v1/sessions", json={"email": "demo@example.com", "password": "demo-password-123"}
    )
    response.raise_for_status()
    session: str = response.json()["token"]
    return session


@pytest.fixture
async def client(api: str, token: str) -> AsyncIterator[Client]:
    notes = NotesClient(base_url=api, credentials=StaticCredentials(token), timeout_seconds=5)
    async with Client(create_server(transport="stdio", notes=notes)) as connected:
        yield connected
    await notes.aclose()


async def test_lists_the_seeded_notes(client: Client) -> None:
    result = await client.call_tool("list_notes", {})
    assert result.is_error is False
    assert result.structured_content is not None
    assert len(result.structured_content["notes"]) >= 2


async def test_creates_a_note_the_api_stores(client: Client) -> None:
    created = await client.call_tool("create_note", {"title": "From the Python MCP server"})
    assert created.structured_content is not None
    listed = await client.call_tool("list_notes", {"limit": 50})
    assert listed.structured_content is not None
    ids = [note["id"] for note in listed.structured_content["notes"]]
    assert created.structured_content["id"] in ids


def inspect(*args: str, api: str, token: str) -> Any:
    """Runs `make inspect` as docs/upstream.md shows, in the Inspector's CLI mode."""
    result = subprocess.run(
        ["make", "--silent", "inspect", f"ARGS=--cli {' '.join(args)}"],
        cwd=ROOT,
        env={**os.environ, "UPSTREAM_API_URL": api, "UPSTREAM_API_TOKEN": token},
        capture_output=True,
        text=True,
        timeout=180,
        check=True,
    )
    return json.loads(result.stdout[result.stdout.index("{") :])


def test_the_documented_inspector_quick_start_shows_and_runs_the_notes_tools(
    api: str, token: str
) -> None:
    listed = inspect("--method tools/list", api=api, token=token)
    assert {"list_notes", "create_note"} <= {tool["name"] for tool in listed["tools"]}
    called = inspect("--method tools/call --tool-name list_notes", api=api, token=token)
    assert called["isError"] is False
    assert called["structuredContent"]["notes"]
