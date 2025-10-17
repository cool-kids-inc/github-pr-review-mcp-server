# MCP Tool Reference

## `fetch_pr_review_comments`

- **Description**: Fetch review comments from a GitHub pull request and render them as Markdown or JSON.
- **Parameters**:
  - `pr_url` (string, optional): Full PR URL. When omitted, auto-resolves from git metadata.
  - `output` (enum): `"markdown"` (default), `"json"`, or `"both"`.
  - `per_page` (int): Overrides pagination size. Defaults from `HTTP_PER_PAGE`.
  - `max_pages` (int): Safety cap on pagination loops. Defaults from `PR_FETCH_MAX_PAGES`.
  - `max_comments` (int): Hard limit on total comments collected. Defaults from `PR_FETCH_MAX_COMMENTS`.
  - `max_retries` (int): Overrides HTTP retry budget. Defaults from `HTTP_MAX_RETRIES`.

### Response

Returns one or two text blocks depending on the `output` parameter. Markdown responses are formatted with review comment details including resolution status and code context.

## `resolve_open_pr_url`

- **Description**: Resolve the open pull request that matches the current repository and branch.
- **Parameters**:
  - `select_strategy` (enum): One of `branch`, `latest`, `first`, `error`.
  - `owner`, `repo`, `branch` (string, optional): Override auto-detected values.

### Response

String containing the PR URL, e.g. `https://github.com/cool-kids-inc/github-pr-review-mcp-server/pull/42`.

## Error Codes

| Code | Description | Recommended Action |
| --- | --- | --- |
| `invalid-arguments` | Missing or malformed parameters. | Inspect payload and reissue with valid fields. |
| `not-found` | PR or repository not available. | Confirm URL or repository access. |
| `unauthorized` | Authentication failure. | Update `GITHUB_TOKEN` scopes or validity. |
| `rate-limited` | GitHub API throttling. | Reduce frequency or raise limits with fewer comments per call. |
| `internal-error` | Unhandled exception. | Review server logs, file an issue with stack trace. |
