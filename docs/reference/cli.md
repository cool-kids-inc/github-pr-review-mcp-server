# CLI Reference

The package installs the console script `mcp-github-pr-review`. The CLI accepts the following options:

```text
Usage: mcp-github-pr-review [OPTIONS]
```

| Option | Description |
| --- | --- |
| `--log-level {debug,info,warning,error}` | Set logging verbosity. Defaults to `info`. |
| `--log-file PATH` | Append log output to `PATH`. Stderr remains enabled. |
| `--max-pages N` | Override `PR_FETCH_MAX_PAGES` for this process. |
| `--max-comments N` | Override `PR_FETCH_MAX_COMMENTS` for this process. |
| `--json-logs` | Emit JSON formatted log lines. |
| `--help` | Show usage information. |

All options can also be provided via environment variables. Command-line flags take precedence over `.env` or shell variables.
