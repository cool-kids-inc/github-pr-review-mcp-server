# Local stdio Execution

The fastest way to run the server is locally over stdio, which is the default transport for most MCP hosts.

## Setup Checklist

1. Install the package (`uv add mcp-github-pr-review`).
2. Export `GITHUB_TOKEN` in your shell or write it to `.env`.
3. Launch the entry point:
   ```bash
   mcp-github-pr-review --log-level info
   ```
4. Register the server with your host using the command above.

## Optional Flags

| Flag | Description |
| --- | --- |
| `--log-file PATH` | Write structured logs to `PATH` in addition to stderr. |
| `--max-comments N` | Override `PR_FETCH_MAX_COMMENTS` for the process lifetime. |
| `--max-pages N` | Override `PR_FETCH_MAX_PAGES`. |

## Troubleshooting

- **401 Unauthorized**: Validate token scopes and ensure you are not mixing fine-grained and classic tokens.
- **Timeouts**: Increase `HTTP_MAX_RETRIES` and review network firewall policies.
- **Input Path Errors**: Upgrade to the latest version to pick up improvements in Dulwich-based repository detection.
