"""Shared test helpers: a real HTTP server in a thread, MCP clients, and signing keys."""

import contextlib
import os
import socket
import subprocess
import sys
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
from mcp.server import MCPServer
from mcp.server.auth.provider import TokenVerifier
from starlette.applications import Starlette
from starlette.types import ASGIApp

from mcp_app.auth.scopes import ToolScopes
from mcp_app.config import HttpConfig
from mcp_app.http import create_http_app
from mcp_app.server import create_server
from mcp_app.telemetry import OperationMetrics, Telemetry
from mcp_app.upstream.credentials import StaticCredentials
from mcp_app.upstream.notes_client import NotesClient

FIXED_NOW = datetime(2026, 11, 8, 12, 30, tzinfo=UTC)
TOKEN = "test-token-0123456789"
COMMAND = [sys.executable, "-m", "mcp_app"]


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


@contextlib.contextmanager
def serve_cli(
    env: dict[str, str], port: int | None = None
) -> Iterator[tuple[subprocess.Popen[str], str]]:
    port = port or free_port()
    process = subprocess.Popen(
        [*COMMAND, "--http"],
        env={**os.environ, "PORT": str(port), "LOG_LEVEL": "info", **env},
        stderr=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
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
            # SIGTERM, not SIGKILL, so the process shuts down and saves its coverage.
            process.terminate()
            process.communicate(timeout=20)


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


def notes_client(
    token: str, transport: httpx2.AsyncBaseTransport | None = None, timeout_seconds: float = 5
) -> NotesClient:
    return NotesClient(
        base_url="http://notes.test",
        credentials=StaticCredentials(token),
        timeout_seconds=timeout_seconds,
        transport=transport,
    )


def http_app(
    config: HttpConfig,
    *,
    verifier: TokenVerifier | None,
    notes: NotesClient | None = None,
    server: MCPServer | None = None,
    telemetry: Telemetry | None = None,
) -> Starlette:
    """Builds the HTTP app as the CLI does, from `server` or the default tools."""
    scopes = ToolScopes()
    server = server or create_server(
        transport="http",
        notes=notes,
        now=lambda: FIXED_NOW,
        tool_scopes=scopes,
        middleware=[OperationMetrics(telemetry.meter_provider)] if telemetry else (),
    )
    return create_http_app(
        config, server=server, tool_scopes=scopes, verifier=verifier, telemetry=telemetry
    )


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
