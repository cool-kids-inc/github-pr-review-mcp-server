.PHONY: compile-check lint format test sync

# Use uv consistently to avoid host Python differences

compile-check:
	uv run python -m compileall -q -f .

lint:
	uv run ruff check .

format:
	uv run ruff format .

test:
	uv run pytest -q

sync:
	uv sync --dev

