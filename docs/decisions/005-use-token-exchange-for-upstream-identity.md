# 005. Use token exchange for upstream identity

- **Status**: accepted
- **Context**: The notes tools call an upstream API. Forwarding the caller's MCP token would be token passthrough, which the MCP authorization spec forbids: its audience is this server, and the upstream couldn't tell who it was really for. One shared service account loses the caller's identity.
- **Decision**: Keep the static `UPSTREAM_API_TOKEN` service account as the default. Add an opt-in `UPSTREAM_AUTH=exchange` that swaps each caller's token for an upstream token at the authorization server ([RFC 8693](https://www.rfc-editor.org/rfc/rfc8693)). One seam, `src/mcp_app/upstream/credentials.py`, picks the credential, so tools never handle one.
- **Consequences**:
  - Trust model: the upstream trusts the authorization server, which decides per user and audience whether this server may act for the caller. This server holds only its exchange client secret.
  - Exchanged tokens are cached per caller token until 30 seconds before they expire, so a busy caller costs one exchange per token lifetime.
  - Exchange needs `MCP_AUTH_MODE=oauth`, an upstream that accepts the authorization server's tokens, and an authorization server that supports token exchange. The example notes API accepts only its own session tokens, so it stays on `static`.
  - The `compose.auth.yaml` Keycloak realm and `tests/e2e/test_token_exchange.py` show and prove the whole flow.
