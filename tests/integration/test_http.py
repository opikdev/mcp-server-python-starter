import json
from collections.abc import Iterator
from typing import Any

import anyio
import httpx2
import pytest
from mcp.server.mcpserver import Context
from mcp.shared.exceptions import MCPError

from mcp_app.auth.jwt import JwtVerifier
from mcp_app.auth.static import StaticTokenVerifier
from mcp_app.config import OAuthConfig, TokenConfig, load_http_config
from mcp_app.server import create_server
from tests.fake_notes_api import FakeNotesApi
from tests.helpers import (
    TOKEN,
    SigningKey,
    claims,
    free_port,
    http_app,
    http_client,
    notes_client,
    serve,
)

pytestmark = pytest.mark.anyio

ISSUER = "https://auth.example.com"
UPSTREAM_TOKEN = "upstream-secret-token-123"


def call(tool: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments or {}},
    }


MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


@pytest.fixture(scope="module")
def token_server() -> Iterator[str]:
    port = free_port()
    config = load_http_config(
        {"PORT": str(port), "MCP_AUTH_MODE": "token", "MCP_AUTH_TOKENS": TOKEN}
    )
    assert isinstance(config.auth, TokenConfig)
    verifier = StaticTokenVerifier(config.auth.tokens, config.auth.scopes)
    with serve(http_app(config, verifier=verifier), port) as url:
        yield url


@pytest.fixture(scope="module")
def signing_key() -> SigningKey:
    return SigningKey()


@pytest.fixture(scope="module")
def notes_api() -> FakeNotesApi:
    return FakeNotesApi(UPSTREAM_TOKEN)


@pytest.fixture(scope="module")
def oauth_server(signing_key: SigningKey, notes_api: FakeNotesApi) -> Iterator[str]:
    port = free_port()
    config = load_http_config(
        {"PORT": str(port), "MCP_AUTH_MODE": "oauth", "MCP_AUTH_ISSUER": ISSUER}
    )
    assert isinstance(config.auth, OAuthConfig)
    verifier = JwtVerifier(issuer=ISSUER, audience=config.public_url, keys=signing_key)
    notes = notes_client(UPSTREAM_TOKEN, httpx2.ASGITransport(app=notes_api.app))
    with serve(http_app(config, verifier=verifier, notes=notes), port) as url:
        yield url
    anyio.run(notes.aclose)


async def test_challenges_a_request_without_a_token_with_no_error_code(token_server: str) -> None:
    async with httpx2.AsyncClient() as http:
        response = await http.post(f"{token_server}/mcp", json={})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Bearer scope="mcp"'
    assert response.headers["content-type"] == "application/problem+json"


async def test_challenges_a_wrong_token_as_invalid(token_server: str) -> None:
    async with httpx2.AsyncClient() as http:
        response = await http.post(
            f"{token_server}/mcp", json={}, headers={"Authorization": "Bearer wrong-token-000000"}
        )
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Bearer error="invalid_token", scope="mcp"'


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_accepts_the_configured_token_in_both_protocol_eras(
    token_server: str, mode: str
) -> None:
    async with http_client(f"{token_server}/mcp", TOKEN, mode) as client:
        result = await client.call_tool("whoami", {})
    assert result.structured_content == {
        "transport": "http",
        "client_id": "token-1",
        "scopes": ["mcp"],
    }


async def test_uses_the_given_clock(token_server: str) -> None:
    async with http_client(f"{token_server}/mcp", TOKEN) as client:
        result = await client.call_tool("get_time", {})
    assert result.structured_content is not None
    assert result.structured_content["iso"] == "2026-11-08T12:30:00Z"


async def test_serves_health_and_readiness_without_a_token(token_server: str) -> None:
    async with httpx2.AsyncClient() as http:
        health = await http.get(f"{token_server}/healthz")
        ready = await http.get(f"{token_server}/readyz")
    assert health.json() == {"status": "ok"}
    assert ready.json() == {"status": "ok"}


async def test_reports_unready_while_draining_but_keeps_serving() -> None:
    config = load_http_config({"MCP_AUTH_MODE": "token", "MCP_AUTH_TOKENS": TOKEN})
    app = http_app(config, verifier=StaticTokenVerifier([TOKEN], ["mcp"]))
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://localhost:3000"
    ) as http:
        starting = await http.get("/readyz")
        app.state.ready = True
        app.state.draining = True
        draining = await http.get("/readyz")
        health = await http.get("/healthz")
    assert (starting.status_code, starting.json()["title"]) == (503, "Starting")
    assert (draining.status_code, draining.json()["title"]) == (503, "Draining")
    assert draining.headers["content-type"] == "application/problem+json"
    assert health.status_code == 200


async def test_refuses_a_get_stream_that_a_stateless_server_never_writes_to(
    token_server: str,
) -> None:
    async with httpx2.AsyncClient(timeout=5) as http:
        response = await http.get(
            f"{token_server}/mcp",
            headers={"Authorization": f"Bearer {TOKEN}", "Accept": "text/event-stream"},
        )
    assert response.status_code == 405
    assert response.headers["allow"] == "POST"


async def test_blocks_a_dns_rebinding_attempt(token_server: str) -> None:
    async with httpx2.AsyncClient() as http:
        response = await http.post(
            f"{token_server}/mcp",
            json={},
            headers={"Host": "attacker.example", "Authorization": f"Bearer {TOKEN}"},
        )
    assert response.status_code == 421


async def test_has_no_protected_resource_metadata_because_it_is_not_oauth(
    token_server: str,
) -> None:
    async with httpx2.AsyncClient() as http:
        response = await http.get(f"{token_server}/.well-known/oauth-protected-resource/mcp")
    assert response.status_code == 404


async def test_serves_any_local_client_without_auth_on_localhost() -> None:
    port = free_port()
    config = load_http_config({"PORT": str(port), "MCP_AUTH_MODE": "none"})
    with serve(http_app(config, verifier=None), port) as url:
        async with http_client(f"{url}/mcp") as client:
            result = await client.call_tool("whoami", {})
    assert result.structured_content == {"transport": "http", "client_id": None, "scopes": ["mcp"]}


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_streams_progress_notifications_to_http_clients(mode: str) -> None:
    server = create_server(transport="http")

    @server.tool()
    async def count(ctx: Context) -> str:
        """Reports progress twice."""
        await ctx.report_progress(1, 2)
        await ctx.report_progress(2, 2)
        return "done"

    received: list[float] = []

    async def record(progress: float, total: float | None, message: str | None) -> None:
        received.append(progress)

    port = free_port()
    config = load_http_config({"PORT": str(port), "MCP_AUTH_MODE": "none"})
    with serve(http_app(config, verifier=None, server=server), port) as url:
        async with http_client(f"{url}/mcp", mode=mode) as client:
            result = await client.call_tool("count", {}, progress_callback=record)
    assert result.is_error is False
    assert received == [1, 2]


async def test_publishes_protected_resource_metadata_with_every_tool_scope(
    oauth_server: str,
) -> None:
    async with httpx2.AsyncClient() as http:
        response = await http.get(f"{oauth_server}/.well-known/oauth-protected-resource/mcp")
    assert response.json() == {
        "resource": f"{oauth_server}/mcp",
        "authorization_servers": [f"{ISSUER}/"],
        "scopes_supported": ["mcp", "notes:read", "notes:write"],
        "bearer_methods_supported": ["header"],
    }


async def test_lists_only_the_base_scopes_when_the_notes_tools_are_off() -> None:
    config = load_http_config({"MCP_AUTH_MODE": "oauth", "MCP_AUTH_ISSUER": ISSUER})
    verifier = JwtVerifier(issuer=ISSUER, audience=config.public_url, keys=SigningKey())
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=http_app(config, verifier=verifier)),
        base_url="http://localhost:3000",
    ) as http:
        response = await http.get("/.well-known/oauth-protected-resource/mcp")
    assert response.json()["scopes_supported"] == ["mcp"]


@pytest.mark.parametrize(
    ("tool", "granted", "challenged"),
    [
        ("create_note", "mcp notes:read", "mcp notes:write"),
        ("list_notes", "mcp notes:write", "mcp notes:read"),
    ],
)
async def test_challenges_a_tool_call_without_the_tool_scope(
    oauth_server: str,
    signing_key: SigningKey,
    notes_api: FakeNotesApi,
    tool: str,
    granted: str,
    challenged: str,
) -> None:
    token = signing_key.sign(claims(aud=f"{oauth_server}/mcp", scope=granted))
    before = len(notes_api.requests)
    async with httpx2.AsyncClient() as http:
        response = await http.post(
            f"{oauth_server}/mcp",
            json=call(tool, {"title": "Buy milk"} if tool == "create_note" else {}),
            headers={**MCP_HEADERS, "Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 403
    assert response.headers["www-authenticate"] == (
        f'Bearer error="insufficient_scope", scope="{challenged}", '
        f'resource_metadata="{oauth_server}/.well-known/oauth-protected-resource/mcp"'
    )
    assert len(notes_api.requests) == before


async def test_challenges_a_modern_client_before_the_tool_runs(
    oauth_server: str, signing_key: SigningKey, notes_api: FakeNotesApi
) -> None:
    token = signing_key.sign(claims(aud=f"{oauth_server}/mcp", scope="mcp notes:read"))
    before = len(notes_api.requests)
    async with http_client(f"{oauth_server}/mcp", token) as client:
        with pytest.raises(MCPError):
            await client.call_tool("create_note", {"title": "Buy milk"})
    assert len(notes_api.requests) == before


async def test_lets_other_calls_through_with_only_the_base_scope(
    oauth_server: str, signing_key: SigningKey
) -> None:
    token = signing_key.sign(claims(aud=f"{oauth_server}/mcp", scope="mcp"))
    async with http_client(f"{oauth_server}/mcp", token) as client:
        tools = {tool.name for tool in (await client.list_tools()).tools}
        result = await client.call_tool("whoami", {})
    assert {"list_notes", "create_note"} <= tools
    assert result.structured_content is not None
    assert result.structured_content["scopes"] == ["mcp"]


async def test_creates_and_lists_notes_with_both_notes_scopes(
    oauth_server: str, signing_key: SigningKey
) -> None:
    token = signing_key.sign(claims(aud=f"{oauth_server}/mcp", scope="mcp notes:read notes:write"))
    async with http_client(f"{oauth_server}/mcp", token) as client:
        result = await client.call_tool("create_note", {"title": "Buy milk"})
        listed = await client.call_tool("list_notes", {})
    assert result.is_error is False
    assert listed.structured_content is not None
    assert "Buy milk" in [note["title"] for note in listed.structured_content["notes"]]


async def test_points_clients_at_the_metadata_and_base_scope_in_the_401_challenge(
    oauth_server: str,
) -> None:
    async with httpx2.AsyncClient() as http:
        response = await http.post(f"{oauth_server}/mcp", json={})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == (
        f'Bearer scope="mcp", '
        f'resource_metadata="{oauth_server}/.well-known/oauth-protected-resource/mcp"'
    )


async def test_serves_a_client_with_a_valid_access_token(
    oauth_server: str, signing_key: SigningKey
) -> None:
    token = signing_key.sign(claims(aud=f"{oauth_server}/mcp"))
    async with http_client(f"{oauth_server}/mcp", token) as client:
        result = await client.call_tool("whoami", {})
    assert result.structured_content == {
        "transport": "http",
        "client_id": "client-1",
        "scopes": ["mcp", "notes"],
    }


@pytest.mark.parametrize(
    ("label", "overrides"),
    [
        ("another resource", {"aud": "https://other.example.com/mcp"}),
        ("another issuer", {"iss": "https://evil.example.com"}),
        ("an expired token", {"exp": 1}),
    ],
)
async def test_rejects_a_token_that_is_not_for_this_server(
    oauth_server: str, signing_key: SigningKey, label: str, overrides: dict[str, object]
) -> None:
    token = signing_key.sign(claims(aud=f"{oauth_server}/mcp") | overrides)
    async with httpx2.AsyncClient() as http:
        response = await http.post(
            f"{oauth_server}/mcp", json={}, headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 401, label
    assert 'error="invalid_token"' in response.headers["www-authenticate"], label


async def test_challenges_a_token_without_the_base_scope(
    oauth_server: str, signing_key: SigningKey
) -> None:
    token = signing_key.sign(claims(aud=f"{oauth_server}/mcp", scope="notes:read"))
    async with httpx2.AsyncClient() as http:
        response = await http.post(
            f"{oauth_server}/mcp",
            content=json.dumps(call("whoami")),
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 403
    assert response.headers["www-authenticate"] == (
        f'Bearer error="insufficient_scope", scope="mcp", '
        f'resource_metadata="{oauth_server}/.well-known/oauth-protected-resource/mcp"'
    )
