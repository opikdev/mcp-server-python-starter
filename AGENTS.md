# Agent guide

A production-ready MCP server in Python, built on the official MCP Python SDK v2 and its `MCPServer` API. It serves stdio for local clients and Streamable HTTP with OAuth for remote ones. `get_time`, `search_docs`, `whoami`, the `docs://` resources, and `list_notes` and `create_note`, which appear when `UPSTREAM_API_URL` is set, are samples to copy or replace.

| Path | Purpose |
|---|---|
| [docs/architecture.md](docs/architecture.md) | How requests flow, and where tools live |
| [docs/auth.md](docs/auth.md) | HTTP auth modes and settings |
| [docs/clients.md](docs/clients.md) | How to connect Claude Code, Claude Desktop, Cursor, and VS Code |
| [docs/upstream.md](docs/upstream.md) | How tools call a backend API, the notes API contract, and token exchange |
| [docs/deploy.md](docs/deploy.md) | Proxy, TLS, audience, secrets, readiness, and telemetry in production |
| [docs/publishing.md](docs/publishing.md) | Releasing to PyPI, the MCP Registry, and GHCR |
| [docs/decisions/](docs/decisions/) | Why it's built this way |
| `.agents/skills/` | Step-by-step guides for recurring tasks |
| `.mcp.json` | MCP servers for working on this project |

## Commands

| Task | Command |
|---|---|
| Install dependencies | `make sync` |
| Try the tools in the MCP Inspector | `make inspect` |
| Serve over HTTP on your machine | `cp .env.example .env`, then `make dev` |
| Run all gates | `make verify` |
| Test the built wheel, Docker image, example backend, Inspector, and Keycloak | `make e2e` |
| Fix formatting | `make format` |

## Rules

- Don't commit until `make verify` passes. For changes to packaging, Docker, or entry points, run `make e2e` too. If they can't run, stop and report that instead of committing.
- If the check blocks you, fix the cause. Never edit `.agents/check.sh`, `.githooks/`, or the harness workflow to get past it, and never use `--no-verify`. If the request can't be done without that, stop and ask.
- After cloning, run `git config core.hooksPath .githooks` once to turn on the hook.
- Add each tool in its own module in `src/mcp_app/tools/` with a `register_*` function, call it from `src/mcp_app/server.py`, name it in the server's instructions there, and test it through a real client in `tests/integration/`. A test checks that the instructions name every tool.
- Give every tool typed, described parameters, a one-line docstring, `ToolAnnotations` with all four hints set, and a return type of `Annotated[CallToolResult, Model]`, where `Model` is a Pydantic `BaseModel`. Name every input and output field in snake_case. Raise `ToolError` with a message the model can act on for expected failures.
- Every tool that reads or changes data declares the scope it needs: put `@scopes.require(SCOPE)` under `@server.tool(...)`, and call `require_scope` from `src/mcp_app/auth/scopes.py` first in the tool. The metadata and the `403` challenge read those registrations. See [docs/auth.md](docs/auth.md#per-tool-scopes).
- Call backends through a client in `src/mcp_app/upstream/` with a deadline and a response model. Get credentials from `upstream/credentials.py`, never in a tool, and never forward the caller's token. Turn failures into `UpstreamError` messages, quote backend text with `quote_untrusted`, and never return credentials or raw upstream bodies to the model. When a write that isn't idempotent gets no answer (`NoResponseError`), tell the model the outcome is unknown and how to check, never to retry.
- Never print to stdout, because stdio uses it for protocol messages. Log with `logging`, which writes JSON to stderr. Ruff's `T20` rule flags `print`.
- Keep `server.json` in step with `pyproject.toml`. A test enforces this.
- Add dependencies with `uv add`, and commit `uv.lock` in the same change.
- Don't edit files listed in `.baseline.sha256`. They come from [opikdev/starters](https://github.com/opikdev/starters).
- Keep this file a short map, and put detail in `docs/`.
- Fix any doc your change makes wrong, in the same change.
- Record significant decisions with the `record-decision` skill.
- Back important rules with a lint rule, hook, or CI check.
