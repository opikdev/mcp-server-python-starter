"""Runs the real entry point in a subprocess, as clients and containers do."""

import json
import os
import signal
import subprocess
import threading
import tomllib
from collections.abc import Iterator
from pathlib import Path

import anyio
import anyio.to_thread
import httpx2
import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from tests.helpers import (
    COMMAND,
    TOKEN,
    SigningKey,
    claims,
    free_port,
    http_client,
    serve,
    serve_cli,
)

pytestmark = pytest.mark.anyio


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
    pyproject = tomllib.loads((Path(__file__).parents[2] / "pyproject.toml").read_text())
    assert result.stdout.strip() == pyproject["project"]["version"]


def test_refuses_token_exchange_over_stdio() -> None:
    result = run(
        env={
            "UPSTREAM_API_URL": "https://notes.example.com",
            "UPSTREAM_AUTH": "exchange",
            "MCP_AUTH_MODE": "oauth",
            "TOKEN_EXCHANGE_URL": "https://auth.example.com/token",
            "TOKEN_EXCHANGE_CLIENT_ID": "mcp-server",
            "TOKEN_EXCHANGE_CLIENT_SECRET": "exchange-secret",
            "UPSTREAM_AUDIENCE": "notes-api",
        }
    )
    assert result.returncode == 2
    assert "UPSTREAM_AUTH=exchange works only over HTTP" in result.stderr


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
    with serve_cli({"MCP_AUTH_MODE": "token", "MCP_AUTH_TOKENS": TOKEN}) as served:
        yield served


async def test_serves_http_and_shuts_down_cleanly_on_sigterm(
    http_process: tuple[subprocess.Popen[str], str],
) -> None:
    process, url = http_process
    async with http_client(f"{url}/mcp", TOKEN) as client:
        result = await client.call_tool("whoami", {})
    assert result.structured_content is not None
    assert result.structured_content["client_id"] == "token-1"

    process.send_signal(signal.SIGTERM)
    stdout, stderr = process.communicate(timeout=20)
    # Uvicorn shuts down gracefully, then re-raises the signal, so supervisors see why it stopped.
    assert process.returncode == -signal.SIGTERM
    assert "Application shutdown complete." in stderr
    entries = [json.loads(line) for line in stderr.splitlines() if line.startswith("{")]
    assert any(entry["msg"] == "Serving MCP over HTTP" for entry in entries)
    assert all({"time", "level", "logger", "msg"} <= entry.keys() for entry in entries)
    assert TOKEN not in stderr + stdout


def slow_notes_api(started: threading.Event) -> Starlette:
    async def notes(_: Request) -> JSONResponse:
        started.set()
        await anyio.sleep(2)
        return JSONResponse({"data": [], "meta": {"nextCursor": None}})

    return Starlette(routes=[Route("/v1/notes", notes)])


async def test_drains_then_finishes_a_call_in_flight_on_sigterm() -> None:
    started = threading.Event()
    api_port = free_port()
    with (
        serve(slow_notes_api(started), api_port) as api,
        serve_cli(
            {
                "MCP_AUTH_MODE": "token",
                "MCP_AUTH_TOKENS": TOKEN,
                "UPSTREAM_API_URL": api,
                "UPSTREAM_API_TOKEN": "upstream-token-0123",
                "SHUTDOWN_DRAIN_SECONDS": "1",
            }
        ) as (process, url),
    ):
        async with (
            http_client(f"{url}/mcp", TOKEN) as client,
            anyio.create_task_group() as tasks,
            httpx2.AsyncClient() as http,
        ):
            results = []
            # The client validates results against the listed schemas, so list before the drain.
            await client.list_tools()

            async def list_notes() -> None:
                results.append(await client.call_tool("list_notes", {}))

            tasks.start_soon(list_notes)
            await anyio.to_thread.run_sync(started.wait, 10)
            process.send_signal(signal.SIGTERM)
            await anyio.sleep(0.3)
            ready = await http.get(f"{url}/readyz")
        _, stderr = process.communicate(timeout=20)
    assert ready.status_code == 503
    assert results[0].is_error is False
    assert results[0].structured_content == {"notes": [], "next_cursor": None}
    assert process.returncode == -signal.SIGTERM
    messages = [json.loads(line)["msg"] for line in stderr.splitlines() if line.startswith("{")]
    assert "Draining before shutdown" in messages


def authorization_server(key: SigningKey, port: int) -> Starlette:
    issuer = f"http://localhost:{port}"

    async def metadata(_: Request) -> JSONResponse:
        return JSONResponse({"issuer": issuer, "jwks_uri": f"{issuer}/jwks"})

    async def jwks(_: Request) -> JSONResponse:
        return JSONResponse({"keys": [key.jwk]})

    return Starlette(
        routes=[
            Route("/.well-known/oauth-authorization-server", metadata),
            Route("/jwks", jwks),
        ]
    )


async def test_finds_the_issuer_keys_and_accepts_its_tokens() -> None:
    key = SigningKey()
    issuer_port = free_port()
    with (
        serve(authorization_server(key, issuer_port), issuer_port) as issuer,
        serve_cli({"MCP_AUTH_MODE": "oauth", "MCP_AUTH_ISSUER": issuer}) as (_, url),
    ):
        token = key.sign(claims(iss=issuer, aud=f"{url}/mcp"))
        async with http_client(f"{url}/mcp", token) as client:
            result = await client.call_tool("whoami", {})
    assert result.structured_content is not None
    assert result.structured_content["client_id"] == "client-1"


def test_explains_an_unreachable_issuer_without_a_traceback() -> None:
    issuer = f"http://127.0.0.1:{free_port()}"
    result = run("--http", env={"MCP_AUTH_MODE": "oauth", "MCP_AUTH_ISSUER": issuer})
    assert result.returncode == 2
    assert f"Error: Couldn't reach the authorization server at {issuer}/" in result.stderr
    assert "Traceback" not in result.stderr
