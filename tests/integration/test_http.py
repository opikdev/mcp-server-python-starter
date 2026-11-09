from collections.abc import Iterator

import anyio
import httpx2
import pytest
from mcp.types import TextContent

from mcp_app.auth.jwt import JwtVerifier
from mcp_app.auth.static import StaticTokenVerifier
from mcp_app.config import OAuthConfig, TokenConfig, load_http_config
from mcp_app.http import create_http_app
from mcp_app.upstream.notes_client import NotesClient
from tests.fake_notes_api import FakeNotesApi
from tests.helpers import FIXED_NOW, TOKEN, SigningKey, claims, free_port, http_client, serve

pytestmark = pytest.mark.anyio

ISSUER = "https://auth.example.com"
UPSTREAM_TOKEN = "upstream-secret-token-123"


@pytest.fixture(scope="module")
def token_server() -> Iterator[str]:
    port = free_port()
    config = load_http_config(
        {"PORT": str(port), "MCP_AUTH_MODE": "token", "MCP_AUTH_TOKENS": TOKEN}
    )
    assert isinstance(config.auth, TokenConfig)
    verifier = StaticTokenVerifier(config.auth.tokens, config.auth.scopes)
    app = create_http_app(config, verifier=verifier, now=lambda: FIXED_NOW)
    with serve(app, port) as url:
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
    notes = NotesClient(
        base_url="http://notes.test",
        token=UPSTREAM_TOKEN,
        timeout_seconds=5,
        transport=httpx2.ASGITransport(app=notes_api.app),
    )
    with serve(create_http_app(config, verifier=verifier, notes=notes), port) as url:
        yield url
    anyio.run(notes.aclose)


async def test_rejects_a_request_without_a_token_with_a_bearer_challenge(token_server: str) -> None:
    async with httpx2.AsyncClient() as http:
        response = await http.post(f"{token_server}/mcp", json={})
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Bearer")
    assert "resource_metadata" not in response.headers["www-authenticate"]


async def test_rejects_a_wrong_token(token_server: str) -> None:
    async with httpx2.AsyncClient() as http:
        response = await http.post(
            f"{token_server}/mcp", json={}, headers={"Authorization": "Bearer wrong-token-000000"}
        )
    assert response.status_code == 401


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_accepts_the_configured_token_in_both_protocol_eras(
    token_server: str, mode: str
) -> None:
    async with http_client(f"{token_server}/mcp", TOKEN, mode) as client:
        result = await client.call_tool("whoami", {})
    assert result.structured_content == {
        "transport": "http",
        "clientId": "token-1",
        "scopes": ["mcp", "notes:write"],
    }


async def test_uses_the_given_clock(token_server: str) -> None:
    async with http_client(f"{token_server}/mcp", TOKEN) as client:
        result = await client.call_tool("get_time", {})
    assert result.structured_content is not None
    assert result.structured_content["iso"] == "2026-11-08T12:30:00Z"


async def test_serves_health_without_a_token(token_server: str) -> None:
    async with httpx2.AsyncClient() as http:
        response = await http.get(f"{token_server}/healthz")
    assert response.json() == {"status": "ok"}


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
    with serve(create_http_app(config, verifier=None), port) as url:
        async with http_client(f"{url}/mcp") as client:
            result = await client.call_tool("whoami", {})
    assert result.structured_content == {"transport": "http", "clientId": None, "scopes": []}


async def test_publishes_protected_resource_metadata(oauth_server: str) -> None:
    async with httpx2.AsyncClient() as http:
        response = await http.get(f"{oauth_server}/.well-known/oauth-protected-resource/mcp")
    assert response.json() == {
        "resource": f"{oauth_server}/mcp",
        "authorization_servers": [ISSUER],
        "scopes_supported": ["mcp", "notes:write"],
        "bearer_methods_supported": ["header"],
    }


async def test_lists_only_the_base_scopes_when_the_notes_tools_are_off() -> None:
    config = load_http_config({"MCP_AUTH_MODE": "oauth", "MCP_AUTH_ISSUER": ISSUER})
    verifier = JwtVerifier(issuer=ISSUER, audience=config.public_url, keys=SigningKey())
    app = create_http_app(config, verifier=verifier)
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://localhost:3000"
    ) as http:
        response = await http.get("/.well-known/oauth-protected-resource/mcp")
    assert response.json()["scopes_supported"] == ["mcp"]


async def test_refuses_to_create_a_note_without_the_notes_write_scope(
    oauth_server: str, signing_key: SigningKey, notes_api: FakeNotesApi
) -> None:
    token = signing_key.sign(claims(aud=f"{oauth_server}/mcp", scope="mcp"))
    async with http_client(f"{oauth_server}/mcp", token) as client:
        result = await client.call_tool("create_note", {"title": "Buy milk"})
    content = result.content[0]
    assert result.is_error is True
    assert isinstance(content, TextContent)
    assert content.text.endswith(
        "This token lacks the notes:write scope. Reconnect with that scope to create notes."
    )
    assert notes_api.notes == []


async def test_creates_a_note_with_the_notes_write_scope(
    oauth_server: str, signing_key: SigningKey, notes_api: FakeNotesApi
) -> None:
    token = signing_key.sign(claims(aud=f"{oauth_server}/mcp", scope="mcp notes:write"))
    async with http_client(f"{oauth_server}/mcp", token) as client:
        result = await client.call_tool("create_note", {"title": "Buy milk"})
        listed = await client.call_tool("list_notes", {})
    assert result.is_error is False
    assert listed.structured_content is not None
    assert [note["title"] for note in listed.structured_content["notes"]] == ["Buy milk"]


async def test_points_clients_at_the_metadata_in_the_401_challenge(oauth_server: str) -> None:
    async with httpx2.AsyncClient() as http:
        response = await http.post(f"{oauth_server}/mcp", json={})
    assert response.status_code == 401
    assert (
        f'resource_metadata="{oauth_server}/.well-known/oauth-protected-resource/mcp"'
        in response.headers["www-authenticate"]
    )


async def test_serves_a_client_with_a_valid_access_token(
    oauth_server: str, signing_key: SigningKey
) -> None:
    token = signing_key.sign(claims(aud=f"{oauth_server}/mcp"))
    async with http_client(f"{oauth_server}/mcp", token) as client:
        result = await client.call_tool("whoami", {})
    assert result.structured_content == {
        "transport": "http",
        "clientId": "client-1",
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


async def test_rejects_a_token_without_the_mcp_scope(
    oauth_server: str, signing_key: SigningKey
) -> None:
    token = signing_key.sign(claims(aud=f"{oauth_server}/mcp", scope="notes"))
    async with httpx2.AsyncClient() as http:
        response = await http.post(
            f"{oauth_server}/mcp", json={}, headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 403
    assert 'error="insufficient_scope"' in response.headers["www-authenticate"]
