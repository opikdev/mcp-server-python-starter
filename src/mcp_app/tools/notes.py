"""`list_notes` and `create_note`: tools that call a REST API through `NotesClient`."""

from typing import Annotated

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import BaseModel, Field, StringConstraints

from mcp_app.auth.scopes import NOTES_READ, NOTES_WRITE, ToolScopes, require_scope
from mcp_app.upstream.errors import NoResponseError, UpstreamError
from mcp_app.upstream.notes_client import NotesClient

UNKNOWN_OUTCOME = (
    "The notes API didn't answer in time, so the note may or may not exist. "
    "Call list_notes to check before retrying."
)


class NoteResult(BaseModel):
    id: str
    title: str
    body: str
    created_at: str


class NoteList(BaseModel):
    notes: list[NoteResult]
    next_cursor: str | None


def register_notes_tools(server: MCPServer, notes: NotesClient, scopes: ToolScopes) -> None:
    @server.tool(
        title="List notes",
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=True,
        ),
    )
    @scopes.require(NOTES_READ)
    async def list_notes(
        limit: Annotated[int, Field(ge=1, le=50, description="Notes per page.")] = 10,
        cursor: Annotated[
            str | None, Field(max_length=100, description="next_cursor from a previous result.")
        ] = None,
    ) -> Annotated[CallToolResult, NoteList]:
        """Lists notes from the notes API, newest first. Pass next_cursor to get the next page."""
        require_scope(NOTES_READ, "list notes")
        try:
            page = await notes.list(limit=limit, cursor=cursor)
        except UpstreamError as error:
            raise ToolError(str(error)) from None
        lines = "\n".join(f"- {note.title} ({note.id})" for note in page.data)
        text = f"{len(page.data)} note(s):\n{lines}" if page.data else "No notes."
        result = NoteList(
            notes=[NoteResult(**note.model_dump()) for note in page.data],
            next_cursor=page.meta.next_cursor,
        )
        return CallToolResult(
            content=[TextContent(type="text", text=text)],
            structured_content=result.model_dump(),
        )

    @server.tool(
        title="Create a note",
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=True,
        ),
    )
    @scopes.require(NOTES_WRITE)
    async def create_note(
        title: Annotated[
            str,
            StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
            Field(description="Short title."),
        ],
        body: Annotated[str, Field(max_length=10_000, description="Note text.")] = "",
    ) -> Annotated[CallToolResult, NoteResult]:
        """Creates one note in the notes API per call, so call it once for each note."""
        require_scope(NOTES_WRITE, "create notes")
        try:
            note = await notes.create(title=title, body=body)
        except NoResponseError:
            raise ToolError(UNKNOWN_OUTCOME) from None
        except UpstreamError as error:
            raise ToolError(str(error)) from None
        return CallToolResult(
            content=[TextContent(type="text", text=f'Created "{note.title}" ({note.id}).')],
            structured_content=NoteResult(**note.model_dump()).model_dump(),
        )
