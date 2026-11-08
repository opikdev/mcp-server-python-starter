import json
from typing import Any

import httpx2
import pytest

from mcp_app.auth.jwt import JwtVerifier, discover_jwks_url
from mcp_app.auth.static import StaticTokenVerifier
from tests.helpers import SigningKey, claims

pytestmark = pytest.mark.anyio

ISSUER = "https://auth.example.com"
AUDIENCE = "http://localhost:3000/mcp"


@pytest.fixture(scope="module")
def key() -> SigningKey:
    return SigningKey()


def verifier(key: SigningKey) -> JwtVerifier:
    return JwtVerifier(issuer=ISSUER, audience=AUDIENCE, keys=key)


async def test_static_verifier_accepts_each_configured_token() -> None:
    tokens = ["first-token-0123456", "second-token-012345"]
    static = StaticTokenVerifier(tokens, ["mcp"])
    first, second = [await static.verify_token(token) for token in tokens]
    assert first is not None
    assert second is not None
    assert (first.client_id, second.client_id, second.scopes) == ("token-1", "token-2", ["mcp"])
    assert await static.verify_token("first-token-012345") is None


async def test_jwt_verifier_accepts_a_valid_token_and_reads_its_claims(key: SigningKey) -> None:
    token = await verifier(key).verify_token(key.sign(claims()))
    assert token is not None
    assert (token.client_id, token.scopes, token.subject, token.resource) == (
        "client-1",
        ["mcp", "notes"],
        "user-1",
        AUDIENCE,
    )
    assert token.expires_at is not None


async def test_jwt_verifier_reads_scopes_from_an_scp_array(key: SigningKey) -> None:
    payload = claims(scp=["mcp", 7, "write"])
    del payload["scope"]
    token = await verifier(key).verify_token(key.sign(payload))
    assert token is not None
    assert token.scopes == ["mcp", "write"]


@pytest.mark.parametrize(
    ("drop", "expected"), [(["client_id"], "user-1"), (["client_id", "sub"], "unknown")]
)
async def test_jwt_verifier_falls_back_to_azp_then_sub_for_the_client(
    key: SigningKey, drop: list[str], expected: str
) -> None:
    payload = {name: value for name, value in claims().items() if name not in drop}
    token = await verifier(key).verify_token(key.sign(payload))
    assert token is not None
    assert token.client_id == expected
    with_azp = await verifier(key).verify_token(key.sign(payload | {"azp": "app-9"}))
    assert with_azp is not None
    assert with_azp.client_id == "app-9"


@pytest.mark.parametrize(
    "overrides",
    [{"aud": "https://elsewhere.example/mcp"}, {"iss": "https://evil.example"}, {"exp": 10}],
)
async def test_jwt_verifier_rejects_a_token_not_meant_for_this_server(
    key: SigningKey, overrides: dict[str, Any]
) -> None:
    assert await verifier(key).verify_token(key.sign(claims() | overrides)) is None


async def test_jwt_verifier_requires_an_expiry(key: SigningKey) -> None:
    payload = claims()
    del payload["exp"]
    assert await verifier(key).verify_token(key.sign(payload)) is None


async def test_jwt_verifier_rejects_an_algorithm_outside_the_allowlist_even_with_a_valid_key(
    key: SigningKey,
) -> None:
    assert await verifier(key).verify_token(key.sign(claims(), algorithm="RS512")) is None


async def test_jwt_verifier_rejects_a_token_signed_by_another_key(key: SigningKey) -> None:
    assert await verifier(key).verify_token(SigningKey().sign(claims())) is None


def metadata_server(responses: dict[str, dict[str, str]]) -> httpx2.AsyncClient:
    def handle(request: httpx2.Request) -> httpx2.Response:
        body = responses.get(str(request.url))
        if body is None:
            return httpx2.Response(404)
        return httpx2.Response(200, content=json.dumps(body))

    return httpx2.AsyncClient(transport=httpx2.MockTransport(handle))


async def test_discovery_reads_jwks_uri_from_oauth_metadata() -> None:
    client = metadata_server(
        {
            f"{ISSUER}/.well-known/oauth-authorization-server": {
                "issuer": ISSUER,
                "jwks_uri": f"{ISSUER}/jwks",
            }
        }
    )
    assert await discover_jwks_url(ISSUER, client) == f"{ISSUER}/jwks"


async def test_discovery_falls_back_to_openid_metadata_keeping_the_issuer_path() -> None:
    issuer = f"{ISSUER}/realms/demo"
    client = metadata_server(
        {
            f"{issuer}/.well-known/openid-configuration": {
                "issuer": issuer,
                "jwks_uri": f"{issuer}/certs",
            }
        }
    )
    assert await discover_jwks_url(issuer, client) == f"{issuer}/certs"


async def test_discovery_rejects_metadata_for_another_issuer() -> None:
    client = metadata_server(
        {
            f"{ISSUER}/.well-known/oauth-authorization-server": {
                "issuer": "https://evil.example",
                "jwks_uri": "https://evil.example/jwks",
            }
        }
    )
    with pytest.raises(RuntimeError, match=r"names issuer https://evil\.example"):
        await discover_jwks_url(ISSUER, client)


async def test_discovery_explains_how_to_fix_missing_metadata() -> None:
    with pytest.raises(RuntimeError, match="Set MCP_AUTH_JWKS_URL"):
        await discover_jwks_url(ISSUER, metadata_server({}))
