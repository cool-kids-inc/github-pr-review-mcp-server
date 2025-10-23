# Installation

Pick the path that best fits how you work today. Option A is the most common choice for local development and authoring contributions, while Option B keeps everything ephemeral by running straight from Git.

## Option A: Clone and Automatic Setup *(recommended)*

```bash
git clone https://github.com/cool-kids-inc/github-pr-review-mcp-server.git
cd github-pr-review-mcp-server

# First run installs uv dependencies and prints status
./run-server.sh --sync

# Launch immediately (reads .env / shell env for tokens)
./run-server.sh
```

The helper script is modelled after the Zen MCP server workflow and can optionally configure popular clients for you:

```bash
# Configure Claude CLI, Codex CLI, Gemini CLI, and Claude Desktop
./run-server.sh --register --codex --gemini --desktop
```

- Store secrets such as `GITHUB_TOKEN` (and optionally `GH_HOST`) in `.env` or export them before running the script.
- The script keeps logs in `logs/mcp_server.log` when invoked with `--log`. Use `./run-server.sh --help` to see every flag.
- To update later, run `git pull` followed by `./run-server.sh --sync`.

## Option B: Instant Setup with `uvx`

If you prefer not to clone the repository, you can run the published package directly from Git using `uvx`. Add an MCP entry to your preferred client—here is an example for `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "pr-review": {
      "command": "bash",
      "args": [
        "-c",
        "for p in $(which uvx 2>/dev/null) $HOME/.local/bin/uvx /opt/homebrew/bin/uvx /usr/local/bin/uvx uvx; do [ -x \"$p\" ] && exec \"$p\" --from git+https://github.com/cool-kids-inc/github-pr-review-mcp-server.git mcp-github-pr-review; done; echo 'uvx not found' >&2; exit 1"
      ],
      "env": {
        "PATH": "/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin:$HOME/.local/bin",
        "GITHUB_TOKEN": "your-token-here"
      }
    }
  }
}
```

Adjust the `env` block for any other variables you need (`PR_FETCH_MAX_PAGES`, `PR_FETCH_MAX_COMMENTS`, `HTTP_PER_PAGE`, `HTTP_MAX_RETRIES`, `GH_HOST`, etc.). The entry point `mcp-github-pr-review` exposes the same toolset, and `uvx` keeps the environment isolated each time it runs.

For Codex CLI, edit `~/.codex/config.toml`:

```toml
[mcp_servers.pr-review]
command = "bash"
args = ["-c", "for p in $(which uvx 2>/dev/null) $HOME/.local/bin/uvx /opt/homebrew/bin/uvx /usr/local/bin/uvx uvx; do [ -x \"$p\" ] && exec \"$p\" --from git+https://github.com/cool-kids-inc/github-pr-review-mcp-server.git mcp-github-pr-review; done; echo 'uvx not found' >&2; exit 1"]
tool_timeout_sec = 1200  # 20 minutes; keeps upstream providers responsive

[mcp_servers.pr-review.env]
PATH = "/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$HOME/bin"
GITHUB_TOKEN = "your_token_here"
```

## Optional: Add as a Python Dependency

For applications that embed this MCP server, add it to your `pyproject.toml`:

```toml
[project]
dependencies = [
  "mcp-github-pr-review>=0.2.0",
]
```

After installation the CLI `mcp-github-pr-review` is available, which ultimately invokes `python -m mcp_github_pr_review.server`.
