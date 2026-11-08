"""Runs the real entry point in a subprocess, as clients and containers do."""

import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Iterator

import httpx2
import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from tests.helpers import TOKEN, free_port, http_client

pytestmark = pytest.mark.anyio

COMMAND = [sys.executable, "-m", "mcp_app"]


def run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*COMMAND, *args],
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, **(env or {})},
        check=False,
    )


def test_prints_its_version() -> None:
    result = run("--version")
    assert result.returncode == 0
    assert result.stdout.strip() == "0.1.0"


def test_explains_a_bad_setting_and_exits_with_code_2() -> None:
    result = run("--http", env={"MCP_AUTH_MODE": ""})
    assert result.returncode == 2
    assert "Set MCP_AUTH_MODE to oauth, token, or none" in result.stderr
    assert result.stdout == ""


async def test_keeps_stdout_for_protocol_messages_and_logs_json_to_stderr() -> None:
    process = StdioServerParameters(command=COMMAND[0], args=COMMAND[1:], env={**os.environ})
    async with Client(process) as client:
        result = await client.call_tool("get_time", {"timezone": "UTC"})
    assert result.is_error is False


@pytest.fixture
def http_process() -> Iterator[tuple[subprocess.Popen[str], str]]:
    port = free_port()
    env = {
        **os.environ,
        "PORT": str(port),
        "MCP_AUTH_MODE": "token",
        "MCP_AUTH_TOKENS": TOKEN,
        "LOG_LEVEL": "info",
    }
    process = subprocess.Popen(
        [*COMMAND, "--http"], env=env, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True
    )
    url = f"http://localhost:{port}"
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            if httpx2.get(f"{url}/healthz").status_code == 200:
                break
        except httpx2.TransportError:
            time.sleep(0.1)
    try:
        yield process, url
    finally:
        if process.poll() is None:
            process.kill()


async def test_serves_http_and_shuts_down_cleanly_on_sigterm(
    http_process: tuple[subprocess.Popen[str], str],
) -> None:
    process, url = http_process
    async with http_client(f"{url}/mcp", TOKEN) as client:
        result = await client.call_tool("whoami", {})
    assert result.structured_content is not None
    assert result.structured_content["clientId"] == "token-1"

    process.send_signal(signal.SIGTERM)
    stdout, stderr = process.communicate(timeout=20)
    # Uvicorn shuts down gracefully, then re-raises the signal, so supervisors see why it stopped.
    assert process.returncode == -signal.SIGTERM
    assert "Application shutdown complete." in stderr
    entries = [json.loads(line) for line in stderr.splitlines() if line.startswith("{")]
    assert any(entry["msg"] == "Serving MCP over HTTP" for entry in entries)
    assert all({"time", "level", "logger", "msg"} <= entry.keys() for entry in entries)
    assert TOKEN not in stderr + stdout
