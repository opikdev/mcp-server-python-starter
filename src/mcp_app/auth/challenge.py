"""Bearer challenges for the MCP endpoint: 401 without a valid token, 403 without its scopes.

A `tools/call` for a tool that needs a scope the token lacks gets a 403 scope challenge before
the tool runs, so the client can ask for that scope and retry.
"""

import json
from collections.abc import Iterator

from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.transport_security import DEFAULT_MAX_REQUEST_BODY_SIZE
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from mcp_app.auth.scopes import ToolScopes


def _problem(
    status: int, title: str, detail: str, challenge: str
) -> tuple[bytes, list[tuple[bytes, bytes]]]:
    body = json.dumps(
        {"type": "about:blank", "title": title, "status": status, "detail": detail}
    ).encode()
    headers = [
        (b"content-type", b"application/problem+json"),
        (b"content-length", str(len(body)).encode()),
        (b"www-authenticate", challenge.encode()),
    ]
    return body, headers


def _called_tools(body: bytes) -> Iterator[str]:
    try:
        decoded = json.loads(body)
    except ValueError, RecursionError:
        return
    for message in decoded if isinstance(decoded, list) else [decoded]:
        if not isinstance(message, dict) or message.get("method") != "tools/call":
            continue
        params = message.get("params")
        name = params.get("name") if isinstance(params, dict) else None
        if isinstance(name, str):
            yield name


class BearerChallenge:
    """Wraps the MCP endpoint. Starlette's `AuthenticationMiddleware` must run first."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        required_scopes: list[str],
        tool_scopes: ToolScopes,
        resource_metadata_url: str | None,
    ) -> None:
        self._app = app
        self._required = required_scopes
        self._tool_scopes = tool_scopes
        self._metadata = resource_metadata_url

    def _challenge(self, scopes: list[str], error: str | None) -> str:
        params = [f'error="{error}"'] if error else []
        params.append(f'scope="{" ".join(scopes)}"')
        if self._metadata:
            params.append(f'resource_metadata="{self._metadata}"')
        return f"Bearer {', '.join(params)}"

    async def _reject(
        self, send: Send, status: int, scopes: list[str], error: str | None, detail: str
    ) -> None:
        title = "Unauthorized" if status == 401 else "Forbidden"
        body, headers = _problem(status, title, detail, self._challenge(scopes, error))
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        user = scope.get("user")
        if not isinstance(user, AuthenticatedUser):
            # RFC 6750 section 3.1: no error code when the request had no credentials.
            sent = Headers(scope=scope).get("authorization", "").lower().startswith("bearer ")
            await self._reject(
                send,
                401,
                self._required,
                "invalid_token" if sent else None,
                "The access token is invalid or expired." if sent else "Send an access token.",
            )
            return
        granted = set(user.scopes)
        if not set(self._required) <= granted:
            await self._reject(
                send,
                403,
                self._required,
                "insufficient_scope",
                f"The access token needs the scopes {' '.join(self._required)}.",
            )
            return
        if scope["method"] != "POST":
            await self._app(scope, receive, send)
            return
        body, receive = await _buffer(receive)
        if body is None:
            await self._app(scope, receive, send)
            return
        needed = [
            tool_scope
            for name in _called_tools(body)
            if (tool_scope := self._tool_scopes.for_tool(name)) is not None
        ]
        if not set(needed) <= granted:
            scopes = list(dict.fromkeys([*self._required, *needed]))
            await self._reject(
                send,
                403,
                scopes,
                "insufficient_scope",
                f"This tool needs the scopes {' '.join(scopes)}. Ask for them and retry.",
            )
            return
        await self._app(scope, receive, send)


async def _buffer(receive: Receive) -> tuple[bytes | None, Receive]:
    """Reads the request body, then replays it. Returns None for the body if it's too large.

    A body over the SDK's limit isn't parsed. The SDK rejects it with 413 as it reads on.
    """
    chunks: list[bytes] = []
    size = 0
    while True:
        message = await receive()
        if message["type"] != "http.request":
            return None, _replay([message], receive)
        chunks.append(message.get("body", b""))
        size += len(chunks[-1])
        more = message.get("more_body", False)
        too_large = size > DEFAULT_MAX_REQUEST_BODY_SIZE
        if too_large or not more:
            body = b"".join(chunks)
            replayed = _replay([{"type": "http.request", "body": body, "more_body": more}], receive)
            return (None if too_large else body), replayed


def _replay(messages: list[Message], receive: Receive) -> Receive:
    pending = list(messages)

    async def replayed() -> Message:
        if pending:
            return pending.pop(0)
        return await receive()

    return replayed
