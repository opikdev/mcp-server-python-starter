"""Per-tool scopes: tools that change data call `require_scope` before they act."""

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.mcpserver.exceptions import ToolError

NOTES_WRITE = "notes:write"
TOOL_SCOPES = [NOTES_WRITE]


def require_scope(scope: str, action: str) -> None:
    """Raises `ToolError` unless the caller's token has `scope`.

    Without a token, over stdio or with no auth, the caller has every scope.
    """
    token = get_access_token()
    if token is not None and scope not in token.scopes:
        raise ToolError(
            f"This token lacks the {scope} scope. Reconnect with that scope to {action}."
        )
