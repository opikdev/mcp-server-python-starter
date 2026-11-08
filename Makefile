INSPECTOR := @modelcontextprotocol/inspector@2.14.0
ENV_FILE := $(if $(wildcard .env),--env-file .env)

.PHONY: sync format lint test verify e2e dev inspect

sync:
	uv sync --locked

format:
	uv run ruff format .
	uv run ruff check --fix .

lint:
	uv run ruff format --check .
	uv run ruff check .
	uv run mypy

test:
	uv run pytest --cov

verify: lint test
	.agents/check.sh
	.github/scripts/check-repo-standards.sh

e2e:
	uv run pytest tests/e2e

dev:
	uv run $(ENV_FILE) mcp-server-python-starter --http

inspect:
	npx --yes $(INSPECTOR) uv run $(ENV_FILE) mcp-server-python-starter
