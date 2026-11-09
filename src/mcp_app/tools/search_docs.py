"""`search_docs`: finds the docs that match a query, with links to read each one."""

from typing import Annotated

from mcp.server import MCPServer
from mcp.types import CallToolResult, ContentBlock, ResourceLink, TextContent, ToolAnnotations
from pydantic import Field, StringConstraints

from mcp_app.models import CamelModel
from mcp_app.resources.docs import DOCS, Doc, doc_uri

SNIPPET_LENGTH = 120


class SearchResult(CamelModel):
    slug: str
    title: str
    uri: str
    snippet: str


class SearchResults(CamelModel):
    results: list[SearchResult]


def _score(doc: Doc, terms: list[str]) -> int:
    title, body = doc.title.lower(), doc.body.lower()
    return sum((3 if term in title else 0) + (1 if term in body else 0) for term in terms)


def register_search_docs_tool(server: MCPServer) -> None:
    @server.tool(
        title="Search the docs",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
    )
    def search_docs(
        query: Annotated[
            str,
            StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
            Field(description="Words to search for."),
        ],
        limit: Annotated[int, Field(ge=1, le=10, description="Maximum number of results.")] = 3,
    ) -> Annotated[CallToolResult, SearchResults]:
        """Searches this server's docs and returns the best matches, with links to read each."""
        terms = query.lower().split()
        scored = [(doc, _score(doc, terms)) for doc in DOCS]
        ranked = sorted(
            (match for match in scored if match[1] > 0),
            key=lambda match: (-match[1], match[0].slug),
        )
        results = [
            SearchResult(
                slug=doc.slug,
                title=doc.title,
                uri=doc_uri(doc.slug),
                snippet=doc.body[:SNIPPET_LENGTH],
            )
            for doc, _ in ranked[:limit]
        ]
        summary = (
            f'No docs match "{query}".'
            if not results
            else f'Found {len(results)} doc(s) for "{query}".'
        )
        content: list[ContentBlock] = [TextContent(type="text", text=summary)]
        content.extend(
            ResourceLink(
                type="resource_link",
                uri=result.uri,
                name=result.slug,
                title=result.title,
                mime_type="text/markdown",
            )
            for result in results
        )
        return CallToolResult(
            content=content, structured_content=SearchResults(results=results).model_dump()
        )
