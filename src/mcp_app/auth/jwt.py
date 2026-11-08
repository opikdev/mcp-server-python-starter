"""OAuth access tokens: signed JWTs from your authorization server, checked against its JWKS."""

import logging
from typing import Any, Protocol
from urllib.parse import urlsplit

import anyio.to_thread
import httpx2
import jwt
from mcp.server.auth.provider import AccessToken

ALGORITHMS = ["RS256", "PS256", "ES256", "EdDSA"]
DISCOVERY_TIMEOUT_SECONDS = 5.0

logger = logging.getLogger(__name__)


class KeySource(Protocol):
    """Finds the key that signed a token. `PyJWKClient` satisfies it."""

    def get_signing_key_from_jwt(self, token: str) -> jwt.PyJWK: ...


def _scopes(claims: dict[str, Any]) -> list[str]:
    scope = claims.get("scope")
    if isinstance(scope, str):
        return scope.split()
    scp = claims.get("scp")
    if isinstance(scp, list):
        return [item for item in scp if isinstance(item, str)]
    return []


def _client(claims: dict[str, Any]) -> str:
    for claim in ("client_id", "azp", "sub"):
        value = claims.get(claim)
        if isinstance(value, str) and value:
            return value
    return "unknown"


class JwtVerifier:
    """Accepts JWTs signed with an allowed algorithm, for this issuer, audience, and an expiry."""

    def __init__(self, *, issuer: str, audience: str, keys: KeySource) -> None:
        self._issuer = issuer
        self._audience = audience
        self._keys = keys

    def _decode(self, token: str) -> dict[str, Any]:
        key = self._keys.get_signing_key_from_jwt(token)
        claims: dict[str, Any] = jwt.decode(
            token,
            key,
            algorithms=ALGORITHMS,
            audience=self._audience,
            issuer=self._issuer,
            options={"require": ["exp", "iss", "aud"]},
        )
        return claims

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            claims = await anyio.to_thread.run_sync(self._decode, token)
        except jwt.PyJWTError as error:
            logger.info("Rejected an access token", extra={"reason": type(error).__name__})
            return None
        return AccessToken(
            token=token,
            client_id=_client(claims),
            scopes=_scopes(claims),
            expires_at=int(claims["exp"]),
            resource=self._audience,
            subject=claims.get("sub"),
            claims={"iss": claims["iss"]},
        )


def _metadata_urls(issuer: str) -> list[str]:
    parts = urlsplit(issuer)
    origin = f"{parts.scheme}://{parts.netloc}"
    path = parts.path.rstrip("/")
    return [
        f"{origin}/.well-known/oauth-authorization-server{path}",
        f"{origin}{path}/.well-known/openid-configuration",
    ]


async def discover_jwks_url(issuer: str, client: httpx2.AsyncClient) -> str:
    """Reads `jwks_uri` from the issuer's OAuth or OpenID metadata, per RFC 8414."""
    for address in _metadata_urls(issuer):
        response = await client.get(address, timeout=DISCOVERY_TIMEOUT_SECONDS)
        if response.status_code != 200:
            continue
        metadata = response.json()
        if metadata.get("issuer") != issuer:
            raise RuntimeError(
                f"Authorization server metadata at {address} names issuer "
                f"{metadata.get('issuer')}, not {issuer}"
            )
        jwks_uri = metadata.get("jwks_uri")
        if isinstance(jwks_uri, str) and jwks_uri:
            return jwks_uri
    raise RuntimeError(f"Couldn't find a jwks_uri for {issuer}. Set MCP_AUTH_JWKS_URL.")


def remote_keys(jwks_url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=300, timeout=5)
