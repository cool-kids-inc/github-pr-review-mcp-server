# Remote Hosting with `uv`

Serve the MCP process on a remote machine to centralise credentials and reduce local setup steps.

## Architecture Overview

```
client host (Claude, Codex) ──ssh──► uv-managed worker ──► GitHub API
```

- The MCP server continues to run over stdio on the worker.
- SSH multiplexing forwards stdio to the client, keeping secrets on the worker.

## Provision the Worker

1. Create a dedicated system user with limited permissions.
2. Install dependencies:
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   uv add mcp-github-pr-review-spec-maker
   ```
3. Store secrets in `/etc/pr-review-spec/.env` with restrictive permissions.

## Launch the Service

Use `systemd` or `supervisord` to keep the process alive:

```ini
[Unit]
Description=GitHub PR Review Spec MCP
After=network.target

[Service]
EnvironmentFile=/etc/pr-review-spec/.env
ExecStart=/usr/local/bin/uv run mcp-github-pr-review-spec-maker --log-level info
Restart=on-failure
User=pr-review
WorkingDirectory=/var/lib/pr-review-spec

[Install]
WantedBy=multi-user.target
```

Enable with `systemctl enable --now pr-review-spec.service`.

## Connect from a Client

Tunnel stdio over SSH in your MCP host configuration:

```bash
claude mcp add pr-review-spec -- \
  ssh user@worker.example.com -- mcp-github-pr-review-spec-maker
```

You can also wrap the remote command in `uvx run` if the worker pins a specific lockfile.

## Observability

- Stream logs with `journalctl -u pr-review-spec -f`.
- Capture metrics via structured logging output (JSON) and feed into your log aggregation system.

## Security Tips

- Restrict the worker's outbound network rules to GitHub domains.
- Rotate PATs regularly and monitor for unusual API rate usage.
- Use SSH certificates or hardware-backed keys for client authentication.
