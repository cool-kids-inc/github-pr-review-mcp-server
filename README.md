# GitHub PR Review Spec Generator (MCP Server)

![Demo](docs/demo.gif)

[![Install MCP Server](https://cursor.com/deeplink/mcp-install-dark.svg)](https://cursor.com/en/install-mcp?name=pr-review-spec&config=eyJjb21tYW5kIjoidXYiLCJhcmdzIjpbInJ1biIsInB5dGhvbiIsIm1jcF9zZXJ2ZXIucHkiXX0%3D) [<img alt="Install in VS Code (uv)" src="https://img.shields.io/badge/Install%20in%20VS%20Code-0098FF?style=for-the-badge&logo=visualstudiocode&logoColor=white">](https://insiders.vscode.dev/redirect?url=vscode%3Amcp%2Finstall%3F%7B%22name%22%3A%22pr-review-spec%22%2C%22command%22%3A%22uv%22%2C%22args%22%3A%5B%22run%22%2C%22python%22%2C%22mcp_server.py%22%5D%7D)

This is a Model Context Protocol (MCP) server that allows a large language model (LLM) like Claude to fetch review comments from a GitHub pull request and generate markdown specifications.

> **⚠️ Security Notice**: Please read [SECURITY.md](SECURITY.md) for important security considerations, especially regarding agentic workflows and automated implementation of PR comments.

## Prerequisites

- Python 3.9 or higher
- [uv](https://docs.astral.sh/uv/) - modern Python package manager (recommended)

## Setup

### Option 1: Using UV (Recommended)

1. **Install UV (if not already installed):**
   ```bash
   # On macOS and Linux
   curl -LsSf https://astral.sh/uv/install.sh | sh

   # On Windows
   powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

   # Or with pip
   pip install uv
   ```

2. **Clone the repository:**
   ```bash
   git clone <repository_url>
   cd <repository_directory>
   ```

3. **Install dependencies:**
   ```bash
   # Install production dependencies
   uv pip install -e .

   # Install development dependencies
   uv pip install -e ".[dev]"

   # Or install all dependencies in one command
   uv sync --all-extras
   ```

4. **Set up environment variables:**
   - Create a `.env` file and add your GitHub personal access token:
     ```bash
     echo "GITHUB_TOKEN=your_github_token_here" > .env
     ```

### Option 2: Using Traditional pip (Legacy)

1. **Clone the repository:**
   ```bash
   git clone <repository_url>
   cd <repository_directory>
   ```

2. **Create and activate virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables:**
   - Create a `.env` file and add your GitHub personal access token:
     ```bash
     echo "GITHUB_TOKEN=your_github_token_here" > .env
     ```

## Enterprise GitHub Support

This MCP server supports both GitHub.com and GitHub Enterprise Server (GHES).

### Configuration

**For GitHub.com (default):**
```bash
GITHUB_TOKEN=ghp_your_token_here
```

**For GitHub Enterprise Server:**
```bash
GH_HOST=github.enterprise.com
GITHUB_TOKEN=your_enterprise_token
```

The server automatically constructs API endpoints based on `GH_HOST`:

```text
REST API:    https://{GH_HOST}/api/v3
GraphQL API: https://{GH_HOST}/api/graphql
```

### Advanced: Custom API URLs

For non-standard enterprise configurations:
```bash
GITHUB_API_URL=https://custom.github.company.com/api
GITHUB_GRAPHQL_URL=https://custom.github.company.com/graphql
```

### URL Format

The server accepts PR URLs in this format:
```text
https://{host}/owner/repo/pull/123
```

Examples:
- `https://github.com/owner/repo/pull/123` (GitHub.com)
- `https://github.enterprise.com/owner/repo/pull/456` (GHES)

## Development Workflow

### Code Quality and Formatting

This project uses [Ruff](https://docs.astral.sh/ruff/) for linting and formatting. All configurations are defined in `pyproject.toml`.

```bash
# Install development dependencies (if not already installed)
uv pip install -e ".[dev]"

# Run linting
ruff check .

# Run linting with auto-fix
ruff check . --fix

# Format code
ruff format .

# Run both linting and formatting
ruff check . --fix && ruff format .
```

### Testing

Run tests using pytest:

```bash
# Run all tests
pytest

# Run tests with verbose output
pytest -v

# Run specific test file
pytest test_mcp_server.py

# Run tests with coverage (install pytest-cov first)
pytest --cov=. --cov-report=html
```

### Pre-commit

This project uses [pre-commit](https://pre-commit.com/) to run formatting, linting, and tests on staged files.

```bash
# Install the git hook scripts
uv run --extra dev pre-commit install

# Run all checks on every file
uv run --extra dev pre-commit run --all-files
```

## Running the MCP Server

To start the MCP server, run the following command in your terminal:

```bash
# Using the installed script (after pip install -e .)
mcp-github-pr-review-spec-maker

# Or run directly
python mcp_server.py

# With UV
uv run python mcp_server.py

# Or use the helper script (uv-first)
./run-server.sh                 # starts via `uv run`
./run-server.sh --sync          # sync deps first
./run-server.sh --log           # also write logs/logs/mcp_server.log
./run-server.sh --register      # register with Claude CLI as `pr-review-spec`
./run-server.sh --codex         # configure Codex CLI to use this server
```

## Install / Configure in Editors & CLIs

### Option A: Quick setup via `run-server.sh`

- Interactive config/show config only:
  ```bash
  ./run-server.sh --config     # print instructions for all clients (no changes)
  ```
- One-shot configure common clients (non-interactive):
  ```bash
  ./run-server.sh --register --codex --gemini
  # add --desktop to also configure Claude Desktop
  ```

### Option B: Manual setup

Run these from the repo root so `$(pwd)` points to this project.

#### Claude Code (CLI)

```bash
# Minimal (pass env vars if needed)
claude mcp add pr-review-spec -s user -- \
  uv run --project "$(pwd)" -- python mcp_server.py

# Example with env var (GitHub token)
claude mcp add pr-review-spec -s user -e GITHUB_TOKEN="$GITHUB_TOKEN" -- \
  uv run --project "$(pwd)" -- python mcp_server.py
```

#### Codex CLI

Append to `~/.codex/config.toml`:

```toml
[mcp_servers.pr-review-spec]
command = "uv"
args = ["run", "python", "mcp_server.py"]

[mcp_servers.pr-review-spec.env]
# Optional – provide your token here, or rely on your shell environment
# GITHUB_TOKEN = "your_github_token_here"
PATH = "/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$HOME/bin"
```

> Tip: `./run-server.sh --codex` can write this for you.

#### Gemini CLI

Edit `~/.gemini/settings.json` and add:

```json
{
  "mcpServers": {
    "pr-review-spec": {
      "command": "uv",
      "args": ["run", "python", "mcp_server.py"]
    }
  }
}
```

> Tip: `./run-server.sh --gemini` can write this for you.

The server listens over `stdio` and becomes available to connected MCP clients.

## Available Tools

The server exposes the following tools to the LLM:

### 1. `fetch_pr_review_comments`

Fetches all review comments from a given GitHub pull request URL. The tool returns Markdown by default (optimized for human/AI readability), with options to request JSON or both.

-   **Parameters:**
    -   `pr_url` (str): The full URL of the pull request (e.g., `"https://github.com/owner/repo/pull/123"`). If omitted, the server will attempt to auto-resolve from the current repo/branch.
    -   `output` (str, optional): Output format. One of `"markdown"` (default), `"json"`, or `"both"`.
        - `markdown`: returns a single Markdown document rendered from the comments (default).
        - `json`: returns a single JSON string with the raw comments list.
        - `both`: returns two messages: first JSON, then Markdown.
    -   `per_page` (int, optional): GitHub page size (1–100). Defaults from env `HTTP_PER_PAGE`.
    -   `max_pages` (int, optional): Safety cap on pages. Defaults from env `PR_FETCH_MAX_PAGES`.
    -   `max_comments` (int, optional): Safety cap on total comments. Defaults from env `PR_FETCH_MAX_COMMENTS`.
    -   `max_retries` (int, optional): Retry budget for transient errors. Defaults from env `HTTP_MAX_RETRIES`.

-   **Returns:**
    -   When `output="markdown"` (default): a single text item containing Markdown.
    -   When `output="json"`: a single text item containing a JSON string with the raw comments list.
    -   When `output="both"`: two text items in order — first JSON, then Markdown.

Example (Markdown default):
```json
{
  "name": "fetch_pr_review_comments",
  "arguments": { "pr_url": "https://github.com/owner/repo/pull/123" }
}
```

Example (JSON output):
```json
{
  "name": "fetch_pr_review_comments",
  "arguments": { "pr_url": "https://github.com/owner/repo/pull/123", "output": "json" }
}
```

### 2. `resolve_open_pr_url(select_strategy?: str, owner?: str, repo?: str, branch?: str) -> str`

Resolves the open PR URL for the current branch using git detection.

-   **Parameters:**
    -   `select_strategy` (str, optional): Strategy when auto-resolving a PR (default 'branch'). Options: 'branch', 'latest', 'first', 'error'.
    -   `owner` (str, optional): Override repo owner for PR resolution.
    -   `repo` (str, optional): Override repo name for PR resolution.
    -   `branch` (str, optional): Override branch name for PR resolution.
-   **Returns:**
    -   The resolved PR URL as a string.

### GitHub Token Scopes

Use least privilege for `GITHUB_TOKEN`:

- Classic PATs:
  - Public repositories: `public_repo` is sufficient.
  - Private repositories: `repo` is required.
- Fine-grained PATs:
  - Repository access: Select the target repo(s).
  - Permissions: Pull requests → Read access (enables reading review comments at `GET /repos/{owner}/{repo}/pulls/{pull_number}/comments`).

Avoid granting write or admin scopes unless needed for other tools.

## Warning: Production Deployment

Do not run this application in production using a development server or with debug enabled. If exposing HTTP endpoints, use a production-grade WSGI/ASGI server (e.g., Gunicorn, Uvicorn) and ensure debug is disabled.

## Environment Variables

These variables can be set in `.env` (loaded via `python-dotenv`) or your environment:

- `GITHUB_TOKEN`: GitHub PAT used for API calls. Fine-grained tokens use `Bearer` scheme; classic PATs are automatically retried with `token` scheme on 401.
- `PR_FETCH_MAX_PAGES` (default `50`): Safety cap on pagination pages when fetching comments.
- `PR_FETCH_MAX_COMMENTS` (default `2000`): Safety cap on total collected comments before stopping early.
- `HTTP_PER_PAGE` (default `100`): GitHub API `per_page` value (1–100).
- `HTTP_MAX_RETRIES` (default `3`): Max retries for transient request errors and 5xx responses, with backoff + jitter.

For GitHub Enterprise instances, override the API endpoints in your `.env`:

```bash
GITHUB_API_URL=https://custom.github.company.com/api/v3
GITHUB_GRAPHQL_URL=https://custom.github.company.com/api/graphql
```

## Project Structure and Tooling

### Modern Python Tooling

This project uses modern Python tooling for enhanced developer experience:

- **[uv](https://docs.astral.sh/uv/)**: Ultra-fast Python package manager and resolver
- **[Ruff](https://docs.astral.sh/ruff/)**: Extremely fast Python linter and formatter
- **[pyproject.toml](./pyproject.toml)**: Modern Python project configuration file
- **[pytest](https://pytest.org/)**: Modern testing framework with async support

### Benefits of Modern Tooling

- **Speed**: UV is 10-100x faster than pip for dependency resolution
- **Reliability**: Better dependency resolution and lock file generation
- **Code Quality**: Ruff provides comprehensive linting and formatting in milliseconds
- **Developer Experience**: Better IDE integration and faster feedback loops
- **Consistency**: Standardized configuration in pyproject.toml

### Legacy Support

For compatibility, the original `requirements.txt` file is maintained, but the modern workflow using `pyproject.toml` and UV is recommended for development.

### Migration from Legacy Setup

If you're migrating from the old pip-based setup:

```bash
# Remove old virtual environment
rm -rf venv

# Install UV
pip install uv

# Install dependencies with UV
uv pip install -e ".[dev]"

# Format and lint your code
ruff format . && ruff check . --fix

# Run tests to ensure everything works
pytest
```
