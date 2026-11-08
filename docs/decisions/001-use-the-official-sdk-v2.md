# 001. Use the official MCP SDK v2

- **Status**: accepted
- **Context**: The 2026-07-28 spec made MCP stateless and removed the `initialize` handshake. The official Python SDK v2 implements it, and its `MCPServer` is the decorator API that FastMCP 1.0 contributed. FastMCP 4 is now a separate implementation with more features and more dependencies.
- **Decision**: Build on `mcp` v2 and `MCPServer`, served by Starlette and uvicorn for HTTP.
- **Consequences**:
  - The server speaks the current protocol, and still serves clients on the older handshake.
  - Stateless HTTP needs no session store, so instances scale horizontally.
  - Auth uses the SDK's own resource server support, so protected resource metadata and bearer challenges follow the spec.
  - FastMCP extras, such as its auth providers and server composition, aren't available without adding it.
