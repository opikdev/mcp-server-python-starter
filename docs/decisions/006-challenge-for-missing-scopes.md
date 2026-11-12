# 006. Challenge for missing scopes

- **Status**: accepted
- **Context**: Tools need their own scopes, such as `notes:read` and `notes:write`. A tool error for a missing scope tells the model, but not the client, which can't then ask the user for more access. Hand-kept scope lists also drift from the tools.
- **Decision**: Each tool declares its scope as it registers, with `@scopes.require(...)`. Over HTTP, an ASGI layer in `src/mcp_app/auth/challenge.py` reads the tool name of each `tools/call` and answers a call without the scope with `403` and `WWW-Authenticate: Bearer error="insufficient_scope", scope=…, resource_metadata=…`, as the MCP authorization spec describes. `scopes_supported` comes from the same registrations. The SDK's `RequireAuthMiddleware` checks only scopes every request needs, and its challenge omits `scope=`, so the layer is our own.
- **Consequences**:
  - Clients can step up: they read the challenge, reauthorize with the scope, and retry. The upstream is never called without it.
  - A token missing the base scope `mcp` gets the same `403` challenge on every request, before any tool runs.
  - Over stdio, with static tokens, and with `none`, the caller holds every scope, so there's no challenge. `require_scope` stays in each tool as a second check that also covers stdio.
  - Adding `notes:read` for `list_notes` is breaking: OAuth tokens need the new scope.
