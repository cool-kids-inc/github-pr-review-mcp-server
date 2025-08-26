# Agent Workflow (UV)

This repo is set up to run entirely through `uv` for fast, reproducible dev flows. If you’re automating tasks (e.g., Codex CLI, MCP clients, CI agents), prefer `uv run` over invoking system Python directly.

## Quick Start
- Install `uv` (see https://docs.astral.sh/uv/)
- Sync deps for development: `uv sync --dev`
- Run tests: `uv run pytest`
- Lint: `uv run ruff check .`
- Format: `uv run ruff format .`
- Start server: `uv run python mcp_server.py`

See `UV_COMMANDS.md` for a compact command list.

## Environment
- `GITHUB_TOKEN`: GitHub PAT for API access. The server uses `python-dotenv` to load `.env` automatically. Create `.env` or set the variable in your agent’s environment.
- Network: First-time sync may require network to resolve wheels/sdists according to `uv.lock`.

## Sandbox Notes
- In restricted sandboxes, `uv` may access `~/.cache/uv` and other user dirs. If the environment blocks filesystem access outside the workspace, request elevated permissions for commands like `uv run ...` or `uv sync`.
- Example (Codex CLI): mark the shell step as needing escalation when running `uv run pytest` so it can read/write its cache.

## Server Tools (MCP)
- `fetch_pr_review_comments(pr_url: str)`: Fetch PR review comments.
- `create_review_spec_file(comments: list, filename: str = "spec.md")`: Generate a review spec markdown file.

## Tips
- Use `uv run` consistently; avoid system `python`/`pytest` invocations so agents don’t depend on host Python.
- Run `uv run ruff check --fix . && uv run ruff format .` before tests to keep diffs clean.
