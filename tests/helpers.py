"""Shared test helpers: a real HTTP server in a thread, MCP clients, and signing keys."""

import contextlib
import socket
import threading
import time
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Any

import httpx2
import jwt
import uvicorn
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from starlette.types import ASGIApp

FIXED_NOW = datetime(2026, 11, 8, 12, 30, tzinfo=UTC)
TOKEN = "test-token-0123456789"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


@contextlib.contextmanager
def serve(app: ASGIApp, port: int) -> Iterator[str]:
    """Runs the app on a real socket, so tests cover the same path a client takes."""
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None, lifespan="on")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:  # pragma: no cover
            raise RuntimeError("The test server didn't start")
        time.sleep(0.02)
    try:
        yield f"http://localhost:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


@contextlib.asynccontextmanager
async def http_client(
    url: str, token: str | None = None, mode: str = "auto"
) -> AsyncIterator[Client]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with (
        httpx2.AsyncClient(headers=headers) as http,
        Client(streamable_http_client(url, http_client=http), mode=mode) as client,
    ):
        yield client


class SigningKey:
    """An RSA key pair that signs test tokens, and serves its public key like a JWKS would."""

    def __init__(self, kid: str = "test-key") -> None:
        self.kid = kid
        self.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.jwk: dict[str, Any] = {
            **RSAAlgorithm.to_jwk(self.private.public_key(), as_dict=True),
            "kid": kid,
            "use": "sig",
        }

    def sign(self, claims: dict[str, Any], algorithm: str = "RS256") -> str:
        return jwt.encode(claims, self.private, algorithm=algorithm, headers={"kid": self.kid})

    def get_signing_key_from_jwt(self, token: str) -> jwt.PyJWK:
        algorithm = jwt.get_unverified_header(token)["alg"]
        return jwt.PyJWK.from_dict({**self.jwk, "alg": algorithm})


def claims(**overrides: Any) -> dict[str, Any]:
    now = int(time.time())
    return {
        "iss": "https://auth.example.com",
        "aud": "http://localhost:3000/mcp",
        "sub": "user-1",
        "client_id": "client-1",
        "scope": "mcp notes",
        "iat": now,
        "exp": now + 300,
        **overrides,
    }
