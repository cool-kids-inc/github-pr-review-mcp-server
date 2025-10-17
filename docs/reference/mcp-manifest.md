# MCP Manifest (`mcp.json`)

MCP directories (Cursor, Claude Desktop, etc.) index servers using a manifest file named `mcp.json`. Publishing this package to their marketplaces requires bundling a manifest alongside the Python distribution.

## Recommended Schema

```json
{
  "name": "pr-review-spec",
  "version": "0.2.0",
  "description": "Generate review specs from GitHub pull requests",
  "command": "mcp-github-pr-review-spec-maker",
  "args": [],
  "env": {
    "GITHUB_TOKEN": {
      "description": "GitHub PAT with pull-request read access",
      "required": true
    }
  },
  "homepage": "https://github.com/petersouter/mcp-github-pr-review-spec-maker",
  "license": "MIT",
  "categories": ["code-review", "github"]
}
```

### Key Fields

- `name`: Identifier displayed in marketplaces.
- `command`: Must match the console script installed from PyPI.
- `env`: Document required secrets so hosts can surface configuration prompts.
- `categories`: Helps marketplaces classify the server for discovery.

## Distribution Bundles

When publishing to PyPI, place `mcp.json` inside the package directory (e.g. `src/mcp_github_pr_review_spec_maker/mcp.json`). Update `MANIFEST.in` or Hatch build settings to ensure the file ships with the wheel and source distribution.

## Versioning Strategy

- Align `mcp.json`'s `version` with the Python package version.
- Update `description`, `args`, and environment documentation when CLI defaults change.

## Marketplace Notes

- **Cursor**: requires `command` and `args` pointing to an executable on the PATH. Bundling the console script simplifies installation.
- **Claude Desktop**: reads `homepage`, `license`, and `env` metadata to display the onboarding UI.
