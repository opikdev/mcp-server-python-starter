# Changelog

All notable changes to this repo are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- The README explains how to start a project with `pik new` or GitHub's **Use this template**. `pik new` removes that section from the project it creates.

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
