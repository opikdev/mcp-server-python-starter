"""The Streamable HTTP app: health, protected resource metadata, bearer auth, and MCP."""

import contextlib
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from mcp_app.config import HttpConfig, NoAuthConfig, OAuthConfig
from mcp_app.server import create_server
from mcp_app.upstream.notes_client import NotesClient


def _auth_settings(config: HttpConfig) -> AuthSettings | None:
    match config.auth:
        case OAuthConfig(issuer=issuer, scopes=scopes):
            return AuthSettings(
                issuer_url=issuer,
                resource_server_url=config.public_url,
                required_scopes=scopes,
                # JwtVerifier checks the audience itself.
                validate_token_resource=False,
            )
        case NoAuthConfig():
            return None
        case token:
            # Static tokens have no authorization server, so publish no resource metadata.
            # The SDK needs an issuer to turn auth on, but nothing reads it without metadata.
            return AuthSettings(
                issuer_url=config.public_url,
                resource_server_url=None,
                required_scopes=token.scopes,
            )


def _transport_security(config: HttpConfig) -> TransportSecuritySettings:
    origin = urlsplit(config.public_url)
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[host for name in config.allowed_hosts for host in (name, f"{name}:*")],
        allowed_origins=[
            f"{origin.scheme}://{origin.netloc}",
            *(f"http://{name}:*" for name in ("localhost", "127.0.0.1", "[::1]")),
        ],
    )


async def _health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


def create_http_app(
    config: HttpConfig,
    *,
    verifier: TokenVerifier | None,
    notes: NotesClient | None = None,
    **server_options: Callable[[], datetime] | Any,
) -> Starlette:
    server = create_server(
        transport="http",
        notes=notes,
        token_verifier=verifier,
        auth=_auth_settings(config) if verifier else None,
        **server_options,
    )
    mcp_app = server.streamable_http_app(
        streamable_http_path=config.path,
        stateless_http=True,
        json_response=True,
        transport_security=_transport_security(config),
        host=config.host,
    )

    @contextlib.asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        async with server.session_manager.run():
            yield

    return Starlette(
        routes=[Route("/healthz", _health, methods=["GET"]), Mount("/", app=mcp_app)],
        lifespan=lifespan,
    )
