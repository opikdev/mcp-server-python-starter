"""`get_time`: the current time in an IANA time zone."""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import BaseModel, Field


class Time(BaseModel):
    iso: str = Field(description="The time in UTC, in ISO 8601.")
    timezone: str
    local: str = Field(description="The local date and time, for people to read.")


def register_time_tool(server: MCPServer, now: Callable[[], datetime]) -> None:
    @server.tool(
        title="Get the current time",
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    def get_time(
        timezone: Annotated[
            str, Field(description="IANA time zone name. Defaults to UTC.")
        ] = "UTC",
    ) -> Annotated[CallToolResult, Time]:
        """Returns the current date and time in an IANA time zone, such as Europe/Berlin."""
        try:
            zone = ZoneInfo(timezone)
        except ZoneInfoNotFoundError, ValueError:
            raise ToolError(
                f'Unknown time zone "{timezone}". Use an IANA name, such as Europe/Berlin.'
            ) from None
        current = now()
        here = current.astimezone(zone)
        local = f"{here:%A, %B} {here.day}, {here:%Y at %H:%M:%S %Z}"
        result = Time(
            iso=current.isoformat().replace("+00:00", "Z"), timezone=timezone, local=local
        )
        return CallToolResult(
            content=[TextContent(type="text", text=f"{local} ({timezone})")],
            structured_content=result.model_dump(),
        )
