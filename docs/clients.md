# Connect a client

Once the package is on PyPI, clients run it with [uvx](https://docs.astral.sh/uv/guides/tools/), which installs it in an isolated environment.

## Claude Code

```sh
claude mcp add mcp-server-python-starter -- uvx mcp-server-python-starter
```

For a server you run over HTTP:

```sh
claude mcp add --transport http mcp-server-python-starter http://localhost:3000/mcp \
  --header "Authorization: Bearer <YOUR_TOKEN>"
```

## Claude Desktop, Cursor, and VS Code

Add this to the client's MCP config file:

```json
{
  "mcpServers": {
    "mcp-server-python-starter": {
      "command": "uvx",
      "args": ["mcp-server-python-starter"]
    }
  }
}
```

While developing, point the client at your working copy instead:

```json
{
  "command": "uv",
  "args": ["run", "--directory", "/ABSOLUTE/PATH/TO/REPO", "mcp-server-python-starter"]
}
```

## MCP Inspector

Run `make inspect` to open the Inspector against your working copy. List the tools, call them, and read the `docs://` resources.
