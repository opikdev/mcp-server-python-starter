"""The Streamable HTTP app: health, readiness, resource metadata, bearer auth, and MCP."""

import contextlib
from collections.abc import AsyncIterator
from urllib.parse import urlsplit

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import AuthContextMiddleware
from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend
from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.routes import build_resource_metadata_url, create_protected_resource_routes
from mcp.server.transport_security import TransportSecuritySettings
from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware
from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from mcp_app.auth.challenge import BearerChallenge
from mcp_app.auth.scopes import ToolScopes
from mcp_app.config import HttpConfig, NoAuthConfig, OAuthConfig
from mcp_app.telemetry import Telemetry

PROBE_PATHS = "/healthz$,/readyz$"


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


class PostOnly:
    """Refuses GET, which would open a stream that a stateless server never writes to."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["method"] == "GET":
            await Response(status_code=405, headers={"Allow": "POST"})(scope, receive, send)
            return
        await self._app(scope, receive, send)


def _problem(status: int, title: str, detail: str) -> JSONResponse:
    return JSONResponse(
        {"type": "about:blank", "title": title, "status": status, "detail": detail},
        status_code=status,
        media_type="application/problem+json",
        headers={"Retry-After": "5"},
    )


async def _health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


async def _ready(request: Request) -> JSONResponse:
    if request.app.state.draining:
        return _problem(503, "Draining", "The server is shutting down. Use another instance.")
    if not request.app.state.ready:
        return _problem(503, "Starting", "The server isn't ready yet.")
    return JSONResponse({"status": "ok"})


def create_http_app(
    config: HttpConfig,
    *,
    server: MCPServer,
    tool_scopes: ToolScopes,
    verifier: TokenVerifier | None,
    telemetry: Telemetry | None = None,
) -> Starlette:
    """Serves `server` at the path of `MCP_PUBLIC_URL`.

    Set `app.state.draining` to fail readiness while still serving, before a shutdown.
    """
    # SSE responses, not JSON-only, so progress and log notifications reach HTTP clients as
    # they reach stdio clients. JSON-only responses would drop them.
    mcp_app: ASGIApp = PostOnly(
        server.streamable_http_app(
            streamable_http_path=config.path,
            stateless_http=True,
            json_response=False,
            transport_security=_transport_security(config),
            host=config.host,
        )
    )
    routes = [
        Route("/healthz", _health, methods=["GET"]),
        Route("/readyz", _ready, methods=["GET"]),
    ]
    middleware: list[Middleware] = []
    if verifier is not None and not isinstance(config.auth, NoAuthConfig):
        metadata_url = None
        if isinstance(config.auth, OAuthConfig):
            resource = AnyHttpUrl(config.public_url)
            metadata_url = str(build_resource_metadata_url(resource))
            # Every scope a token needs, then each tool's scope, so clients ask for them.
            routes.extend(
                create_protected_resource_routes(
                    resource_url=resource,
                    authorization_servers=[AnyHttpUrl(config.auth.issuer)],
                    scopes_supported=list(
                        dict.fromkeys([*config.auth.scopes, *tool_scopes.supported])
                    ),
                )
            )
        mcp_app = BearerChallenge(
            mcp_app,
            required_scopes=config.auth.scopes,
            tool_scopes=tool_scopes,
            resource_metadata_url=metadata_url,
        )
        middleware = [
            Middleware(AuthenticationMiddleware, backend=BearerAuthBackend(verifier)),
            Middleware(AuthContextMiddleware),
        ]
    routes.append(Route(config.path, mcp_app))
    if telemetry is not None:
        # Probes run every few seconds, so tracing them would bury real requests.
        middleware.insert(
            0,
            Middleware(
                OpenTelemetryMiddleware,
                excluded_urls=PROBE_PATHS,
                tracer_provider=telemetry.tracer_provider,
                meter_provider=telemetry.meter_provider,
                exclude_spans=["receive", "send"],
            ),
        )

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        async with server.session_manager.run():
            app.state.ready = True
            yield

    app = Starlette(routes=routes, middleware=middleware, lifespan=lifespan)
    app.state.ready = False
    app.state.draining = False
    return app
