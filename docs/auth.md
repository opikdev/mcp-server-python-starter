# Configure HTTP auth

Over stdio, the client starts the server as a local process, so there's no token. Pass any secrets your tools need as environment variables in the client config.

Over HTTP, set `MCP_AUTH_MODE`. The server won't start without it.

| Mode | Use it for | Settings |
|---|---|---|
| `oauth` | Production. Follows the MCP authorization spec | `MCP_AUTH_ISSUER`, optionally `MCP_AUTH_JWKS_URL` |
| `token` | Internal services and local development | `MCP_AUTH_TOKENS`, a comma-separated list |
| `none` | Local experiments only. Refused unless `HOST` is a loopback address | None |

## Use OAuth

Point the server at your authorization server, such as Auth0, Okta, Keycloak, or Entra ID:

```sh
MCP_AUTH_MODE=oauth
MCP_AUTH_ISSUER=https://auth.example.com
MCP_PUBLIC_URL=https://mcp.example.com/mcp
```

The server then:

1. Publishes protected resource metadata at `/.well-known/oauth-protected-resource/mcp`, so clients can find your authorization server. Its `scopes_supported` lists `MCP_AUTH_SCOPES` and the scope of every tool that's on.
2. Answers a request without a token with `401` and `WWW-Authenticate: Bearer scope="mcp", resource_metadata="…"`. It adds `error="invalid_token"` only when a token was sent and rejected ([RFC 6750](https://www.rfc-editor.org/rfc/rfc6750#section-3.1)).
3. Accepts only signed JWT access tokens from your issuer, for `MCP_PUBLIC_URL` as the audience, with every scope in `MCP_AUTH_SCOPES`, and an expiry.
4. Checks the scope each tool needs before it runs. See [Per-tool scopes](#per-tool-scopes).

It finds the signing keys through your issuer's metadata. Set `MCP_AUTH_JWKS_URL` if your issuer doesn't publish it. `MCP_AUTH_ISSUER`, `MCP_AUTH_JWKS_URL`, and `MCP_PUBLIC_URL` must use `https://`, except on a loopback host. For provider setup, see [Match the token audience](deploy.md#match-the-token-audience).

## Per-tool scopes

Every token needs the scopes in `MCP_AUTH_SCOPES`. Tools that read or change data need one more:

| Tool | Scope |
|---|---|
| `list_notes` | `notes:read` |
| `create_note` | `notes:write` |

- **`oauth`:** the token's `scope` or `scp` claim must include it. Otherwise the call gets `403` with `WWW-Authenticate: Bearer error="insufficient_scope", scope="mcp notes:write", resource_metadata="…"`, and the tool doesn't run. The client can ask the user for that scope and retry. See [ADR 006](decisions/006-challenge-for-missing-scopes.md).
- **`token`, `none`, and stdio:** the caller has every scope, so there's no challenge. `whoami` lists them all.

To give a new tool a scope, put `@scopes.require(SCOPE)` under its `@server.tool(...)`, and call `require_scope` first in the tool, as `src/mcp_app/tools/notes.py` does. The metadata and the challenge read the same registrations.

## Run Keycloak locally

`compose.auth.yaml` runs Keycloak with a demo realm: a public `mcp-client` for MCP clients, a confidential `mcp-server` client for token exchange, the `mcp`, `notes:read`, and `notes:write` scopes, and the user `demo` with the password `demo-password-123`. Dev only: its secrets are fixed.

1. Start it:

   ```sh
   docker compose -f compose.auth.yaml up --wait
   ```

2. Serve the MCP server with OAuth:

   ```sh
   MCP_AUTH_MODE=oauth MCP_AUTH_ISSUER=http://localhost:8080/realms/mcp make dev
   ```

3. Get a token for the demo user. The realm allows the password grant for scripts like this one:

   ```sh
   TOKEN=$(curl -s localhost:8080/realms/mcp/protocol/openid-connect/token \
     -d grant_type=password -d client_id=mcp-client -d username=demo \
     -d password=demo-password-123 -d 'scope=mcp notes:read notes:write' | jq -r .access_token)
   ```

4. Connect a client to `http://localhost:3000/mcp` with `Authorization: Bearer $TOKEN`, or let a client that supports OAuth sign in through the browser as `mcp-client`.

Tokens carry `http://localhost:3000/mcp` as their audience. If you serve on another URL, start Keycloak with the same `MCP_PUBLIC_URL`. To try token exchange, see [Act as the user](upstream.md#act-as-the-user).

## Use static tokens

```sh
MCP_AUTH_MODE=token
MCP_AUTH_TOKENS=<A_LONG_RANDOM_TOKEN>
```

Generate a token with `openssl rand -hex 32`. Each one must be at least 16 characters. Clients send it as `Authorization: Bearer <token>`.

## Run behind a proxy

Put a reverse proxy in front for TLS and rate limits. See [Deploy](deploy.md).

## Settings

| Variable | Type | Default | Description |
|---|---|---|---|
| `HOST` | string | `127.0.0.1` | Interface to bind. The Docker image uses `0.0.0.0` |
| `PORT` | number | `3000` | Port to listen on |
| `MCP_PUBLIC_URL` | URL | `http://localhost:<PORT>/mcp` | URL clients use, and the expected OAuth audience |
| `MCP_ALLOWED_HOSTS` | list | Localhost and the `MCP_PUBLIC_URL` host | `Host` headers to accept |
| `MCP_AUTH_MODE` | string | Required | `oauth`, `token`, or `none` |
| `MCP_AUTH_ISSUER` | URL | None | OAuth issuer |
| `MCP_AUTH_JWKS_URL` | URL | Discovered | OAuth signing keys |
| `MCP_AUTH_TOKENS` | list | None | Static tokens |
| `MCP_AUTH_SCOPES` | string | `mcp` | Space-separated scopes every token needs |
| `FORWARDED_ALLOW_IPS` | list | `127.0.0.1,::1` | Proxy addresses whose `X-Forwarded-*` headers Uvicorn trusts |
| `LOG_LEVEL` | string | `info` | `debug`, `info`, `warning`, or `error` |
| `SHUTDOWN_DRAIN_SECONDS` | number | `5` | After `SIGTERM`, how long to fail `/readyz` while still serving |
| `SHUTDOWN_TIMEOUT_SECONDS` | number | `30` | Then, how long requests in flight get to finish |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | URL | None | Turns on OpenTelemetry export. See [Telemetry](deploy.md#telemetry) |
