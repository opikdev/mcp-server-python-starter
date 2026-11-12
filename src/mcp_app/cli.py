"""Entry point: stdio by default, or Streamable HTTP with `--http`."""

import argparse
import contextlib
import logging
import sys
import time
from collections.abc import AsyncIterator
from types import FrameType

import anyio
import httpx2
import uvicorn
from mcp.server.auth.provider import TokenVerifier
from starlette.applications import Starlette

from mcp_app import __version__
from mcp_app.auth.jwt import JwtVerifier, discover_jwks_url, remote_keys
from mcp_app.auth.scopes import ToolScopes
from mcp_app.auth.static import StaticTokenVerifier
from mcp_app.config import (
    ConfigError,
    ExchangeCredentialsConfig,
    HttpConfig,
    OAuthConfig,
    TokenConfig,
    UpstreamConfig,
    load_http_config,
    load_log_level,
    load_upstream_config,
)
from mcp_app.http import create_http_app
from mcp_app.log import configure_logging
from mcp_app.server import create_server
from mcp_app.telemetry import OperationMetrics, start_telemetry
from mcp_app.upstream.credentials import Credentials, StaticCredentials, TokenExchange
from mcp_app.upstream.notes_client import NotesClient

logger = logging.getLogger("mcp_app")


@contextlib.asynccontextmanager
async def _credentials(config: UpstreamConfig) -> AsyncIterator[Credentials]:
    match config.credentials:
        case ExchangeCredentialsConfig() as exchange:
            credentials = TokenExchange(exchange, timeout_seconds=config.timeout_seconds)
            try:
                yield credentials
            finally:
                await credentials.aclose()
        case static:
            yield StaticCredentials(static.token)


@contextlib.asynccontextmanager
async def _notes(config: UpstreamConfig | None) -> AsyncIterator[NotesClient | None]:
    if config is None:
        yield None
        return
    async with _credentials(config) as credentials:
        client = NotesClient(
            base_url=config.base_url,
            credentials=credentials,
            timeout_seconds=config.timeout_seconds,
        )
        try:
            yield client
        finally:
            await client.aclose()


async def _verifier(config: HttpConfig, tool_scopes: ToolScopes) -> TokenVerifier | None:
    match config.auth:
        case OAuthConfig(issuer=issuer, jwks_url=jwks_url):
            if jwks_url is None:
                async with httpx2.AsyncClient() as client:
                    jwks_url = await discover_jwks_url(issuer, client)
            return JwtVerifier(
                issuer=issuer, audience=config.public_url, keys=remote_keys(jwks_url)
            )
        case TokenConfig(tokens=tokens, scopes=scopes):
            # A static token has every scope the server uses.
            return StaticTokenVerifier(tokens, [*scopes, *tool_scopes.supported])
        case _:
            return None


async def _serve_stdio() -> None:
    upstream = load_upstream_config()
    if upstream is not None and isinstance(upstream.credentials, ExchangeCredentialsConfig):
        raise ConfigError("UPSTREAM_AUTH=exchange works only over HTTP with MCP_AUTH_MODE=oauth.")
    async with _notes(upstream) as notes:
        await create_server(transport="stdio", notes=notes).run_stdio_async()


class DrainingServer(uvicorn.Server):
    """On the first SIGTERM or SIGINT, fails readiness but keeps serving, then shuts down.

    The drain gives load balancers time to stop sending requests before connections close.
    Uvicorn then stops accepting and waits for requests in flight. A second signal skips the
    rest of the drain.
    """

    def __init__(self, config: uvicorn.Config, app: Starlette, drain_seconds: int) -> None:
        super().__init__(config)
        self.app = app
        self.drain_seconds = drain_seconds
        self.drain_until: float | None = None
        self.pending_exit: tuple[int, FrameType | None] | None = None
        self.announced = False

    def handle_exit(self, sig: int, frame: FrameType | None) -> None:
        if self.drain_until is None:
            self.app.state.draining = True
            self.drain_until = time.monotonic() + self.drain_seconds
            self.pending_exit = (sig, frame)
            return
        super().handle_exit(sig, frame)

    async def on_tick(self, counter: int) -> bool:
        if self.drain_until is not None and not self.announced:
            # Logged here, not in the signal handler, which may interrupt another log call.
            logger.info("Draining before shutdown", extra={"seconds": self.drain_seconds})
            self.announced = True
        if self.pending_exit and time.monotonic() >= (self.drain_until or 0):
            super().handle_exit(*self.pending_exit)
            self.pending_exit = None
        return await super().on_tick(counter)


async def _serve_http() -> None:
    config = load_http_config()
    upstream = load_upstream_config()
    telemetry = start_telemetry()
    tool_scopes = ToolScopes()
    try:
        async with _notes(upstream) as notes:
            server = create_server(
                transport="http",
                notes=notes,
                tool_scopes=tool_scopes,
                middleware=[OperationMetrics(telemetry.meter_provider)] if telemetry else (),
            )
            verifier = await _verifier(config, tool_scopes)
            app = create_http_app(
                config,
                server=server,
                tool_scopes=tool_scopes,
                verifier=verifier,
                telemetry=telemetry,
            )
            uvicorn_config = uvicorn.Config(
                app,
                host=config.host,
                port=config.port,
                log_config=None,
                timeout_graceful_shutdown=config.shutdown_timeout_seconds,
            )
            logger.info(
                "Serving MCP over HTTP",
                extra={"url": config.public_url, "auth": config.auth.mode, "host": config.host},
            )
            await DrainingServer(uvicorn_config, app, config.shutdown_drain_seconds).serve()
    finally:
        if telemetry is not None:
            telemetry.shutdown()


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
