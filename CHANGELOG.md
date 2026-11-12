# Changelog

All notable changes to this repo are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Fixed

- `pik new` with a name that contains the starter's name no longer renames the server name twice, so the Docker image label matches `server.json`.

## [0.3.0] - 2026-11-12

### Security

- Over HTTP with OAuth, a tool call without the tool's scope now gets `403` and `WWW-Authenticate: Bearer error="insufficient_scope", scope="…", resource_metadata="…"` before the tool runs, instead of `200` with a tool error. The `401` challenge now names `scope="mcp"`, and adds `error="invalid_token"` only when a token was sent.
- With `MCP_AUTH_MODE=oauth`, `MCP_AUTH_ISSUER`, `MCP_AUTH_JWKS_URL`, and `MCP_PUBLIC_URL` must use `https://`, except on a loopback host.
- A notes API error `detail` reaches the model quoted as untrusted data, without control characters and capped at 500 characters.
- Base images are pinned by digest, and Renovate waits 3 days before taking a release. The runtime image takes Debian's security updates and drops pip.
- The release scans the image with Trivy before pushing it, and publishes an SBOM, provenance, and a GitHub build attestation. CI scans the image too. The SBOM job only reads the repo.

### Added

- The README explains how to start a project with `pik new` or GitHub's **Use this template**. `pik new` removes that section from the project it creates.
- `UPSTREAM_AUTH=exchange` acts as each user: it swaps the caller's OAuth token for a notes API token at `TOKEN_EXCHANGE_URL` (RFC 8693), and caches it until shortly before it expires. `UPSTREAM_AUTH=static`, with `UPSTREAM_API_TOKEN`, stays the default. See ADR 005.
- `compose.auth.yaml` runs a local Keycloak with a demo realm, and `docs/auth.md` walks through OAuth with it. An end-to-end test proves token exchange against it.
- `/readyz` fails while starting and while draining. On `SIGTERM`, the server fails it for `SHUTDOWN_DRAIN_SECONDS` (default 5), then gives requests in flight up to `SHUTDOWN_TIMEOUT_SECONDS` (default 30).
- With `OTEL_EXPORTER_OTLP_ENDPOINT` set, the server exports OpenTelemetry traces and metrics: HTTP and tool call spans, request and tool call duration by tool and error, and `traceparent` on upstream calls. Log lines inside a span carry `trace_id` and `span_id`.
- `docs/deploy.md` covers the proxy, TLS, rate limits, the token audience for Keycloak, Auth0, and Entra ID, secrets, readiness, telemetry, and publishing. ADRs record token exchange, the scope challenge, rate limiting at the proxy, and snake_case tool fields.
- `server.json` lists the GHCR image with its HTTP settings, and both packages list their settings, with secrets marked. The image carries the `io.modelcontextprotocol.server.name` label.

### Changed

- `docs/upstream.md` documents the notes API contract: endpoints, fields, auth, errors, and timeouts. Any API that meets it works. `compose.upstream.yaml` is labeled an optional example backend and runs `api-hono-starter` 0.4.0.
- `compose.upstream.yaml` runs the hardened `api-hono-starter` 0.5.0 on a read-only filesystem. The notes client already relied only on `Retry-After` and the problem `detail`, so its rate-limit headers and error changes need nothing else.
- **Breaking:** `list_notes` needs the `notes:read` scope with `MCP_AUTH_MODE=oauth`. The protected resource metadata lists each tool's scope, taken from the tool registrations.
- **Breaking:** tool results use snake_case, as tool inputs do: `next_cursor`, `created_at`, and `client_id` replace `nextCursor`, `createdAt`, and `clientId`. `CamelModel` is now `ApiModel`, for backend responses only. See ADR 008.
- HTTP responses are Server-Sent Events streams, so progress and log notifications reach HTTP clients.
- `make inspect` passes the `UPSTREAM_*` settings to the server, so the documented quick start shows the notes tools. An end-to-end test runs it. `ARGS` passes Inspector flags.
- ADR 001 now says FastMCP 4 is built on SDK v2.
- Dependencies are on their latest releases.

### Fixed

- Reading an unknown `docs://` resource returns JSON-RPC `-32602` (Invalid Params), not `-32603`.
- `GET /mcp` returns `405` instead of opening an event stream that a stateless server never writes to or closes.
- `UPSTREAM_TIMEOUT_MS` limits each notes API call in total, not each phase of it.
- The notes client accepts a success with no body, such as `204 No Content`.
- Over stdio and with static tokens or no auth, `whoami` reports every scope the caller has, not an empty list.

## [0.2.0] - 2026-11-09

### Added

- **Breaking:** per-tool scopes. With `MCP_AUTH_MODE=oauth`, `create_note` now needs the `notes:write` scope, and the protected resource metadata lists it while the notes tools are on. Static tokens, no auth, and stdio have every scope, so `whoami` now shows `notes:write` for a static token.
- A dev container with Python, uv, and jq, so `make verify` and `.agents/check.sh` run inside it.
- `docs/auth.md` covers running behind a proxy: the HTTP transport has no rate limit, the `Host` check, and `FORWARDED_ALLOW_IPS`.

### Changed

- Every tool sets all four annotation hints explicitly. One contract test checks the title, one-line description, schemas, and hints of every registered tool, including the notes tools.
- Tool results and notes API responses share one `CamelModel` base, so fields are snake_case in Python and camelCase in JSON, with no per-field aliases.
- Ruff's `T20` rule now flags `print`, which would corrupt stdio messages.
- The agent harness is v0.3.0. Its check also fails when the harness workflow or pre-commit hook is missing or no longer runs the check.
- `renovate.json` belongs to the project and extends the shared baseline preset. Generated projects extend only `config:recommended`.

### Fixed

- The release workflow runs lint and tests before it publishes anything, so a failing tag no longer reaches GHCR or PyPI.
- When `create_note` gets no answer from the notes API, it no longer tells the model to try again, which could create a duplicate. It says the note may or may not exist and to check with `list_notes` first.
- The server's instructions to the model now name every tool, including the notes tools when they're on. A test keeps them in step.
- With `MCP_AUTH_MODE=oauth`, an unreachable issuer or unusable metadata now stops the server with a clear message and exit code 2, not a traceback. Metadata that isn't a JSON object falls through to the next discovery URL.

## [0.1.0] - 2026-11-08

### Added

- MCP server on the official Python SDK v2, serving the 2026-07-28 protocol and older clients.
- stdio for local clients, and stateless Streamable HTTP with OAuth, static tokens, and DNS rebinding protection.
- Sample tools with typed schemas and annotations, plus `docs://` resources.
- `list_notes` and `create_note`, which call a REST API with timeouts, response validation, and readable errors. They appear when `UPSTREAM_API_URL` is set.
- Tests through real MCP clients in process, over stdio, and over HTTP, plus end-to-end tests of the wheel, the Docker image, and a real backend.
- Release workflow for GHCR, PyPI, and the MCP Registry, with `server.json`.
- `pik.yaml`, so `pik new mcp-server-python-starter` can create projects from this starter.
