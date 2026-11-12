"""Exchanges a Keycloak user's token for a notes API token, with the realm in compose.auth.yaml."""

import base64
import json
import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import httpx2
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from tests.helpers import free_port, http_client, serve, serve_cli

ROOT = Path(__file__).parents[2]
PROJECT = "mcp-auth-python-e2e"

pytestmark = pytest.mark.anyio


def claims_of(token: str) -> dict[str, object]:
    payload = token.split(".")[1]
    decoded: dict[str, object] = json.loads(
        base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
    )
    return decoded


class RecordingUpstream:
    """A notes API that accepts any bearer token and records each one it receives."""

    def __init__(self) -> None:
        self.tokens: list[str] = []
        self.app = Starlette(routes=[Route("/v1/notes", self._notes, methods=["GET"])])

    async def _notes(self, request: Request) -> JSONResponse:
        self.tokens.append(request.headers["authorization"].removeprefix("Bearer "))
        return JSONResponse({"data": [], "meta": {"limit": 10, "nextCursor": None}})


@pytest.fixture(scope="module")
def mcp_port() -> int:
    return free_port()


@pytest.fixture(scope="module")
def keycloak(mcp_port: int) -> Iterator[str]:
    env = {
        **os.environ,
        "KEYCLOAK_PORT": str(free_port()),
        "MCP_PUBLIC_URL": f"http://localhost:{mcp_port}/mcp",
    }
    command = ["docker", "compose", "--project-name", PROJECT, "-f", "compose.auth.yaml"]
    subprocess.run(
        [*command, "up", "--detach", "--wait"], cwd=ROOT, env=env, check=True, capture_output=True
    )
    try:
        yield f"http://localhost:{env['KEYCLOAK_PORT']}/realms/mcp"
    finally:
        subprocess.run(
            [*command, "down", "--volumes"], cwd=ROOT, env=env, check=True, capture_output=True
        )


def user_token(issuer: str, scope: str) -> str:
    response = httpx2.post(
        f"{issuer}/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "mcp-client",
            "username": "demo",
            "password": "demo-password-123",
            "scope": scope,
        },
    )
    response.raise_for_status()
    token: str = response.json()["access_token"]
    return token


async def test_sends_the_upstream_an_exchanged_token_never_the_callers(
    keycloak: str, mcp_port: int
) -> None:
    upstream = RecordingUpstream()
    with serve(upstream.app, free_port()) as upstream_url:
        env = {
            "MCP_AUTH_MODE": "oauth",
            "MCP_AUTH_ISSUER": keycloak,
            "MCP_PUBLIC_URL": f"http://localhost:{mcp_port}/mcp",
            "UPSTREAM_API_URL": upstream_url,
            "UPSTREAM_AUTH": "exchange",
            "UPSTREAM_AUDIENCE": "notes-api",
            "TOKEN_EXCHANGE_URL": f"{keycloak}/protocol/openid-connect/token",
            "TOKEN_EXCHANGE_CLIENT_ID": "mcp-server",
            "TOKEN_EXCHANGE_CLIENT_SECRET": "mcp-server-dev-secret",
        }
        with serve_cli(env, port=mcp_port) as (_, url):
            caller = user_token(keycloak, "mcp notes:read")
            async with http_client(f"{url}/mcp", caller) as client:
                result = await client.call_tool("list_notes", {})
                await client.call_tool("list_notes", {})
    assert result.is_error is False, result.content
    assert len(upstream.tokens) == 2
    assert caller not in upstream.tokens
    assert upstream.tokens[0] == upstream.tokens[1]
    exchanged = claims_of(upstream.tokens[0])
    assert exchanged["aud"] == "notes-api"
    assert exchanged["sub"] == claims_of(caller)["sub"]


async def test_challenges_a_keycloak_token_without_the_read_scope(
    keycloak: str, mcp_port: int
) -> None:
    env = {
        "MCP_AUTH_MODE": "oauth",
        "MCP_AUTH_ISSUER": keycloak,
        "MCP_PUBLIC_URL": f"http://localhost:{mcp_port}/mcp",
        "UPSTREAM_API_URL": "http://127.0.0.1:9/",
        "UPSTREAM_API_TOKEN": "unused-static-token",
    }
    call = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "list_notes", "arguments": {}},
    }
    with serve_cli(env, port=mcp_port) as (_, url):
        response = httpx2.post(
            f"{url}/mcp",
            json=call,
            headers={
                "Authorization": f"Bearer {user_token(keycloak, 'mcp')}",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-11-25",
            },
        )
    assert response.status_code == 403
    assert 'scope="mcp notes:read"' in response.headers["www-authenticate"]
