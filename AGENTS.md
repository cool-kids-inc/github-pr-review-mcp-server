# Agent Development Guide

This repository contains a **Model Context Protocol (MCP) server** that fetches GitHub PR review comments and generates markdown specifications. The application is built with modern Python tooling and follows strict development practices.

> **⚠️ Critical Security Warning**: Before using this MCP server in any agent workflows, carefully read [SECURITY.md](SECURITY.md). This document contains essential warnings about the risks of automated implementation of PR comments, including potential security vulnerabilities and the need for human oversight.

## Application Overview

**Purpose**: MCP server that provides tools for LLMs to:
- Fetch review comments from GitHub pull requests
- Generate formatted markdown specifications from PR feedback
- Auto-resolve PR URLs from git repository context

**Architecture**: Async Python server using `httpx` for GitHub API calls, `mcp` framework for protocol implementation, and `dulwich` for git operations.

## Development Environment Setup

### Prerequisites
- **Python 3.10+** (enforced by `pyproject.toml`)
- **uv** package manager (see https://docs.astral.sh/uv/)

### Initial Setup
```bash
# Install dependencies
uv sync --dev

# Set up environment variables
echo "GITHUB_TOKEN=your_github_token_here" > .env
```

### Environment Variables
- `GITHUB_TOKEN`: GitHub PAT for API access (required)
- `PR_FETCH_MAX_PAGES`: Safety cap on pagination (default: 50)
- `PR_FETCH_MAX_COMMENTS`: Safety cap on total comments (default: 2000)
- `HTTP_PER_PAGE`: GitHub API page size (default: 100)
- `HTTP_MAX_RETRIES`: Max retries for transient errors (default: 3)

## Code Quality Workflow

**CRITICAL**: All code changes MUST follow this workflow:

### 1. Pre-Development Checks
```bash
# Ensure clean state
uv run ruff check . && uv run ruff format . && uv run mypy . && uv run pytest
```

### 2. Development Process
- Write code following Python best practices
- Use type hints consistently
- Follow async/await patterns for I/O operations
- Handle errors gracefully with proper logging

### 3. Pre-Commit Quality Gates
```bash
# Format code (auto-fix style issues)
uv run ruff format .

# Lint and auto-fix issues
uv run ruff check --fix .

# Static type check
uv run mypy .

# Run syntax check (catches import/syntax errors early)
make compile-check

# Run full test suite
uv run pytest

# Install git hooks (required once per clone)
uv run --extra dev pre-commit install
# Install Commitizen commit-msg hook to enforce Conventional Commits
uv run --extra dev pre-commit install --hook-type commit-msg
```

Before pushing any branch, rerun the full pre-commit quality check so formatting, lint auto-fix, type checks, syntax validation, and tests all pass when the branch hits the remote:
```bash
# Pre-commit quality check (format, lint, type, syntax, test)
uv run ruff format . && uv run ruff check --fix . && uv run mypy . && make compile-check && uv run pytest
```

### 4. Quality Standards
- **Linting**: Must pass `ruff check .` with zero violations
- **Formatting**: Code must be formatted with `ruff format .`
- **Type Checking**: Static analysis must pass with `uv run mypy .`
- **Testing**: All tests must pass (`uv run pytest`)
- **Type Safety**: Use type hints for all function signatures
- **Error Handling**: Proper exception handling and logging

## Available MCP Tools

### `fetch_pr_review_comments`
Fetches GitHub PR review comments with multiple output formats.

**Parameters**:
- `pr_url` (str): GitHub PR URL (auto-resolves if omitted)
- `output` (str): "markdown" (default), "json", or "both"
- `per_page`, `max_pages`, `max_comments`, `max_retries` (int): Safety limits

**Returns**: Formatted markdown or raw JSON based on `output` parameter.

### `create_review_spec_file`
Creates markdown files from PR comments or pre-rendered markdown.

**Parameters**:
- `markdown` (str, preferred): Pre-rendered markdown content
- `comments` (list, legacy): Raw comments array
- `filename` (str, optional): Output filename (auto-generated if omitted)

**Returns**: Success/error message with file path.

### `resolve_open_pr_url`
Auto-resolves PR URL from current git repository context.

**Parameters**:
- `select_strategy`: "branch" (default), "latest", "first", or "error"
- `owner`, `repo`, `branch`: Override git detection

## Development Commands

### Core Commands
```bash
# Install/update dependencies
uv sync --dev

# Run server
uv run python mcp_server.py

# Quality checks
make lint          # uv run ruff check .
make format        # uv run ruff format .
make test          # uv run pytest -q
make compile-check # uv run python -m compileall -q -f .
```

### Advanced Commands
```bash
# Run tests with coverage
uv run pytest --cov=. --cov-report=html

# Run specific test file
uv run pytest tests/test_git_pr_resolver.py -v

# Lint with auto-fix
uv run ruff check --fix .

# Full quality pipeline
uv run ruff format . && uv run ruff check --fix . && uv run pytest
```

## Sandbox/CI Considerations



### Restricted Environments
- In restricted sandboxes, `uv` may access `~/.cache/uv` and other user dirs. If the environment blocks filesystem access outside the workspace, request elevated permissions for commands like `uv run ...` or `uv sync`.
- Example (Codex CLI): mark the shell step as needing escalation when running `uv run pytest` so it can read/write its cache.
- First-time sync requires network access for dependency resolution

### CI/CD Integration
- All workflows run `make compile-check` for early syntax validation
- Lint and test workflows enforce quality gates
- Use `uv run` consistently to avoid host Python version conflicts

## Testing

Pytest is organized under a single `tests/` tree with clear conventions:

- Test files: `tests/test_*.py`
- Test functions: `test_*`
- Common fixtures: `tests/conftest.py`
- Integration tests: `tests/test_integration.py` (skips when `GITHUB_TOKEN` is not set)
- Pagination safety tests: `tests/test_pagination_limits.py`

Examples:

```bash
uv run pytest -q
uv run pytest tests/test_pagination_limits.py -q
uv run pytest tests/test_integration.py::TestEndToEndWorkflow::test_complete_mock_workflow -q
```

## Best Practices for AI Agents

### Code Implementation
1. **Always run quality checks** before considering code complete
2. **Use `uv run`** for all Python commands (never system Python)
3. **Follow async patterns** for I/O operations (GitHub API calls, file operations)
4. **Handle errors gracefully** with proper logging to stderr
5. **Use type hints** for all function parameters and return values

### Commit Messages
- This repo enforces Conventional Commits via Commitizen using a `commit-msg` hook.
- Hook configuration lives in `.pre-commit-config.yaml` (Commitizen `v1.17.0`).
- Install hooks after cloning:
  - `uv run --extra dev pre-commit install`
  - `uv run --extra dev pre-commit install --hook-type commit-msg`
- Example valid messages:
  - `feat(server): add PR comment fetch pagination`
  - `fix: handle GitHub API 403 with retries`
  - `chore(ci): run compile-check in workflow`

### Testing Strategy
- Write tests for new functionality in `tests/` directory
- Use `pytest-asyncio` for async test functions
- Mock external dependencies (GitHub API, file system)
- Test error conditions and edge cases

### Error Handling
- Log errors to stderr with `print(..., file=sys.stderr)`
- Use `traceback.print_exc(file=sys.stderr)` for debugging
- Return meaningful error messages to MCP clients
- Implement proper retry logic for transient failures

### Security Considerations
- Validate all input parameters (URLs, filenames, numeric limits)
- Use safe file operations (exclusive create, path validation)
- Implement rate limiting and pagination safety caps
- Follow least-privilege principle for GitHub token scopes

## Troubleshooting

### Common Issues
- **Import errors**: Run `make compile-check` to catch syntax issues early
- **Test failures**: Ensure all dependencies are installed with `uv sync --dev`
- **Linting errors**: Use `uv run ruff check --fix .` to auto-fix issues
- **GitHub API errors**: Check `GITHUB_TOKEN` environment variable

### Debug Mode
- Server logs to stderr for debugging
- Use `-v` flag with pytest for verbose test output
- Check `htmlcov/` directory for coverage reports after running tests with coverage

## Quick Reference

| Task | Command |
|------|---------|
| Setup | `uv sync --dev` |
| Quality Check | `make format && make lint && make test` |
| Run Server | `uv run python mcp_server.py` |
| Test Specific File | `uv run pytest tests/test_file.py -v` |
| Fix Linting | `uv run ruff check --fix .` |
| Format Code | `uv run ruff format .` |
