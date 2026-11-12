# Architecture

```mermaid
flowchart LR
  L[Local client] -->|stdio| CLI["cli.py"]
  R[Remote client] -->|Streamable HTTP| H["http.py: host check, bearer auth, scope challenge"]
  CLI --> F["create_server() in server.py"]
  H --> F
  F --> T["tools/*"]
  F --> D["resources/*"]
  T --> U["upstream/*"] --> B[(Backend API)]
  U -.->|exchange mode| A[(Authorization server)]
```

Paths are under `src/mcp_app/`.

| Path | Does |
|---|---|
| `cli.py` | Reads settings, starts stdio by default, or HTTP with `--http` |
| `server.py` | Builds an `MCPServer` with every tool and resource |
| `tools/` | One module per tool: typed parameters, an output model, annotations, and the handler |
| `resources/` | Resources and their data |
| `http.py` | The Starlette app: health, readiness, protected resource metadata, auth, and the MCP endpoint |
| `auth/` | Static token and JWT verifiers, tool scopes, and the `401`/`403` bearer challenge |
| `upstream/` | Clients for backend APIs, with a total deadline and response validation, and `credentials.py`, which picks each call's credential |
| `models.py` | `ApiModel`, the base for backend responses, which reads camelCase JSON |
| `telemetry.py` | OpenTelemetry traces and metrics, on only with `OTEL_EXPORTER_OTLP_ENDPOINT` |
| `config.py`, `log.py` | Settings from the environment, and JSON logs on stderr |

## Key behaviors

- **Both protocol eras:** clients on the stateless 2026-07-28 protocol and clients on the older `initialize` handshake are both served, over stdio and HTTP.
- **Stateless HTTP:** no session state is kept between requests, so it scales horizontally with no session store. `GET /mcp` gets `405`, because a stateless server never writes to a standalone stream.
- **Streamed responses:** HTTP responses are Server-Sent Events, so progress and log notifications reach HTTP clients as they reach stdio clients.
- **Graceful shutdown:** on `SIGTERM`, `/readyz` fails, the server drains, then lets requests in flight finish. See [Readiness and shutdown](deploy.md#readiness-and-shutdown).
- **Safe defaults:** HTTP binds to localhost, checks the `Host` header against DNS rebinding, and won't start until you pick an auth mode.
- **Clean stdout:** logs go to stderr as JSON, so they never corrupt stdio messages.
- **Schemas from types:** each tool's input schema comes from its type hints, and its output schema from the model in `Annotated[CallToolResult, Model]`. Every field is snake_case. See [ADR 008](decisions/008-name-tool-fields-in-snake-case.md).
