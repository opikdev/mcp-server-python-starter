"""Builds the MCP server with every tool and resource. Both transports share it."""

from collections.abc import Callable
from datetime import UTC, datetime

from mcp.server import MCPServer
from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings

from mcp_app import __version__
from mcp_app.resources.docs import register_docs
from mcp_app.tools.notes import register_notes_tools
from mcp_app.tools.search_docs import register_search_docs_tool
from mcp_app.tools.time import register_time_tool
from mcp_app.tools.whoami import Transport, register_whoami_tool
from mcp_app.upstream.notes_client import NotesClient

INSTRUCTIONS = (
    "Tools for the current time and this server's docs. Read docs:// resources for details."
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def create_server(
    *,
    transport: Transport,
    notes: NotesClient | None = None,
    now: Callable[[], datetime] | None = None,
    token_verifier: TokenVerifier | None = None,
    auth: AuthSettings | None = None,
) -> MCPServer:
    server = MCPServer(
        "mcp-server-python-starter",
        title="MCP server Python starter",
        version=__version__,
        instructions=INSTRUCTIONS,
        token_verifier=token_verifier,
        auth=auth,
    )
    register_time_tool(server, now or _utc_now)
    register_search_docs_tool(server)
    register_whoami_tool(server, transport)
    if notes is not None:
        register_notes_tools(server, notes)
    register_docs(server)
    return server
