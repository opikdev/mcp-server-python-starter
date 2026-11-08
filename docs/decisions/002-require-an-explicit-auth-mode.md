# 002. Require an explicit auth mode

- **Status**: accepted
- **Context**: An MCP server over HTTP exposes tools to anyone who can reach it. A silent default of no auth is how servers end up open on the internet.
- **Decision**: Refuse to start HTTP until `MCP_AUTH_MODE` is `oauth`, `token`, or `none`, and allow `none` only on a loopback address.
- **Consequences**:
  - `oauth` follows the MCP authorization spec, with protected resource metadata and audience checks.
  - `token` covers internal services without an authorization server.
  - The first HTTP run needs one setting, which `.env.example` and `compose.yaml` provide.
