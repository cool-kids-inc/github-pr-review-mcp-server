# Installation

The MCP server is published as the Python package `mcp-github-pr-review-spec-maker`. You can install it using `uv`, pip, or integrate it directly into a project that manages dependencies through `pyproject.toml`.

## Install with `uv`

```bash
# Add the package to your environment
uv add mcp-github-pr-review-spec-maker

# Or install with extras required for development
uv add mcp-github-pr-review-spec-maker[dev]
```

## Install with `pip`

```bash
python -m venv .venv
source .venv/bin/activate
pip install mcp-github-pr-review-spec-maker
```

## Verify the Entry Point

After installation, the console script `mcp-github-pr-review-spec-maker` becomes available:

```bash
mcp-github-pr-review-spec-maker --help
```

This entry point wraps `uv run python -m mcp_github_pr_review_spec_maker.server` when installed from PyPI.

## Using as a Dependency

If you are bundling the MCP server inside another project, declare it in your `pyproject.toml`:

```toml
[project]
dependencies = [
  "mcp-github-pr-review-spec-maker>=0.2.0",
]
```

The server can then be imported as `mcp_github_pr_review_spec_maker` for programmatic integration or CLI invocation.
