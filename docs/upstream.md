# Connect a backend API

Most MCP servers wrap an existing system. The `list_notes` and `create_note` tools show the pattern by calling a REST notes API. Any API that meets [the contract](#the-notes-api-contract) works, your own included.

## Turn the notes tools on

They appear only when `UPSTREAM_API_URL` is set:

| Variable | Type | Default | Description |
|---|---|---|---|
| `UPSTREAM_API_URL` | URL | None | Base URL of the API. Unset hides the notes tools |
| `UPSTREAM_AUTH` | string | `static` | `static` sends `UPSTREAM_API_TOKEN`. `exchange` swaps each caller's token. See [Act as the user](#act-as-the-user) |
| `UPSTREAM_API_TOKEN` | string | Required with `static` | Sent as `Authorization: Bearer`. Never returned to the model or logged |
| `UPSTREAM_TIMEOUT_MS` | number | `5000` | How long each call may take in total, from connecting to the last byte, in milliseconds |

Point them at your API. `make inspect` passes them on to the server the Inspector starts:

```sh
UPSTREAM_API_URL=https://notes.example.com UPSTREAM_API_TOKEN=$TOKEN make inspect
```

## The notes API contract

The client in `src/mcp_app/upstream/notes_client.py` relies on this, and nothing else. [api-hono-starter](https://github.com/opikdev/api-hono-starter), [api-go-starter](https://github.com/opikdev/api-go-starter), and [api-fastapi-starter](https://github.com/opikdev/api-fastapi-starter) all implement it, but they're only examples.

**Auth:** every request sends `Authorization: Bearer <token>` and `Accept: application/json`. The token is `UPSTREAM_API_TOKEN`, or an exchanged token with `UPSTREAM_AUTH=exchange`. The server never logs in or refreshes a static token, so give it one that lasts. Requests also send `traceparent` while [telemetry](deploy.md#telemetry) is on.

**Endpoints**, relative to `UPSTREAM_API_URL`:

| Call | Sends | Reads on success |
|---|---|---|
| `GET /v1/notes` | Query `limit` (1 to 50) and `cursor` when paging | `200` with `data[]` notes and `meta.nextCursor`, a string or `null` on the last page |
| `POST /v1/notes` | JSON body `{ "title", "body" }`. Title 1 to 200 characters, body up to 10,000 | `2xx` with the created note |

The client also accepts a success with no body, such as `204 No Content`, for calls that return nothing.

A note has string fields `id`, `title`, `body`, and `createdAt`. Other fields are ignored. `cursor` is the `nextCursor` from the previous page, passed back unchanged. `POST` sends no `Idempotency-Key`.

**Errors:** any status outside `2xx` is a failure. Error bodies should be [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457) problem details.

| Response | What the model sees |
|---|---|
| `401` or `403` | The credentials were rejected, so the operator should check `UPSTREAM_API_TOKEN`, or the exchange settings |
| `429` | Retry after `Retry-After` seconds, or 60 if it's missing or not a whole number |
| Other `4xx` | The status, and the problem's `detail` when it's a string, quoted as untrusted data: control characters removed and capped at 500 characters |
| `5xx` | The status, and to try again later |
| A success body that doesn't match | That the response wasn't understood |
| No full answer within `UPSTREAM_TIMEOUT_MS`, or no connection | That the API didn't answer. For `create_note`, that the note may or may not exist |

## Try it with an example API

`compose.upstream.yaml` runs api-hono-starter's released image with Postgres and demo data. It's an optional example backend, so swap it for any API that meets the contract.

```sh
docker compose -f compose.upstream.yaml up --wait api
TOKEN=$(curl -s -X POST localhost:3200/v1/sessions -H 'Content-Type: application/json' \
  -d '{"email":"demo@example.com","password":"demo-password-123"}' | jq -r .token)
UPSTREAM_API_URL=http://localhost:3200 UPSTREAM_API_TOKEN=$TOKEN make inspect
```

Logging in through `POST /v1/sessions` is how the example API issues tokens, not part of the contract. `tests/e2e/test_upstream.py` runs this same `make inspect` path in the Inspector's CLI mode.

## Follow the pattern

`src/mcp_app/upstream/notes_client.py` and `src/mcp_app/tools/notes.py` split the work:

1. **The client** calls the API with a timeout through `httpx2`, validates every response with a Pydantic model, and turns failures into `UpstreamError` messages written for the model, such as "Retry in 30 seconds".
2. **The tool** validates input from its type hints, calls the client, returns structured content, and raises `ToolError` with the `UpstreamError` message, which the model sees as `isError: true`. If a write such as `create_note` gets no answer, the model is told the note may or may not exist and to check with `list_notes`, because a blind retry could create a duplicate. Any other error is a bug, so the model only sees a generic error and the details stay in your logs.
3. **The annotations** tell clients what a call does: `open_world_hint=True` for an external system, and `read_only_hint=False` for writes.

Keep the API token on the server. The model only sees results and error messages, never credentials or raw upstream bodies. A backend's error text can carry anything, including text that reads like instructions, so pass it through `quote_untrusted` from `src/mcp_app/upstream/errors.py`.

## Adapt it

- **Another REST API:** copy the client, change the paths and response models, then copy the tools.
- **GraphQL:** send `POST` with `{ query, variables }`. A `200` can still carry an `errors` array, so treat that as a failure too.
- **A database:** connect with a read-only role, use parameterized queries, set a statement timeout, and cap the rows each tool returns.

Test with a fake upstream, as `tests/fake_notes_api.py` does, and add an end-to-end test against a real system, as `tests/e2e/test_upstream.py` does with the example API.

## Act as the user

By default, the tools call the API as one service account. To act as each user, set `UPSTREAM_AUTH=exchange`: the server swaps the caller's MCP access token for an API token at your authorization server ([RFC 8693](https://www.rfc-editor.org/rfc/rfc8693)). It never forwards the MCP token itself, because its audience is this server, not the API. See [ADR 005](decisions/005-use-token-exchange-for-upstream-identity.md).

| Variable | Type | Default | Description |
|---|---|---|---|
| `UPSTREAM_AUDIENCE` | string | Required with `exchange` | The audience to request, which the API checks |
| `TOKEN_EXCHANGE_URL` | URL | Required with `exchange` | The authorization server's token endpoint. `https://`, except on a loopback host |
| `TOKEN_EXCHANGE_CLIENT_ID` | string | Required with `exchange` | The client this server authenticates as |
| `TOKEN_EXCHANGE_CLIENT_SECRET` | string | Required with `exchange` | Its secret. Never logged |

- It needs `MCP_AUTH_MODE=oauth` and HTTP. The server won't start otherwise.
- Each exchanged token is cached per caller token until 30 seconds before it expires.
- A failed exchange becomes a tool error, and a log line with the client, subject, and reason, never a token.
- Your API must accept the authorization server's tokens. The example notes API accepts only its own session tokens, so keep it on `static`. The API starters will gain an OIDC mode.

Try it with the local Keycloak from [Run Keycloak locally](auth.md#run-keycloak-locally), whose `notes-api` client is the audience:

```sh
MCP_AUTH_MODE=oauth MCP_AUTH_ISSUER=http://localhost:8080/realms/mcp \
UPSTREAM_API_URL=https://notes.example.com UPSTREAM_AUTH=exchange UPSTREAM_AUDIENCE=notes-api \
TOKEN_EXCHANGE_URL=http://localhost:8080/realms/mcp/protocol/openid-connect/token \
TOKEN_EXCHANGE_CLIENT_ID=mcp-server TOKEN_EXCHANGE_CLIENT_SECRET=mcp-server-dev-secret \
make dev
```

`tests/e2e/test_token_exchange.py` runs this flow against Keycloak and a fake API, and checks the API gets the exchanged token, never the caller's.
