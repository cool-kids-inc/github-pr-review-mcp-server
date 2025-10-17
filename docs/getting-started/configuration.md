# Configuration

The MCP server reads configuration from environment variables or a `.env` file in the working directory. Use these controls to tune pagination limits, HTTP behaviour, and GitHub endpoints.

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `GITHUB_TOKEN` | ✅ | — | GitHub personal access token scoped to read pull-request comments. |
| `GH_HOST` | ❌ | `github.com` | GitHub Enterprise hostname. Automatically derives REST/GraphQL endpoints. |
| `GITHUB_API_URL` | ❌ | `https://{GH_HOST}/api/v3` | Override REST endpoint when the default convention is incorrect. |
| `GITHUB_GRAPHQL_URL` | ❌ | `https://{GH_HOST}/api/graphql` | Override GraphQL endpoint. |
| `PR_FETCH_MAX_PAGES` | ❌ | `50` | Maximum pages fetched per PR to prevent runaway pagination. |
| `PR_FETCH_MAX_COMMENTS` | ❌ | `2000` | Cap on total review comments collected. |
| `HTTP_PER_PAGE` | ❌ | `100` | GitHub page size. Must be between 1 and 100. |
| `HTTP_MAX_RETRIES` | ❌ | `3` | Retry budget applied to transient HTTP failures. |

Store secrets using `.env` in development and delegate to your secrets manager or CI variables in production:

```bash
GITHUB_TOKEN=ghp_...
PR_FETCH_MAX_COMMENTS=1000
```

### Logging configuration

Set `LOG_LEVEL` (`DEBUG`, `INFO`, `WARNING`, `ERROR`) to control verbosity. Logs are written to stderr by default and can be directed to a file using the `--log-file` CLI flag.

### MPC Manifest overrides

When packaging for MPC directories, you can bundle default configuration inside `mcp.json`. See [MCP Manifest](../reference/mcp-manifest.md) for schema guidance.
