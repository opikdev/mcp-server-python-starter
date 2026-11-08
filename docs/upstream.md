# Connect a backend API

Most MCP servers wrap an existing system. The `list_notes` and `create_note` tools show the pattern by calling a REST API: [api-hono-starter](https://github.com/opikdev/api-hono-starter)'s notes endpoints, or any API with the same shape.

## Turn the notes tools on

They appear only when `UPSTREAM_API_URL` is set:

| Variable | Type | Default | Description |
|---|---|---|---|
| `UPSTREAM_API_URL` | URL | None | Base URL of the API. Unset hides the notes tools |
| `UPSTREAM_API_TOKEN` | string | Required with the URL | Sent as `Authorization: Bearer`. Never returned to the model or logged |
| `UPSTREAM_TIMEOUT_MS` | number | `5000` | How long to wait for each call, in milliseconds |

To try it against a real API:

```sh
docker compose -f compose.upstream.yaml up --wait api
TOKEN=$(curl -s -X POST localhost:3200/v1/sessions -H 'Content-Type: application/json' \
  -d '{"email":"demo@example.com","password":"demo-password-123"}' | jq -r .token)
UPSTREAM_API_URL=http://localhost:3200 UPSTREAM_API_TOKEN=$TOKEN make inspect
```

## Follow the pattern

`src/mcp_app/upstream/notes_client.py` and `src/mcp_app/tools/notes.py` split the work:

1. **The client** calls the API with a timeout through `httpx2`, validates every response with a Pydantic model, and turns failures into `UpstreamError` messages written for the model, such as "Retry in 30 seconds".
2. **The tool** validates input from its type hints, calls the client, returns structured content, and raises `ToolError` with the `UpstreamError` message, which the model sees as `isError: true`. Any other error is a bug, so the model only sees a generic error and the details stay in your logs.
3. **The annotations** tell clients what a call does: `open_world_hint=True` for an external system, and `read_only_hint=False` for writes.

Keep the API token on the server. The model only sees results and error messages, never credentials or raw upstream bodies.

## Adapt it

- **Another REST API:** copy the client, change the paths and response models, then copy the tools.
- **GraphQL:** send `POST` with `{ query, variables }`. A `200` can still carry an `errors` array, so treat that as a failure too.
- **A database:** connect with a read-only role, use parameterized queries, set a statement timeout, and cap the rows each tool returns.

Test with a fake upstream, as `tests/fake_notes_api.py` does, and add an end-to-end test against the real system, as `tests/e2e/test_upstream.py` does.

## Act as the user

These tools call the API as one service account. To act as each user, exchange the caller's MCP access token for an API token ([RFC 8693](https://www.rfc-editor.org/rfc/rfc8693)) with your authorization server. Don't forward the MCP token itself, because its audience is this server, not the API.
