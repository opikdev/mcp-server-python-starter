"""`whoami`: how the caller is connected and, over HTTP, which client the token belongs to."""

from typing import Annotated, Literal

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import BaseModel, Field

Transport = Literal["stdio", "http"]


class Caller(BaseModel):
    transport: Transport
    client_id: str | None = Field(alias="clientId")
    scopes: list[str]


def register_whoami_tool(server: MCPServer, transport: Transport) -> None:
    @server.tool(
        title="Who am I",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
    )
    def whoami() -> Annotated[CallToolResult, Caller]:
        """Returns how the caller is connected and, over HTTP, the client and its scopes."""
        token = get_access_token()
        caller = Caller(
            transport=transport,
            clientId=token.client_id if token else None,
            scopes=token.scopes if token else [],
        )
        who = f"client {caller.client_id}" if caller.client_id else "an unauthenticated caller"
        return CallToolResult(
            content=[TextContent(type="text", text=f"Connected over {transport} as {who}.")],
            structured_content=caller.model_dump(by_alias=True),
        )
