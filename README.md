# GitHub PR Review Spec Generator (MCP Server)

This is a Model Context Protocol (MCP) server that allows a large language model (LLM) like Claude to fetch review comments from a GitHub pull request and generate a markdown spec file.

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
   pip install -r requirements-dev.txt  # For development
   ```

4. **Set up environment variables:**
   - Create a `.env` file and add your GitHub personal access token:
     ```bash
     echo "GITHUB_TOKEN=your_github_token_here" > .env
     ```

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

### Pre-commit Checks

Before committing, ensure your code passes all checks:

```bash
# Format and lint
ruff format . && ruff check . --fix

# Run tests
pytest

# Check types (if using mypy)
mypy .
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
```

The server will start and listen for requests over `stdio`, making its tools available to a connected MCP client (e.g., Claude Desktop).

## Available Tools

The server exposes the following tools to the LLM:

### 1. `fetch_pr_review_comments(pr_url: str) -> list`

Fetches all review comments from a given GitHub pull request URL.

-   **Parameters:**
    -   `pr_url` (str): The full URL of the pull request (e.g., `"https://github.com/owner/repo/pull/123"`).
    -   `per_page` (int, optional): GitHub page size (1–100). Defaults from env `HTTP_PER_PAGE`.
    -   `max_pages` (int, optional): Safety cap on pages. Defaults from env `PR_FETCH_MAX_PAGES`.
    -   `max_comments` (int, optional): Safety cap on total comments. Defaults from env `PR_FETCH_MAX_COMMENTS`.
    -   `max_retries` (int, optional): Retry budget for transient errors. Defaults from env `HTTP_MAX_RETRIES`.
-   **Returns:**
    -   A list of comment objects, where each object is a dictionary containing details about the comment. Returns an empty list if no comments are found. On error, may return an empty list or a list containing an error object.

### 2. `create_review_spec_file(comments: list, filename: str | None = None) -> str`

Creates a markdown file containing the formatted review comments.

-   **Parameters:**
    -   `comments` (list): A list of comment objects, typically the output from the `fetch_pr_review_comments` tool.
    -   `filename` (str, optional): Basename for the output file (must match `[A-Za-z0-9._-]{1,80}\.md` with no path separators). If omitted, a unique name like `spec-YYYYmmdd-HHMMSS-xxxx.md` is generated.
-   **Returns:**
    -   A string indicating whether the file was created successfully or if an error occurred. Files are created under `./review_specs/` with exclusive create to avoid overwrite.

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

For compatibility, the original `requirements.txt` and `requirements-dev.txt` files are maintained, but the modern workflow using `pyproject.toml` and UV is recommended for development.

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
