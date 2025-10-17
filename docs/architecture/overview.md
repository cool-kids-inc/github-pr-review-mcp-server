# Architecture Overview

The MCP server orchestrates three subsystems:

1. **Transport layer** (`mcp` framework): handles stdio protocol negotiation and tool invocation.
2. **GitHub client** (`httpx`): fetches pull-request review comments with retry and pagination safeguards.
3. **Git workspace resolver** (`dulwich`): maps the active git repository to a PR URL when one is not provided.

![Architecture Diagram](../assets/demo.gif)

## Execution Flow

1. MCP host calls `fetch_pr_review_comments`.
2. Server resolves the PR URL using the `git_pr_resolver` module when necessary.
3. HTTP requests retrieve review comments, applying concurrency and rate limiting.
4. Comments are transformed into a markdown specification via the `specs` templates.
5. Response returns to the host in the requested format (Markdown or JSON).

## Concurrency Model

The server is asynchronous, relying on `asyncio` to keep HTTP operations non-blocking. HTTP calls use `httpx.AsyncClient` with circuit breakers for GitHub throttling.

## Error Handling

- Expected HTTP failures (401, 403, 404) surface as structured MCP errors for agent awareness.
- Transient errors trigger retries with exponential backoff and jitter.
- Uncaught exceptions are logged with stack traces but masked from remote clients to avoid information leakage.

## Extensibility

- Add new MCP tools by registering their schema in `src/mcp_github_pr_review/server.py` and implementing async handlers under `tools/`.
- Comment formatting templates live in the server code. Extend the `generate_markdown()` function for new output formats.
- Logging integrates with standard `logging` instrumentation. Add adapters to stream to JSON or observability backends.
