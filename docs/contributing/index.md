# Contributing Guide

Follow this workflow to submit improvements or bug fixes.

## Prerequisites

- Python 3.10+
- `uv` package manager
- `pre-commit`

## Local Setup

```bash
uv sync --dev
uv run --extra dev pre-commit install
uv run --extra dev pre-commit install --hook-type commit-msg
```

## Development Loop

```bash
uv run ruff format .
uv run ruff check --fix .
uv run mypy .
make compile-check
uv run pytest
```

## Conventional Commits

Commit messages must follow [Conventional Commits](https://www.conventionalcommits.org/). Hooks enforce this automatically.

## Opening a Pull Request

1. Ensure the full quality pipeline passes.
2. Update documentation in `docs/` and `CHANGELOG.md` when behaviour changes.
3. Link related issues and request review from maintainers.
