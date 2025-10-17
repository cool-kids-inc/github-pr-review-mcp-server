# Editor & CLI Integrations

This guide walks through registering the MCP server with popular hosts. These instructions assume the package is installed globally or inside an activated virtual environment.

## Claude Desktop

1. Open **Settings → MCP Servers**.
2. Add a custom server with:
   - **Name**: `pr-review`
   - **Command**: `mcp-github-pr-review`
   - **Environment**: Provide `GITHUB_TOKEN` (do not commit to repo). For GitHub Enterprise, also set `GH_HOST`.
3. Restart Claude Desktop and confirm the server appears as `Connected`.

## Codex CLI

Append the following snippet to `~/.codex/config.toml`:

```toml
[mcp_servers.pr-review]
command = "mcp-github-pr-review"

[mcp_servers.pr-review.env]
GITHUB_TOKEN = "${GITHUB_TOKEN}"
# For GitHub Enterprise:
# GH_HOST = "ghe.example.com"
```

If the package is not on your PATH, point to the full path inside your virtual environment's `bin` directory.

## Cursor

Add an entry to `~/.cursor/mcp.json`:

```json
{
  "name": "pr-review",
  "command": "mcp-github-pr-review",
  "env": {
    "GITHUB_TOKEN": "${GITHUB_TOKEN}"
    // For GitHub Enterprise:
    // "GH_HOST": "ghe.example.com"
  }
}
```

Restart Cursor to pick up changes.

## Gemini CLI

```json
{
  "mcpServers": {
    "pr-review": {
      "command": "mcp-github-pr-review",
      "env": {
        "GITHUB_TOKEN": "${GITHUB_TOKEN}"
        // For GitHub Enterprise:
        // "GH_HOST": "ghe.example.com"
      }
    }
  }
}
```

The server streams results over stdio. Keep the process running in a terminal and reconnect if you update the package.
