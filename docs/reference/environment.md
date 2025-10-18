# Environment Variables

The server reads configuration from the environment at startup. Values from `.env` files override system-wide settings.

| Variable | Type | Default | Notes |
| --- | --- | --- | --- |
| `GITHUB_TOKEN` | string | — | Required. Accepts fine-grained or classic PATs with `pull_request:read` scope. |
| `GH_HOST` | string | `github.com` | Automatically updates `GITHUB_API_URL` when not provided. |
| `GITHUB_API_URL` | string | `https://{GH_HOST}/api/v3` | Use for bespoke enterprise routing. |
| `GITHUB_GRAPHQL_URL` | string | `https://{GH_HOST}/api/graphql` | GraphQL endpoint. Reserved for future roadmap features. |
| `PR_FETCH_MAX_PAGES` | int | `50` | Guardrail for runaway pagination. |
| `PR_FETCH_MAX_COMMENTS` | int | `2000` | Soft limit for produced markdown size. |
| `HTTP_PER_PAGE` | int | `100` | Range `1..100`. |
| `HTTP_MAX_RETRIES` | int | `3` | Retries for request timeouts and 5xx responses. |
| `LOG_LEVEL` | string | `INFO` | Standard Python log level names. |
| `LOG_JSON` | bool | `false` | Emit machine-readable JSON logs when `true`. |

Set environment variables permanently via your shell profile or pass them directly through MCP host configuration.
