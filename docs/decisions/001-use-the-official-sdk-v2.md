# 001. Use the official MCP SDK v2

- **Status**: accepted
- **Context**: The 2026-07-28 spec made MCP stateless and removed the `initialize` handshake. The official Python SDK v2 implements it, and its `MCPServer` is the decorator API that FastMCP 1.0 contributed. FastMCP 4 is a framework built on top of SDK v2: it adds auth providers, server composition, and more dependencies, but the protocol underneath is the same.
- **Decision**: Build on `mcp` v2 and `MCPServer` directly, served by Starlette and uvicorn for HTTP.
- **Consequences**:
  - The server speaks the current protocol, and still serves clients on the older handshake.
  - Stateless HTTP needs no session store, so instances scale horizontally.
  - Bearer auth and protected resource metadata use the SDK's resource server parts. The scope challenge is a small ASGI layer of our own. See [ADR 006](006-challenge-for-missing-scopes.md).
  - Fewer dependencies to audit and keep current. Moving to FastMCP 4 later keeps the same protocol layer, so tools port with little change.
  - FastMCP extras, such as its auth providers and server composition, aren't available without adding it.
