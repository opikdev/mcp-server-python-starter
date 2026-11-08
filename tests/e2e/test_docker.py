"""Builds the image and serves a client over HTTP, as a deployment would."""

import json
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import httpx2
import pytest

from tests.helpers import TOKEN, free_port, http_client

ROOT = Path(__file__).parents[2]
IMAGE = "mcp-server-python-starter:e2e"

pytestmark = pytest.mark.anyio


def docker(*args: str) -> str:
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=True).stdout


@pytest.fixture(scope="module")
def container() -> Iterator[tuple[str, str]]:
    docker("build", "--tag", IMAGE, str(ROOT))
    port = free_port()
    name = f"mcp-python-e2e-{port}"
    docker(
        "run",
        "--detach",
        "--name",
        name,
        "--publish",
        f"127.0.0.1:{port}:3000",
        "--env",
        "MCP_AUTH_MODE=token",
        "--env",
        f"MCP_AUTH_TOKENS={TOKEN}",
        "--env",
        f"MCP_PUBLIC_URL=http://localhost:{port}/mcp",
        IMAGE,
    )
    try:
        deadline = time.monotonic() + 60
        while docker("inspect", "--format", "{{.State.Health.Status}}", name).strip() != "healthy":
            if time.monotonic() > deadline:
                pytest.fail(f"The container never became healthy:\n{docker('logs', name)}")
            time.sleep(0.5)
        yield name, f"http://localhost:{port}"
    finally:
        subprocess.run(["docker", "rm", "--force", name], capture_output=True, check=False)


async def test_serves_a_client_over_http_with_a_token(container: tuple[str, str]) -> None:
    _, url = container
    async with http_client(f"{url}/mcp", TOKEN) as client:
        result = await client.call_tool("get_time", {"timezone": "Europe/Berlin"})
    assert result.is_error is False


async def test_rejects_a_request_without_a_token(container: tuple[str, str]) -> None:
    _, url = container
    async with httpx2.AsyncClient() as http:
        response = await http.post(f"{url}/mcp", json={})
    assert response.status_code == 401


def test_is_healthy_and_runs_as_a_non_root_user(container: tuple[str, str]) -> None:
    name, _ = container
    assert docker("exec", name, "id", "-u").strip() == "10001"
    logs = subprocess.run(["docker", "logs", name], capture_output=True, text=True, check=True)
    entries = [json.loads(line) for line in logs.stderr.splitlines() if line.startswith("{")]
    assert any(entry["msg"] == "Serving MCP over HTTP" for entry in entries)
    assert TOKEN not in logs.stdout + logs.stderr
