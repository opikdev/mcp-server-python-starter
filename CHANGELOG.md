# Changelog

All notable changes to this repo are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Fixed

- With `MCP_AUTH_MODE=oauth`, an unreachable issuer or unusable metadata now stops the server with a clear message and exit code 2, not a traceback. Metadata that isn't a JSON object falls through to the next discovery URL.

### Changed

- Tool results and notes API responses share one `CamelModel` base, so fields are snake_case in Python and camelCase in JSON, with no per-field aliases.
- Ruff's `T20` rule now flags `print`, which would corrupt stdio messages.

## [0.1.0] - 2026-11-08

### Added

- MCP server on the official Python SDK v2, serving the 2026-07-28 protocol and older clients.
- stdio for local clients, and stateless Streamable HTTP with OAuth, static tokens, and DNS rebinding protection.
- Sample tools with typed schemas and annotations, plus `docs://` resources.
- `list_notes` and `create_note`, which call a REST API with timeouts, response validation, and readable errors. They appear when `UPSTREAM_API_URL` is set.
- Tests through real MCP clients in process, over stdio, and over HTTP, plus end-to-end tests of the wheel, the Docker image, and a real backend.
- Release workflow for GHCR, PyPI, and the MCP Registry, with `server.json`.
- `pik.yaml`, so `pik new mcp-server-python-starter` can create projects from this starter.
