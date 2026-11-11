# Connect a backend API

Most MCP servers wrap an existing system. The `list_notes` and `create_note` tools show the pattern by calling a REST notes API. Any API that meets [the contract](#the-notes-api-contract) works, your own included.

## Turn the notes tools on

They appear only when `UPSTREAM_API_URL` is set:

| Variable | Type | Default | Description |
|---|---|---|---|
| `UPSTREAM_API_URL` | URL | None | Base URL of the API. Unset hides the notes tools |
| `UPSTREAM_API_TOKEN` | string | Required with the URL | Sent as `Authorization: Bearer`. Never returned to the model or logged |
| `UPSTREAM_TIMEOUT_MS` | number | `5000` | How long to wait for each call, in milliseconds |

Point them at your API:

```sh
UPSTREAM_API_URL=https://notes.example.com UPSTREAM_API_TOKEN=$TOKEN make inspect
```

## The notes API contract

The client in `src/mcp_app/upstream/notes_client.py` relies on this, and nothing else. [api-hono-starter](https://github.com/opikdev/api-hono-starter), [api-go-starter](https://github.com/opikdev/api-go-starter), and [api-fastapi-starter](https://github.com/opikdev/api-fastapi-starter) all implement it, but they're only examples.

**Auth:** every request sends `Authorization: Bearer <UPSTREAM_API_TOKEN>` and `Accept: application/json`. The server never logs in or refreshes the token, so give it one that lasts.

**Endpoints**, relative to `UPSTREAM_API_URL`:

| Call | Sends | Reads on success |
|---|---|---|
| `GET /v1/notes` | Query `limit` (1 to 50) and `cursor` when paging | `200` with `data[]` notes and `meta.nextCursor`, a string or `null` on the last page |
| `POST /v1/notes` | JSON body `{ "title", "body" }`. Title 1 to 200 characters, body up to 10,000 | `2xx` with the created note |

A note has string fields `id`, `title`, `body`, and `createdAt`. Other fields are ignored. `cursor` is the `nextCursor` from the previous page, passed back unchanged. `POST` sends no `Idempotency-Key`.

**Errors:** any status outside `2xx` is a failure. Error bodies should be [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457) problem details.

| Response | What the model sees |
|---|---|
| `401` or `403` | The credentials were rejected, so the operator should check `UPSTREAM_API_TOKEN` |
| `429` | Retry after `Retry-After` seconds, or 60 if it's missing or not a whole number |
| Other `4xx` | The problem's `detail` when it's a string, or else the status |
| `5xx` | The status, and to try again later |
| A success body that doesn't match | That the response wasn't understood |
| No answer within `UPSTREAM_TIMEOUT_MS`, or no connection | That the API didn't answer. For `create_note`, that the note may or may not exist |

## Try it with an example API

`compose.upstream.yaml` runs api-hono-starter's released image with Postgres and demo data. It's an optional example backend, so swap it for any API that meets the contract.

```sh
docker compose -f compose.upstream.yaml up --wait api
TOKEN=$(curl -s -X POST localhost:3200/v1/sessions -H 'Content-Type: application/json' \
  -d '{"email":"demo@example.com","password":"demo-password-123"}' | jq -r .token)
UPSTREAM_API_URL=http://localhost:3200 UPSTREAM_API_TOKEN=$TOKEN make inspect
```

Logging in through `POST /v1/sessions` is how the example API issues tokens, not part of the contract.

## Follow the pattern

`src/mcp_app/upstream/notes_client.py` and `src/mcp_app/tools/notes.py` split the work:

1. **The client** calls the API with a timeout through `httpx2`, validates every response with a Pydantic model, and turns failures into `UpstreamError` messages written for the model, such as "Retry in 30 seconds".
2. **The tool** validates input from its type hints, calls the client, returns structured content, and raises `ToolError` with the `UpstreamError` message, which the model sees as `isError: true`. If a write such as `create_note` gets no answer, the model is told the note may or may not exist and to check with `list_notes`, because a blind retry could create a duplicate. Any other error is a bug, so the model only sees a generic error and the details stay in your logs.
3. **The annotations** tell clients what a call does: `open_world_hint=True` for an external system, and `read_only_hint=False` for writes.

Keep the API token on the server. The model only sees results and error messages, never credentials or raw upstream bodies.

## Adapt it

- **Another REST API:** copy the client, change the paths and response models, then copy the tools.
- **GraphQL:** send `POST` with `{ query, variables }`. A `200` can still carry an `errors` array, so treat that as a failure too.
- **A database:** connect with a read-only role, use parameterized queries, set a statement timeout, and cap the rows each tool returns.

Test with a fake upstream, as `tests/fake_notes_api.py` does, and add an end-to-end test against a real system, as `tests/e2e/test_upstream.py` does with the example API.

## Act as the user

These tools call the API as one service account. To act as each user, exchange the caller's MCP access token for an API token ([RFC 8693](https://www.rfc-editor.org/rfc/rfc8693)) with your authorization server. Don't forward the MCP token itself, because its audience is this server, not the API.
