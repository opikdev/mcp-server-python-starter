import base64
import json
import logging
from urllib.parse import parse_qs

import httpx2
import pytest
from mcp.server.auth.provider import AccessToken

from mcp_app.config import ExchangeCredentialsConfig
from mcp_app.upstream.credentials import StaticCredentials, TokenExchange
from mcp_app.upstream.errors import UpstreamError

pytestmark = pytest.mark.anyio

CALLER_TOKEN = "caller-access-token-0123"
CONFIG = ExchangeCredentialsConfig(
    token_url="https://auth.example.com/token",
    client_id="mcp server",
    client_secret="exchange-secret:1",
    audience="notes-api",
)


def caller(token: str = CALLER_TOKEN, expires_at: int | None = 10_000) -> AccessToken:
    return AccessToken(
        token=token, client_id="client-1", scopes=["mcp"], expires_at=expires_at, subject="user-1"
    )


class AuthorizationServer:
    def __init__(self, response: httpx2.Response | None = None) -> None:
        self.requests: list[httpx2.Request] = []
        self.response = response

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if self.response is not None:
            return self.response
        subject = parse_qs(request.content.decode())["subject_token"][0]
        return httpx2.Response(
            200,
            json={
                "access_token": f"exchanged-{subject}-{len(self.requests)}",
                "issued_token_type": "urn:ietf:params:oauth:token-type:access_token",
                "token_type": "Bearer",
                "expires_in": 300,
            },
        )


def exchange(server: AuthorizationServer, now: list[float]) -> TokenExchange:
    return TokenExchange(
        CONFIG,
        timeout_seconds=1,
        transport=httpx2.MockTransport(server.handle),
        clock=lambda: now[0],
    )


async def test_static_credentials_send_the_service_token_for_every_caller() -> None:
    static = StaticCredentials("service-token")
    assert await static.token(caller()) == "service-token"
    assert await static.token(None) == "service-token"


async def test_exchanges_the_callers_token_for_one_meant_for_the_upstream() -> None:
    server = AuthorizationServer()
    token = await exchange(server, [1000.0]).token(caller())
    assert token == f"exchanged-{CALLER_TOKEN}-1"
    request = server.requests[0]
    assert parse_qs(request.content.decode()) == {
        "grant_type": ["urn:ietf:params:oauth:grant-type:token-exchange"],
        "subject_token": [CALLER_TOKEN],
        "subject_token_type": ["urn:ietf:params:oauth:token-type:access_token"],
        "requested_token_type": ["urn:ietf:params:oauth:token-type:access_token"],
        "audience": ["notes-api"],
    }
    basic = base64.b64decode(request.headers["authorization"].removeprefix("Basic ")).decode()
    assert basic == "mcp%20server:exchange-secret%3A1"


async def test_caches_each_exchanged_token_until_shortly_before_it_expires() -> None:
    server = AuthorizationServer()
    now = [1000.0]
    credentials = exchange(server, now)
    first = await credentials.token(caller())
    now[0] = 1000 + 300 - 31
    assert await credentials.token(caller()) == first
    assert await credentials.token(caller("another-caller-token")) != first
    now[0] = 1000 + 300 - 30
    assert await credentials.token(caller()) != first
    assert len(server.requests) == 3


async def test_never_caches_past_the_callers_own_expiry() -> None:
    server = AuthorizationServer()
    now = [1000.0]
    credentials = exchange(server, now)
    await credentials.token(caller(expires_at=1100))
    now[0] = 1100 - 30
    await credentials.token(caller(expires_at=1100))
    assert len(server.requests) == 2


async def test_refuses_a_call_without_a_caller_token() -> None:
    server = AuthorizationServer()
    with pytest.raises(UpstreamError, match="needs the caller's OAuth token"):
        await exchange(server, [0.0]).token(None)
    assert server.requests == []


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (
            httpx2.Response(400, json={"error": "invalid_target"}),
            "wouldn't issue a notes API token",
        ),
        (httpx2.Response(200, json={"token_type": "Bearer"}), "doesn't understand"),
    ],
)
async def test_turns_a_failed_exchange_into_a_tool_error_and_logs_it_without_the_token(
    caplog: pytest.LogCaptureFixture, response: httpx2.Response, message: str
) -> None:
    server = AuthorizationServer(response)
    with caplog.at_level(logging.INFO), pytest.raises(UpstreamError, match=message) as error:
        await exchange(server, [0.0]).token(caller())
    assert CALLER_TOKEN not in str(error.value)
    [record] = [record for record in caplog.records if record.msg == "Token exchange failed"]
    assert {key: record.__dict__[key] for key in ("subject", "client_id", "audience")} == {
        "subject": "user-1",
        "client_id": "client-1",
        "audience": "notes-api",
    }
    assert CALLER_TOKEN not in json.dumps(record.__dict__, default=str)


@pytest.mark.parametrize(
    ("error", "reason"),
    [("invalid_target", "invalid_target"), ("client secret s3cret was wrong", None)],
)
async def test_logs_only_standard_oauth_error_codes(
    caplog: pytest.LogCaptureFixture, error: str, reason: str | None
) -> None:
    server = AuthorizationServer(httpx2.Response(400, json={"error": error}))
    with caplog.at_level(logging.INFO), pytest.raises(UpstreamError):
        await exchange(server, [0.0]).token(caller())
    [record] = [record for record in caplog.records if record.msg == "Token exchange failed"]
    assert record.__dict__["reason"] == reason


async def test_explains_an_unreachable_authorization_server() -> None:
    def handle(_: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused")

    credentials = TokenExchange(CONFIG, timeout_seconds=1, transport=httpx2.MockTransport(handle))
    with pytest.raises(UpstreamError, match="Couldn't reach the authorization server"):
        await credentials.token(caller())
