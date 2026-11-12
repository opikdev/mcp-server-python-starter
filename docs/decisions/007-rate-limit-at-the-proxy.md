# 007. Rate limit at the proxy

- **Status**: accepted
- **Context**: A public MCP server needs rate limits. The server is stateless and runs as several replicas, so an in-process limiter would count per replica and reset on every deploy, or would need a shared store.
- **Decision**: Rate limit at the reverse proxy or gateway in front of the server, not in the server. `docs/deploy.md` gives an nginx example.
- **Consequences**:
  - Limits apply across replicas and reject floods before they reach Python.
  - The server stays free of a shared store.
  - Operators must configure the proxy. A server exposed without one has no limit.
  - The upstream API still enforces its own limits, and the notes client turns its `429` into a retry hint for the model.
