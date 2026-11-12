"""Scopes: `mcp` for every request, plus one per tool that reads or changes data."""

from collections.abc import Callable

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.mcpserver.exceptions import ToolError

BASE_SCOPE = "mcp"
NOTES_READ = "notes:read"
NOTES_WRITE = "notes:write"


class ToolScopes:
    """The scope each registered tool needs.

    Tools record their scope as they register, so the protected resource metadata, the HTTP
    scope challenge, and `whoami` all read this one map.
    """

    def __init__(self) -> None:
        self._by_tool: dict[str, str] = {}

    def require[F: Callable[..., object]](self, scope: str) -> Callable[[F], F]:
        """Records that the decorated tool needs `scope`. Put it below `@server.tool()`."""

        def record(tool: F) -> F:
            self._by_tool[getattr(tool, "__name__", "")] = scope
            return tool

        return record

    def for_tool(self, name: str) -> str | None:
        return self._by_tool.get(name)

    @property
    def supported(self) -> list[str]:
        return sorted(set(self._by_tool.values()))


def require_scope(scope: str, action: str) -> None:
    """Raises `ToolError` unless the caller's token has `scope`.

    Over HTTP, the scope challenge rejects the request first. Without a token, over stdio or
    with no auth, the caller has every scope.
    """
    token = get_access_token()
    if token is not None and scope not in token.scopes:
        raise ToolError(
            f"This token lacks the {scope} scope. Reconnect with that scope to {action}."
        )
