"""Decides the credential for each backend call, so tools never handle one.

`StaticCredentials` sends one service token for every caller. `TokenExchange` swaps the caller's
MCP access token for a token meant for the backend (RFC 8693), and never sends the caller's own
token, because its audience is this server.
"""

import hashlib
import logging
import time
from collections.abc import Callable
from typing import Protocol
from urllib.parse import quote

import anyio
import httpx2
from mcp.server.auth.provider import AccessToken
from pydantic import BaseModel, ValidationError

from mcp_app.config import ExchangeCredentialsConfig
from mcp_app.upstream.errors import UpstreamError

TOKEN_EXCHANGE_GRANT = "urn:ietf:params:oauth:grant-type:token-exchange"  # noqa: S105 - a URN
ACCESS_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:access_token"  # noqa: S105 - a URN
EXPIRY_MARGIN_SECONDS = 30
MAX_CACHED_TOKENS = 1000

logger = logging.getLogger(__name__)


class Credentials(Protocol):
    setting: str
    """The settings an operator should check when the backend rejects the credential."""

    async def token(self, caller: AccessToken | None) -> str: ...


class StaticCredentials:
    setting = "UPSTREAM_API_TOKEN"

    def __init__(self, token: str) -> None:
        self._token = token

    async def token(self, caller: AccessToken | None) -> str:
        return self._token


class _ExchangeResponse(BaseModel):
    access_token: str
    expires_in: int | None = None


def _cache_key(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


class TokenExchange:
    """Exchanges each caller's access token at the authorization server, caching the result."""

    setting = "the TOKEN_EXCHANGE_ settings and UPSTREAM_AUDIENCE"

    def __init__(
        self,
        config: ExchangeCredentialsConfig,
        *,
        timeout_seconds: float,
        transport: httpx2.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._token_url = config.token_url
        self._audience = config.audience
        self._timeout = timeout_seconds
        self._clock = clock
        self._cache: dict[bytes, tuple[str, float]] = {}
        # RFC 6749 section 2.3.1: form-encode the client credentials before Basic auth.
        self._http = httpx2.AsyncClient(
            auth=httpx2.BasicAuth(
                quote(config.client_id, safe=""), quote(config.client_secret, safe="")
            ),
            headers={"Accept": "application/json"},
            timeout=timeout_seconds,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def token(self, caller: AccessToken | None) -> str:
        if caller is None:
            raise UpstreamError(
                "The notes API needs the caller's OAuth token, and this request has none. "
                "Connect over HTTP with OAuth."
            )
        key = _cache_key(caller.token)
        now = self._clock()
        cached = self._cache.get(key)
        if cached is not None and cached[1] > now:
            return cached[0]
        exchanged = await self._exchange(caller)
        if exchanged.expires_in is not None:
            expires_at = now + exchanged.expires_in
            if caller.expires_at is not None:
                expires_at = min(expires_at, caller.expires_at)
            self._remember(key, exchanged.access_token, expires_at - EXPIRY_MARGIN_SECONDS, now)
        return exchanged.access_token

    def _remember(self, key: bytes, token: str, expires_at: float, now: float) -> None:
        if expires_at <= now:
            return
        if len(self._cache) >= MAX_CACHED_TOKENS:
            self._cache = {k: v for k, v in self._cache.items() if v[1] > now}
        if len(self._cache) >= MAX_CACHED_TOKENS:
            del self._cache[next(iter(self._cache))]
        self._cache[key] = (token, expires_at)

    async def _exchange(self, caller: AccessToken) -> _ExchangeResponse:
        audit = {
            "client_id": caller.client_id,
            "subject": caller.subject,
            "audience": self._audience,
        }
        form = {
            "grant_type": TOKEN_EXCHANGE_GRANT,
            "subject_token": caller.token,
            "subject_token_type": ACCESS_TOKEN_TYPE,
            "requested_token_type": ACCESS_TOKEN_TYPE,
            "audience": self._audience,
        }
        try:
            with anyio.fail_after(self._timeout):
                response = await self._http.post(self._token_url, data=form)
        except (TimeoutError, httpx2.TransportError) as error:
            logger.warning("Token exchange failed", extra={**audit, "reason": type(error).__name__})
            raise UpstreamError(
                "Couldn't reach the authorization server to get a notes API token. Try again later."
            ) from None
        if not response.is_success:
            logger.warning(
                "Token exchange failed",
                extra={**audit, "status": response.status_code, "reason": _oauth_error(response)},
            )
            raise UpstreamError(
                "The authorization server wouldn't issue a notes API token for this user. "
                "Ask the operator to check the token exchange settings.",
                response.status_code,
            )
        try:
            exchanged = _ExchangeResponse.model_validate_json(response.content)
        except ValidationError:
            logger.warning("Token exchange failed", extra={**audit, "reason": "invalid response"})
            raise UpstreamError(
                "The authorization server sent a token response this server doesn't understand."
            ) from None
        logger.info("Exchanged a token for the notes API", extra=audit)
        return exchanged


def _oauth_error(response: httpx2.Response) -> str | None:
    try:
        error = response.json().get("error")
    except ValueError, AttributeError:
        return None
    return error if isinstance(error, str) else None
