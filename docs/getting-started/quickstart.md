# Quickstart

Follow this quickstart to run the MCP server locally with `uv` in under ten minutes.

## Prerequisites

- Python 3.10 or later
- [`uv`](https://docs.astral.sh/uv/) package manager (recommended)
- GitHub personal access token with **read** access to pull requests

## Install and Run

```bash
# Clone the project
uvx git clone https://github.com/cool-kids-inc/github-pr-review-mcp-server.git
cd mcp-github-pr-review

# Install runtime dependencies and the editable package
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
