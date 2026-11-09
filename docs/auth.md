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

1. Publishes protected resource metadata at `/.well-known/oauth-protected-resource/mcp`, so clients can find your authorization server.
2. Answers unauthenticated requests with `401` and a `WWW-Authenticate` header pointing to that metadata.
3. Accepts only signed JWT access tokens from your issuer, for `MCP_PUBLIC_URL` as the audience, with every scope in `MCP_AUTH_SCOPES`, and an expiry.
4. Checks the scope each tool that changes data needs. See [Per-tool scopes](#per-tool-scopes).

It finds the signing keys through your issuer's metadata. Set `MCP_AUTH_JWKS_URL` if your issuer doesn't publish it.

## Per-tool scopes

Every token needs the scopes in `MCP_AUTH_SCOPES`. Tools that change data need one more:

| Tool | Scope |
|---|---|
| `create_note` | `notes:write` |

- **`oauth`:** the token's `scope` or `scp` claim must include it. Otherwise the tool returns an error the model can read, and does nothing. While the notes tools are on, the metadata's `scopes_supported` lists `notes:write`, so clients ask for it. Define that scope in your authorization server.
- **`token`, `none`, and stdio:** the caller has every scope.

## Use static tokens

```sh
MCP_AUTH_MODE=token
MCP_AUTH_TOKENS=<A_LONG_RANDOM_TOKEN>
```

Generate a token with `openssl rand -hex 32`. Each one must be at least 16 characters. Clients send it as `Authorization: Bearer <token>`.

## Run behind a proxy

- **Rate limits:** the HTTP transport has none. In production, put it behind a gateway or reverse proxy that limits requests per client or token.
- **Host check:** the proxy must pass the original `Host` header, or you must add the host it sends to `MCP_ALLOWED_HOSTS`. Otherwise requests fail with `421`.
- **Client addresses:** Uvicorn reads `X-Forwarded-For` and `X-Forwarded-Proto` only from the addresses in `FORWARDED_ALLOW_IPS`. Set it to your proxy's address, such as `FORWARDED_ALLOW_IPS=10.0.0.5`, so logs show real client addresses. Use `*` only if nothing but the proxy can reach the server.

Auth doesn't depend on these headers: the audience and metadata URLs come from `MCP_PUBLIC_URL`.

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
