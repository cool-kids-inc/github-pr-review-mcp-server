# Quickstart

Get the server running in minutes using the automated helper script, or fall back to the manual `uv` workflow if you prefer to manage environments yourself.

## Prerequisites

- Python 3.10 or later
- [`uv`](https://docs.astral.sh/uv/) package manager (recommended)
- GitHub personal access token with **read** access to pull requests

## Option A: Clone + `run-server.sh` *(recommended)*

```bash
git clone https://github.com/cool-kids-inc/github-pr-review-mcp-server.git
cd github-pr-review-mcp-server

# Install dependencies and show status
./run-server.sh --sync

# Launch with your environment (reads .env automatically)
./run-server.sh --log
```

- Place your secrets in `.env` (e.g., `GITHUB_TOKEN=ghp_your_token`), or export them before running the script.
- Add `--register --codex --gemini --desktop` to configure common MCP hosts in a single pass.

## Option B: Manual `uv` workflow

```bash
git clone https://github.com/cool-kids-inc/github-pr-review-mcp-server.git
cd github-pr-review-mcp-server

# Install runtime dependencies and editable package
uv sync

# Provide credentials
echo "GITHUB_TOKEN=ghp_your_token" > .env

# Launch the MCP server over stdio
uv run mcp-github-pr-review
```

Once the server is running, connect it from your preferred MCP host (Claude Desktop, Codex CLI, Cursor, etc.). For tailored integration steps, visit [Editor Integrations](../guides/editor-integrations.md).

## Verify a Connection

Use the built-in health command to ensure connectivity:

```bash
claude mcp call pr-review list-tools
```

Expected response includes `fetch_pr_review_comments` and `resolve_open_pr_url`.

## Next Steps

1. Review [Security Requirements](../security/index.md) before enabling automated agents.
2. Configure `PR_FETCH_MAX_*` environment limits if your repositories have high comment volume.
3. Explore [Remote Hosting with `uv`](../guides/remote-uv-endpoint.md) to serve the MCP process over TLS.
