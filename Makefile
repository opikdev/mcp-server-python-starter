INSPECTOR := @modelcontextprotocol/inspector@2.14.0
ENV_FILE := $(if $(wildcard .env),--env-file .env)
# The Inspector starts the server with only a few variables, so forward the upstream settings.
UPSTREAM_SETTINGS := UPSTREAM_API_URL UPSTREAM_API_TOKEN UPSTREAM_TIMEOUT_MS
INSPECT_ENV = $(foreach name,$(UPSTREAM_SETTINGS),$(if $($(name)),-e '$(name)=$($(name))'))

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

# ARGS passes Inspector flags, such as ARGS="--cli --method tools/list".
inspect:
	npx --yes $(INSPECTOR) $(ARGS) $(INSPECT_ENV) uv run $(ENV_FILE) mcp-server-python-starter
