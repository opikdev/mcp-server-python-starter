FROM ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 AS uv

FROM python:3.15-slim-trixie@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928 AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY README.md LICENSE ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

FROM python:3.15-slim-trixie@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928 AS runtime
# Take Debian's security fixes that are newer than the base image. The server never installs
# packages at runtime, so drop pip and the copy ensurepip bundles.
RUN apt-get update \
  && apt-get upgrade --yes \
  && rm -rf /var/lib/apt/lists/* /usr/local/bin/pip* /usr/local/lib/python3.15/site-packages/pip* \
    /usr/local/lib/python3.15/ensurepip \
  && useradd --system --uid 10001 --no-create-home app
LABEL io.modelcontextprotocol.server.name="io.github.opikdev/mcp-server-python-starter"
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 HOST=0.0.0.0 PORT=3000
USER app
EXPOSE 3000
HEALTHCHECK --interval=5s --timeout=3s --start-period=5s --retries=5 \
  CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen(f\"http://127.0.0.1:{os.environ['PORT']}/healthz\", timeout=2)"]
CMD ["mcp-server-python-starter", "--http"]
