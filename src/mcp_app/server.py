"""Builds the MCP server with every tool and resource. Both transports share it."""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from mcp.server import MCPServer
from mcp.server.context import ServerMiddleware

from mcp_app import __version__
from mcp_app.auth.scopes import ToolScopes
from mcp_app.resources.docs import register_docs
from mcp_app.tools.notes import register_notes_tools
from mcp_app.tools.search_docs import register_search_docs_tool
from mcp_app.tools.time import register_time_tool
from mcp_app.tools.whoami import Transport, register_whoami_tool
from mcp_app.upstream.notes_client import NotesClient

INSTRUCTIONS = (
    "Use get_time for the current time, search_docs to find this server's guides, and whoami "
    "to see how you're connected. Read docs:// resources for details."
)
NOTES_INSTRUCTIONS = " Use list_notes to read notes from the notes API, and create_note to add one."


def _utc_now() -> datetime:
    return datetime.now(UTC)


def create_server(
    *,
    transport: Transport,
    notes: NotesClient | None = None,
    now: Callable[[], datetime] | None = None,
    tool_scopes: ToolScopes | None = None,
    middleware: Sequence[ServerMiddleware[Any]] = (),
) -> MCPServer:
    """Builds the server. Pass `tool_scopes` to read the scope each registered tool needs."""
    scopes = tool_scopes or ToolScopes()
    server = MCPServer(
        "mcp-server-python-starter",
        title="MCP server Python starter",
        version=__version__,
        instructions=INSTRUCTIONS + (NOTES_INSTRUCTIONS if notes is not None else ""),
        middleware=middleware,
    )
    register_time_tool(server, now or _utc_now)
    register_search_docs_tool(server)
    register_whoami_tool(server, transport, scopes)
    if notes is not None:
        register_notes_tools(server, notes, scopes)
    register_docs(server)
    return server
