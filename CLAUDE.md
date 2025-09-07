# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

This project uses `uv` as the primary package manager for fast, reproducible development:

```bash
# Install all dependencies (production + development)
uv sync --dev

# Run linting and auto-fix
uv run ruff check --fix .

# Format code
uv run ruff format .

# Run tests
uv run pytest

# Run tests with verbose output
uv run pytest -v

# Type checking with mypy
uv run mypy .

# Syntax compile check (fail fast on SyntaxError)
make compile-check

# Run the MCP server
uv run python mcp_server.py

# Pre-commit quality check (format, lint, type check, syntax, test)
uv run ruff format . && uv run ruff check --fix . && uv run mypy . && make compile-check && uv run pytest
```

## Architecture Overview

This is a Model Context Protocol (MCP) server that provides tools for fetching GitHub PR review comments and generating markdown specification files.

### Core Components

- **`ReviewSpecGenerator` class**: Main MCP server class that handles tool registration and execution
- **`fetch_pr_comments()` async function**: Core GitHub API integration with pagination, error handling, and retry logic
- **`generate_markdown()` function**: Converts review comments to formatted markdown with dynamic code fencing
- **`get_pr_info()` function**: URL parser for extracting owner/repo/PR number from GitHub URLs

### Key Architecture Patterns

- **Async/await throughout**: All GitHub API calls and file operations are async
- **Robust error handling**: Network timeouts, API errors, and rate limiting are handled gracefully
- **Configuration via environment**: Uses `.env` file loading with sensible defaults
- **Pagination safety**: Built-in limits prevent runaway API calls (max pages/comments)
- **Dynamic markdown fencing**: Automatically adjusts code block fencing to handle nested backticks

### MCP Tools Exposed

1. **`fetch_pr_review_comments`**: Fetches all review comments from a GitHub PR URL with configurable pagination and safety limits
2. **`create_review_spec_file`**: Creates a markdown file from comments with automatic filename generation and collision avoidance

### Environment Configuration

Required: `GITHUB_TOKEN` (GitHub PAT with appropriate repo access)

Optional tuning parameters:
- `PR_FETCH_MAX_PAGES` (default 50): Safety limit on pagination
- `PR_FETCH_MAX_COMMENTS` (default 2000): Safety limit on total comments
- `HTTP_PER_PAGE` (default 100): GitHub API page size
- `HTTP_MAX_RETRIES` (default 3): Retry limit for transient errors

### File Structure

- `mcp_server.py`: Main server implementation (~400 lines)
- `test_mcp_server.py`: Comprehensive test suite with mocking
- `pyproject.toml`: Modern Python project configuration with Ruff linting rules
- `AGENTS.md`: Agent-specific workflow documentation
- `UV_COMMANDS.md`: Quick reference for uv commands

## Testing

Tests use pytest with async support. Mock HTTP responses to avoid GitHub API calls during testing:

```bash
# Run specific test file
uv run pytest test_mcp_server.py

# Run with coverage (if pytest-cov is installed)
uv run pytest --cov=. --cov-report=html
```

## Code Quality

Ruff is configured for comprehensive linting and formatting:
- Line length: 88 characters
- Targets Python 3.10+
- Includes security (bandit), import sorting, and modern Python practices
- Auto-fix enabled for most issues

## Development Workflow

**CRITICAL**: After implementing any feature or fixing bugs, ALWAYS run the full quality check pipeline:

```bash
# Required before pushing any code changes
uv run ruff format . && uv run ruff check --fix . && uv run mypy . && make compile-check && uv run pytest
```

This ensures:
1. Code is properly formatted (ruff format)
2. All linting issues are resolved (ruff check --fix)
3. Type checking passes (mypy)
4. No syntax errors exist (compile-check)
5. All unit tests pass (pytest)

**Never push code without running these commands first.** The pipeline must pass completely before any git push operation.
