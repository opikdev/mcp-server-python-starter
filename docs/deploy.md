# Deploy

Run the Docker image, or `mcp-server-python-starter --http`, behind a reverse proxy that terminates TLS. The server is stateless, so run as many replicas as you need, with no sticky sessions or shared store.

## Put a proxy in front

The proxy terminates TLS, rate limits, and passes requests through without buffering, because responses can be Server-Sent Events streams. An nginx example:

```nginx
limit_req_zone $binary_remote_addr zone=mcp:10m rate=10r/s;

upstream mcp {
  server 10.0.0.11:3000;
  server 10.0.0.12:3000;
}

server {
  listen 443 ssl;
  http2 on;
  server_name mcp.example.com;
  ssl_certificate     /etc/ssl/mcp.example.com.pem;
  ssl_certificate_key /etc/ssl/mcp.example.com.key;

  location / {
    limit_req zone=mcp burst=20 nodelay;
    limit_req_status 429;

    proxy_pass http://mcp;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header X-Forwarded-Host $host;
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 1h;
  }
}
```

- **Rate limits** belong in the proxy, so they hold across replicas without a shared store. Tune `rate` and `burst` to your traffic. See [ADR 007](decisions/007-rate-limit-at-the-proxy.md).
- **SSE** needs `proxy_buffering off` and a long `proxy_read_timeout`, or streams stall or drop.
- **`Host`** must reach the server unchanged, because it checks it against `MCP_ALLOWED_HOSTS`. Otherwise requests fail with `421`.
- **`X-Forwarded-*`** headers only reach logs: Uvicorn reads them from the addresses in `FORWARDED_ALLOW_IPS`, so set it to your proxy's address, such as `10.0.0.5`. The server builds every URL it publishes from `MCP_PUBLIC_URL`, never from these headers.
- **`HOST=0.0.0.0`**, the image default, lets the proxy reach the server. Don't publish the port anywhere else.

## Match the token audience

`MCP_PUBLIC_URL` is the URL clients use, as the proxy serves it, such as `https://mcp.example.com/mcp`. It's also the audience every access token must carry ([RFC 8707](https://www.rfc-editor.org/rfc/rfc8707)), and the `resource` in the protected resource metadata. With OAuth, it and `MCP_AUTH_ISSUER` must use `https://`, except on a loopback host. Set up your authorization server so `aud` equals it exactly:

| Provider | How |
|---|---|
| Keycloak | Add an audience mapper with `MCP_PUBLIC_URL` as the custom audience to a client scope every MCP client gets, as `keycloak/mcp-realm.json` does for `mcp`. Use the realm URL, such as `https://id.example.com/realms/mcp`, as `MCP_AUTH_ISSUER` |
| Auth0 | Create an API whose identifier is `MCP_PUBLIC_URL`, and add the scopes as its permissions. `MCP_AUTH_ISSUER` is your tenant URL, such as `https://example.us.auth0.com/` |
| Microsoft Entra ID | Under **Expose an API**, set the application ID URI to `MCP_PUBLIC_URL`, and add the scopes. Entra puts them in the `scp` claim, which the server reads. Use the issuer of the token version your app issues, and check `aud` in a real token before going live |

Scope names must match the ones the server expects: `mcp`, `notes:read`, and `notes:write`, or your own `MCP_AUTH_SCOPES` and tool scopes.

## Keep secrets in a secret manager

Pass `MCP_AUTH_TOKENS`, `UPSTREAM_API_TOKEN`, and `TOKEN_EXCHANGE_CLIENT_SECRET` from your platform's secret manager, never from the image or a committed file.

- **`MCP_AUTH_TOKENS`:** add the new token to the list, move clients over, then remove the old one.
- **`UPSTREAM_API_TOKEN`:** the server sends one token. Have the upstream accept the new token alongside the old one, roll out replicas with the new value, then revoke the old one.
- **`TOKEN_EXCHANGE_CLIENT_SECRET`:** create a second secret at your authorization server if it supports two, roll out, then delete the old one. Otherwise rotate during a quiet window, because exchanges fail between the change and the rollout.

## Readiness and shutdown

| Endpoint | Use it for |
|---|---|
| `/healthz` | Liveness, and the image's `HEALTHCHECK`. Always `200` while the process runs |
| `/readyz` | Readiness. `503` while starting and while draining. It doesn't call the upstream |

On `SIGTERM`, the server fails `/readyz`, keeps serving for `SHUTDOWN_DRAIN_SECONDS` (default 5) so the load balancer stops sending traffic, then stops accepting connections and gives requests in flight up to `SHUTDOWN_TIMEOUT_SECONDS` (default 30). Give the platform's grace period more than the sum, such as `terminationGracePeriodSeconds: 45` on Kubernetes or `stop_grace_period: 45s` in Compose.

## Telemetry

Set `OTEL_EXPORTER_OTLP_ENDPOINT` to export OpenTelemetry traces and metrics over OTLP/HTTP. Without it, nothing is exported and no spans are recorded. The standard `OTEL_*` variables apply, such as `OTEL_EXPORTER_OTLP_HEADERS` for collector credentials.

| Signal | What you get |
|---|---|
| Traces | A span per HTTP request, except probes, and the SDK's `tools/call <tool>` span per tool call. Upstream calls send `traceparent` |
| Metrics | `http.server.duration`, for request count and latency, and `mcp.server.operation.duration`, for call count and latency by `mcp.method.name`, `gen_ai.tool.name`, and `error.type` |
| Logs | JSON on stderr. Lines written inside a span carry `trace_id` and `span_id` |

## Publish

Releases go to PyPI, GHCR, and the MCP Registry. See [Publish a release](publishing.md). Once the server is hosted at a public URL, add it to `server.json` as a remote, so registry users can connect without running it:

```json
"remotes": [{ "type": "streamable-http", "url": "https://mcp.example.com/mcp" }]
```

Then update the `remotes` test in `tests/unit/test_publishing.py`.
