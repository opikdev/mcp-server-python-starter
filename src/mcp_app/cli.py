"""Entry point: stdio by default, or Streamable HTTP with `--http`."""

import argparse
import contextlib
import logging
import sys
from collections.abc import AsyncIterator

import anyio
import httpx2
import uvicorn
from mcp.server.auth.provider import TokenVerifier

from mcp_app import __version__
from mcp_app.auth.jwt import JwtVerifier, discover_jwks_url, remote_keys
from mcp_app.auth.static import StaticTokenVerifier
from mcp_app.config import (
    ConfigError,
    HttpConfig,
    OAuthConfig,
    TokenConfig,
    load_http_config,
    load_log_level,
    load_upstream_config,
)
from mcp_app.http import create_http_app
from mcp_app.log import configure_logging
from mcp_app.server import create_server
from mcp_app.upstream.notes_client import NotesClient

logger = logging.getLogger("mcp_app")


@contextlib.asynccontextmanager
async def _notes() -> AsyncIterator[NotesClient | None]:
    config = load_upstream_config()
    if config is None:
        yield None
        return
    client = NotesClient(
        base_url=config.base_url, token=config.token, timeout_seconds=config.timeout_seconds
    )
    try:
        yield client
    finally:
        await client.aclose()


async def _verifier(config: HttpConfig) -> TokenVerifier | None:
    match config.auth:
        case OAuthConfig(issuer=issuer, jwks_url=jwks_url):
            if jwks_url is None:
                async with httpx2.AsyncClient() as client:
                    jwks_url = await discover_jwks_url(issuer, client)
            return JwtVerifier(
                issuer=issuer, audience=config.public_url, keys=remote_keys(jwks_url)
            )
        case TokenConfig(tokens=tokens, scopes=scopes):
            return StaticTokenVerifier(tokens, scopes)
        case _:
            return None


async def _serve_stdio() -> None:
    async with _notes() as notes:
        await create_server(transport="stdio", notes=notes).run_stdio_async()


async def _serve_http() -> None:
    config = load_http_config()
    verifier = await _verifier(config)
    async with _notes() as notes:
        app = create_http_app(config, verifier=verifier, notes=notes)
        server = uvicorn.Server(
            uvicorn.Config(app, host=config.host, port=config.port, log_config=None)
        )
        logger.info(
            "Serving MCP over HTTP",
            extra={"url": config.public_url, "auth": config.auth.mode, "host": config.host},
        )
        await server.serve()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="mcp-server-python-starter", description="An MCP server over stdio or HTTP."
    )
    parser.add_argument("--http", action="store_true", help="serve Streamable HTTP, not stdio")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)

    try:
        configure_logging(load_log_level())
        anyio.run(_serve_http if args.http else _serve_stdio)
    except ConfigError as error:
        sys.stderr.write(f"Error: {error}\n")
        sys.exit(2)
    except KeyboardInterrupt:
        pass
