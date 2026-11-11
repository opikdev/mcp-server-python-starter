# MCP server Python starter

A production-ready Model Context Protocol server in Python, ready to customize with coding agents. It runs over stdio for local clients and Streamable HTTP for remote ones, with OAuth, sample tools that include calls to a backend API, tests through real MCP clients, and a release pipeline.

[![CI](https://github.com/opikdev/mcp-server-python-starter/actions/workflows/ci.yml/badge.svg)](https://github.com/opikdev/mcp-server-python-starter/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

<!-- mcp-name: io.github.opikdev/mcp-server-python-starter -->

## Features

- **Current protocol:** built on the official MCP Python SDK v2 and its `MCPServer` API, for the 2026-07-28 spec, while still serving older clients.
- **Two transports:** stdio for Claude Code, Claude Desktop, and Cursor, plus stateless Streamable HTTP that scales horizontally.
- **Secure HTTP:** OAuth per the MCP authorization spec, or static tokens. It won't start without an auth mode, and it blocks DNS rebinding.
- **Typed tools:** `get_time`, `search_docs`, and `whoami` use type hints and Pydantic models as their schemas, with annotations and readable errors, plus `docs://` resources.
- **Backend integration:** `list_notes` and `create_note` call any REST API that meets a documented notes contract, with timeouts, validated responses, and errors the model can act on. See [Connect a backend API](docs/upstream.md).
- **Real tests:** tools are tested through real MCP clients in process, over stdio, and over HTTP, on both protocol eras, plus the built wheel and the Docker image.
- **Strict gates:** Ruff, mypy in strict mode, and 90% coverage.
- **Publishing:** releases to PyPI, the MCP Registry, and GHCR, with a test that keeps `server.json` and `pyproject.toml` in step.
- **Agent-ready:** `AGENTS.md`, skills, and checks that run on every commit.

## Quick start

You need [uv](https://docs.astral.sh/uv/), which installs Python 3.15 for you, and Node for the MCP Inspector:

```sh
git clone https://github.com/opikdev/mcp-server-python-starter
cd mcp-server-python-starter
make sync
make inspect
```

The MCP Inspector opens in your browser. Connect, list the tools, and call `get_time`.

To run it over HTTP in Docker instead:

```sh
docker compose up --build --wait mcp
```

The server is now at `http://localhost:3000/mcp`, with the dev token `dev-token-change-me-0123`. To connect Claude Code, Claude Desktop, Cursor, or VS Code, see [Connect a client](docs/clients.md).

## Start your own project

Create a renamed copy with [pik](https://github.com/opikdev/pik). It downloads this starter's latest release, then sets your project name and GitHub owner:

```sh
pik new mcp-server-python-starter my-mcp-server
```

Or select **Use this template** on GitHub. That copy keeps the name `mcp-server-python-starter` and the owner `opikdev`, so follow `pik.yaml` by hand: swap the `replace` text, delete the `exclude` paths, and run the `setup` commands.

## Usage

| Task | Command |
|---|---|
| Try the tools in the MCP Inspector | `make inspect` |
| Serve over HTTP on your machine | `cp .env.example .env`, then `make dev` |
| Run lint, types, tests with coverage, and repo checks | `make verify` |
| Test the built wheel, the Docker image, and an example backend | `make e2e` |
| Fix formatting and lint you can fix automatically | `make format` |

To work in a dev container, open the folder in one: `.devcontainer/` has Python, uv, and jq, so `make verify` runs inside it. `make e2e` needs Docker on the host. Over HTTP, the server needs an auth mode. See [Configure HTTP auth](docs/auth.md).

To add a tool, create a module in `src/mcp_app/tools/` with a `register_*` function, call it from `src/mcp_app/server.py`, and test it in `tests/integration/test_tools.py`. Before you release, read [Publish a release](docs/publishing.md).

## Project structure

| Path | Purpose |
|---|---|
| `src/mcp_app/cli.py` | Entry point: stdio by default, or HTTP with `--http` |
| `src/mcp_app/server.py` | Builds the server with every tool and resource |
| `src/mcp_app/tools/` | One module per tool, or a small related set |
| `src/mcp_app/resources/` | `docs://` resources |
| `src/mcp_app/http.py`, `src/mcp_app/auth/` | The HTTP app, health check, and token verifiers |
| `src/mcp_app/upstream/` | Clients for backend APIs |
| `tests/` | Unit, integration, and end-to-end tests |
| `server.json` | MCP Registry metadata |
| `docs/` | [Architecture](docs/architecture.md), guides, and [decisions](docs/decisions/) |

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request, and follow the [code of conduct](CODE_OF_CONDUCT.md).

## Security

Report vulnerabilities privately, as described in [SECURITY.md](SECURITY.md).

## License

Released under the [MIT License](LICENSE).
