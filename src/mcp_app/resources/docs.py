"""Short guides served as `docs://{slug}` resources, and searched by the `search_docs` tool."""

from collections.abc import Callable
from dataclasses import dataclass

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ResourceNotFoundError


@dataclass(frozen=True)
class Doc:
    slug: str
    title: str
    body: str


DOCS = [
    Doc(
        slug="getting-started",
        title="Getting started",
        body=(
            "Run the server over stdio with uvx mcp-server-python-starter, or over HTTP with "
            "--http. Tools live in src/mcp_app/tools, and each one has tests in tests/."
        ),
    ),
    Doc(
        slug="authentication",
        title="Authentication",
        body=(
            "Over HTTP, set MCP_AUTH_MODE to oauth to validate JWT access tokens from your "
            "authorization server, or to token for static bearer tokens. Over stdio, the client "
            "launches the server, so there is no token."
        ),
    ),
    Doc(
        slug="adding-tools",
        title="Adding tools",
        body=(
            "Create a module in src/mcp_app/tools with a register function that adds the tool "
            "with typed parameters, an output model, and annotations, then call it from "
            "src/mcp_app/server.py and write tests in tests/integration."
        ),
    ),
]


def doc_uri(slug: str) -> str:
    return f"docs://{slug}"


def _render(doc: Doc) -> str:
    return f"# {doc.title}\n\n{doc.body}\n"


def _reader(doc: Doc) -> Callable[[], str]:
    return lambda: _render(doc)


def register_docs(server: MCPServer) -> None:
    for doc in DOCS:
        server.resource(
            doc_uri(doc.slug), name=doc.slug, title=doc.title, mime_type="text/markdown"
        )(_reader(doc))

    @server.resource(
        "docs://{slug}",
        name="docs",
        title="Documentation",
        description="Short guides about this server.",
        mime_type="text/markdown",
    )
    def read_doc(slug: str) -> str:
        doc = next((candidate for candidate in DOCS if candidate.slug == slug), None)
        if doc is None:
            raise ResourceNotFoundError(
                f"No doc at {doc_uri(slug)}. List resources to see the available docs."
            )
        return _render(doc)
