# UV Commands Summary

## Development Commands
```bash
# Install all dependencies (production + development)
uv sync --dev

# Run linting
uv run ruff check .

# Run linting with auto-fix  
uv run ruff check --fix .

# Format code
uv run ruff format .

# Run tests
uv run pytest

# Run tests with verbose output
uv run pytest -v

# Run the MCP server
uv run mcp-github-pr-review
```

## Quick Quality Check
```bash
# Format, lint, and test in one command
uv run ruff format . && uv run ruff check --fix . && uv run pytest
```

