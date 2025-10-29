# Spec: Python CLI UX for Agent Configuration & Setup

## Background
- The project currently relies on a sprawling Bash helper (`run-server.sh:1`) to install dependencies, manage `.env` files, and register the MCP server with clients such as Claude, Codex, and Gemini. The script spans hundreds of lines, making it hard to maintain, test, and extend.
- Shell logic duplicates environment validation already present in Python (for example, GitHub token checks in `src/mcp_github_pr_review/server.py`) and forces contributors to debug cross-platform shell behaviour.
- Users lack a discoverable `--help` surface area, and agent/client-specific instructions are spread across `AGENTS.md`, `CLAUDE.md`, and inline script prompts.
- The project already embraces modern Python tooling (`uv`, Pydantic plans, async httpx usage), making a Python-native CLI a natural fit.

## Goals
- Provide a first-class Python CLI (exposed as `mcp-github-pr`) that guides users through configuration, validation, and execution tasks with consistent UX.
- Centralise configuration management (Codex, Claude CLI/Desktop, Gemini, GitHub auth, server defaults) using typed settings objects backed by structured config files.
- Replace brittle shell flows with testable Python commands while preserving the ability to run the MCP server end-to-end.
- Offer clear `--help` output and subcommand documentation so contributors can discover capabilities without reading source.
- Update documentation to reflect the new workflow and deprecate the shell script path.

## Non-Goals
- Automating editor/IDE-specific integrations beyond the existing agent clients.
- Changing the underlying MCP server runtime behaviour or tool interface semantics.
- Introducing GUI elements; the focus is CLI-only.
- Implementing package installers or dependency managers beyond the existing `uv` flow (we will continue to rely on `uv sync`/`uv run`).

## User Experience Requirements
- **Entry point**: `mcp-github-pr` installed via the existing console script entrypoint in `pyproject.toml`.
- **Top-level commands**:
  - `quickstart`: interactive first-time setup wizard combining init, validation, and agent snippet generation in one flow.
  - `config init`: create config files (TOML + .env) with guided prompts for GitHub token, server settings, log path.
  - `config set <key> <value>` / `config unset <key>`: modify settings non-interactively (supports scripting, uses dotted paths like `github.token`).
  - `config validate`: verify GitHub PAT (format, connectivity, scopes) via lightweight API call and report actionable errors with recovery steps.
  - `config show`: display current configuration with secrets masked (e.g., `ghp_abc...xyz`).
  - `config migrate`: migrate from legacy `.env`-only setup to new TOML + .env structure with automatic backup.
  - `config edit`: open config file in `$EDITOR` for manual editing.
  - `config reset`: reset to defaults with confirmation prompt.
  - `agents list`: show supported agent clients (Claude CLI/Desktop, Codex, Gemini) with integration status.
  - `agents snippet <name>`: **generate** configuration snippets for users to copy into agent configs (never auto-write to agent files).
  - `agents verify <name>`: test if specified agent can reach the MCP server.
  - `server run [--log] [--no-sync] [--follow]`: spawn MCP server as subprocess with options currently handled by bash script.
  - `server debug`: run server with verbose logging to stderr for development.
  - `server logs`: tail server logs if `--log` was used previously.
  - `doctor`: comprehensive health checks (Python version, uv, GitHub connectivity, token scopes, config validity, server smoke test) with clear success/warning/failure indicators and exit codes for CI.
  - `version --check`: display version and optionally check for updates.
- **Help system**:
  - `--help` on root and each subcommand shows one-line description, usage examples (not just synopsis), environment variable alternatives, default values, and links to docs.
  - Include common troubleshooting scenarios in help text.
- **Config locations & precedence**:
  - **Precedence order** (highest to lowest):
    1. CLI flags (e.g., `--github-token`)
    2. Environment variables (e.g., `GITHUB_TOKEN`)
    3. TOML config file (e.g., `~/.config/github-pr-review-mcp/config.toml`)
    4. `.env` file (legacy, warn if found without TOML)
  - **File structure**:
    - `~/.config/github-pr-review-mcp/config.toml` (non-secret settings)
    - `~/.config/github-pr-review-mcp/.env` (secrets only: `GITHUB_TOKEN`)
    - Windows: `%APPDATA%/github-pr-review-mcp/` instead
  - Support `XDG_CONFIG_HOME` and override via `--config-path` or `MCP_PR_CONFIG` env var.
  - **Never store secrets in TOML** (only in .env with restricted permissions).
- **Auth validation**:
  - `config validate` performs GitHub API call (`/user`) with token, checks response for scopes, tests connectivity with timeout.
  - Reports: token format validity, API reachability, required scopes (repo, read:org if applicable).
  - Provides actionable error messages with recovery steps and links to GitHub token creation.
- **Error messages**: All errors include:
  - Clear description of what went wrong
  - Context (which config file, which API call)
  - Actionable next steps (numbered list)
  - Relevant documentation links
  - Example: "✗ GitHub token invalid (401 Unauthorized)\n\nYour token at GITHUB_TOKEN may have expired or lack required scopes.\n\nNext steps:\n  1. Generate a new token: https://github.com/settings/tokens/new?scopes=repo\n  2. Update: mcp-github-pr config set github.token ghp_xxx\n  3. Verify: mcp-github-pr config validate"
- **Graceful logging**: Use `rich` for friendly CLI output with progress bars, color-coded status (✓/✗/⚠), while supporting `--json` for automation. Provide `--quiet` flag for CI/scripting.

## Architectural Approach
- **CLI framework**: Use `typer` (already in ecosystem, async-friendly via `typer.run` wrappers) for ergonomic commands, automatic `--help`, and integration with click testing utilities. Make CLI dependencies optional via `[cli]` extras in `pyproject.toml` for users who only need the MCP server.
- **Settings layer**: Introduce `src/mcp_github_pr_review/config/` package using `pydantic-settings` for typed configuration:
  - `config/models.py`:
    ```python
    class GitHubSettings(BaseSettings):
        token: SecretStr  # From .env only
        api_url: str = "https://api.github.com"
        graphql_url: str = "https://api.github.com/graphql"
        host: str = "github.com"

    class ServerSettings(BaseSettings):
        max_pages: int = 50
        max_comments: int = 2000
        per_page: int = 100
        max_retries: int = 3

    class LoggingSettings(BaseSettings):
        level: str = "INFO"
        path: Path | None = None

    class AppConfig(BaseSettings):
        config_version: int = 1  # For schema migrations
        github: GitHubSettings
        server: ServerSettings
        logging: LoggingSettings

        model_config = SettingsConfigDict(
            env_nested_delimiter='__',  # GITHUB__TOKEN
            toml_file='~/.config/github-pr-review-mcp/config.toml',
        )
    ```
  - Separate concerns: secrets in `.env`, non-secrets in `config.toml`
  - Support precedence: CLI flags → env vars → TOML → .env (legacy)
  - **Remove agent-specific config models** (Claude/Codex/Gemini): agents discover the MCP server, not the reverse
- **Config persistence**: Implement `config/repository.py` with `SettingsRepository` class:
  - Read/write config atomically using `pathlib.Path` with `os.replace()` to avoid partial writes
  - Create `.env` with secure permissions (0o600 on Unix, ACL restrictions on Windows)
  - Validate `.env` is in `.gitignore` if repo is git-tracked
  - Provide schema migration hooks using `config_version` field
  - Never log or display full tokens (mask to `ghp_abc...xyz` format)
  - Automatic backup before migrations (`.env.backup.TIMESTAMP`, `config.toml.backup.TIMESTAMP`)
- **Command modules**:
  - `src/mcp_github_pr_review/cli/__init__.py`: entry point with Typer app creation, version metadata from `importlib.metadata`
  - `.../cli/config.py`: subcommands for init/set/unset/validate/show/migrate/edit/reset depending on settings module
  - `.../cli/agents.py`: snippet generation (not file writing) for Claude CLI/Desktop, Codex CLI, Gemini with syntax validation
  - `.../cli/server.py`: **always spawn subprocess** for server (via `uv run` or direct Python); never in-process (MCP uses stdio, conflicts with CLI stdout)
  - `.../cli/doctor.py`: health check implementation with structured output
  - `.../cli/quickstart.py`: interactive wizard combining multiple commands
- **GitHub auth checks**: Extract HTTP client setup from `server.py` into `config/github_validator.py` for reuse. Provide async functions (`validate_token()`, `check_token_scopes()`) invoked by CLI commands.
- **Logging & output**:
  - CLI commands: use `rich.console.Console` for user-facing output, `rich.logging.RichHandler` for debug logs
  - Server: keep existing logging unaffected (writes to stderr when run as subprocess)
  - Provide `--json` flag for machine-readable output
  - Add `--quiet` flag to suppress non-error output
- **Security**:
  - Implement `config/security.py` with secure file permission helpers
  - Optional audit log (`~/.config/github-pr-review-mcp/audit.log`) for config changes and validation attempts
  - Token masking in all output (never show full token except during initial setup with confirmation)

## Migration Plan

### Phase 1: Introduce CLI (Version N - Current)
1. **CLI skeleton**
   - Add Typer app with placeholder commands and `--version` metadata reading from `importlib.metadata`
   - Register console script entrypoint (`mcp-github-pr`)
   - Add `[cli]` optional dependency group in `pyproject.toml`
2. **Settings layer**
   - Define Pydantic settings models in `config/models.py`
   - Implement `SettingsRepository` in `config/repository.py` with atomic read/write/migrate
   - Implement secure file permissions in `config/security.py`
   - Support `.env` fallback with warnings; offer migration path
3. **Core commands**
   - `config init/set/unset/validate/show/migrate/edit/reset`
   - `agents list/snippet/verify` (snippet generation, not file writing)
   - `server run/debug/logs` (always subprocess, never in-process)
   - `doctor` (comprehensive health checks)
   - `quickstart` (interactive wizard)
4. **Testing foundation**
   - Unit tests with `typer.testing.CliRunner` and `pytest-httpx`
   - Integration tests with mocked GitHub responses
   - Cross-platform tests (Windows/macOS/Linux paths)
5. **Documentation**
   - Add `docs/cli.md` with command reference and config schema
   - Add `docs/migration.md` with detailed migration guide
   - Add `docs/ci-migration.md` for CI/CD pipeline updates
   - Update `README.md` to mention both bash and CLI options
   - Keep bash script fully functional with note about CLI availability

### Phase 2: Promote CLI (Version N+1 - Next Release)
1. **Auto-migration helper**
   - `run-server.sh` detects first run without TOML config
   - Offers to run `mcp-github-pr config migrate` automatically
   - Shows clear warning: "Bash script is deprecated, use mcp-github-pr CLI"
   - Continues to work but prints migration instructions on every run
2. **Enhanced documentation**
   - `README.md` primarily shows CLI commands, bash script in "Legacy" section
   - All integration guides (`AGENTS.md`, `CLAUDE.md`) updated to CLI-first
   - Add migration success stories/testimonials if available
3. **Monitoring**
   - Optional telemetry (opt-in) to track CLI vs bash usage
   - GitHub issue template for migration problems

### Phase 3: Remove Bash Script (Version N+2 - Future Release)
1. **Final removal**
   - Delete `run-server.sh` from repository
   - Keep `mcp-github-pr config migrate` indefinitely for late adopters
   - Archive bash script in `docs/legacy/` with warning header
2. **Documentation cleanup**
   - Remove all bash script references from main docs
   - Update installation instructions to CLI-only
   - Create "Upgrading from Pre-CLI Versions" guide

### Migration Safety Features
- **Automatic backups**: All migrations create timestamped backups (`.env.backup.TIMESTAMP`, `config.toml.backup.TIMESTAMP`)
- **Dry-run mode**: `mcp-github-pr config migrate --dry-run` shows what would change without modifying files
- **Rollback helper**: `mcp-github-pr config rollback` restores most recent backup
- **Validation before commit**: Migration always runs `validate` and won't complete if checks fail
- **CI compatibility check**: `mcp-github-pr doctor --ci` validates config for CI environment

### Breaking Changes Mitigation
| Risk | Mitigation |
|------|-----------|
| Users with customized `.env` lose settings | `config migrate` preserves all variables, backs up original, validates after migration |
| CI pipelines break | Provide `docs/ci-migration.md` with examples for GitHub Actions, GitLab CI, etc.; bash script works in N+1 |
| Agent integrations stop working | Snippets guide users through updates; `agents verify` tests connectivity before switching |
| Windows path handling differs | Comprehensive cross-platform tests; Windows-specific helpers in `config/security.py` |
| Config format confusion | Clear precedence documented; `config show` displays effective config with source annotations |

## Testing Strategy

### Unit Tests
- **`tests/test_cli_config.py`**: Config management commands
  - Settings round-trips (read → modify → write → read)
  - Command behaviors (init/set/unset/validate/show/migrate/edit/reset)
  - Error messages with recovery steps
  - Config precedence (CLI flags > env vars > TOML > .env)
  - Token masking in all output paths
- **`tests/test_cli_agents.py`**: Agent integration
  - Snippet generation for Claude CLI/Desktop, Codex, Gemini
  - Snippet syntax validation (valid JSON/TOML)
  - Verify command (mock server connectivity tests)
  - List command with integration status detection
- **`tests/test_cli_server.py`**: Server command wrappers
  - Subprocess spawning (never in-process)
  - Log tailing functionality
  - Debug mode with verbose output to stderr
  - Proper handling of `--sync/--no-sync` flags
- **`tests/test_cli_doctor.py`**: Health checks
  - All checks pass scenario
  - Individual check failures with appropriate exit codes
  - JSON output mode for CI consumption
  - Warning vs. error distinction
- **`tests/test_cli_quickstart.py`**: Interactive wizard
  - Full flow with mocked user input
  - Partial completion and resume
  - Error handling mid-flow
- **`tests/test_cli_migration.py`**: Migration scenarios (new)
  - Migrate from `.env`-only setup
  - Migrate with both `.env` and old config
  - Automatic backups created correctly
  - Dry-run mode (no actual changes)
  - Rollback functionality
  - Validation after migration

### Integration Tests
- **`tests/test_cli_end_to_end.py`**: Full workflows
  - Init → validate → server run with mocked GitHub HTTP (use `pytest-httpx`)
  - Quickstart → agents snippet → server run
  - Config set → validate → show (verify changes)
  - Migration → validate → doctor (ensure health)
- **`tests/test_cli_http.py`**: GitHub API interactions
  - Token validation with various response codes (200, 401, 403, 404, 500)
  - Scope checking (repo, read:org detection)
  - Network timeout handling
  - Rate limiting responses
  - Retry logic on transient failures

### Cross-Platform Tests
- **`tests/test_cli_cross_platform.py`**: Platform-specific behavior
  ```python
  @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific")
  def test_windows_config_path(): ...
  def test_windows_acl_permissions(): ...

  @pytest.mark.skipif(sys.platform != "darwin", reason="macOS-specific")
  def test_macos_claude_desktop_path_detection(): ...

  @pytest.mark.skipif(sys.platform == "win32", reason="Unix-specific")
  def test_unix_file_permissions_0o600(): ...
  ```
- **Filesystem behavior**: Atomic writes, permissions, `XDG_CONFIG_HOME`, `%APPDATA%`

### Security Tests
- **`tests/test_cli_security.py`**: Security-sensitive operations
  - File permissions on `.env` (0o600 on Unix)
  - Windows ACL restrictions
  - Token masking in logs and output
  - `.gitignore` validation for `.env` files
  - Audit log entries for config changes
  - No secrets in TOML files

### Regression Tests
- **`tests/test_cli_server_compatibility.py`**: MCP server integration
  - Ensure existing MCP server tools still work
  - Verify stdin/stdout protocol not affected by CLI
  - Test server spawned via CLI behaves identically to direct invocation

### Snapshot Tests
- **`tests/snapshots/`**: Help text and output format stability
  - Capture `--help` output for all commands
  - Validate error message formats
  - Ensure consistent styling across commands

### Documentation Tests
- **`tests/test_cli_docs.py`**: Documentation verification
  - All commands mentioned in `docs/cli.md` are implemented
  - Code examples in docs are syntactically valid
  - Config schema in docs matches `AppConfig` model
  - Command tree in docs matches actual Typer app structure

### Test Fixtures (in `conftest.py`)
- `temp_config_dir`: Temporary config directory with `tmp_path`
- `mock_github_api`: Pre-configured `pytest-httpx` mock for common responses
- `mock_git_repo`: Temporary git repository for testing git integration
- `cli_runner`: Pre-configured `typer.testing.CliRunner` with isolation
- `sample_env_file`: Fixture providing various `.env` file scenarios
- `sample_toml_config`: Fixture providing valid/invalid TOML configs

## Documentation Updates

### New Documentation Files

#### `docs/cli.md` - CLI Reference
Complete command reference including:
- **Command tree** (hierarchical structure of all commands)
- **Configuration file schema** (TOML format with examples)
- **Configuration precedence** (detailed table with examples)
- **Environment variables** (complete list with defaults)
- **Help text examples** (showing actual `--help` output)
- **Common workflows** (init, migration, validation, server run)
- **Troubleshooting guide** (common errors with solutions)
- **Exit codes reference** (for CI/automation usage)

Example sections:
```markdown
## Configuration File Schema

Location: `~/.config/github-pr-review-mcp/config.toml`

```toml
config_version = 1

[github]
api_url = "https://api.github.com"
graphql_url = "https://api.github.com/graphql"
host = "github.com"

[server]
max_pages = 50
max_comments = 2000
per_page = 100
max_retries = 3

[logging]
level = "INFO"
# path = "/var/log/mcp-github-pr.log"  # Optional
```

**Secrets** (in `.env` file, same directory):
```bash
GITHUB_TOKEN=ghp_xxxxxxxxxxxxx
```

## Command Reference

### mcp-github-pr config validate

Validate GitHub token and configuration.

**Usage:**
```bash
mcp-github-pr config validate [OPTIONS]
```

**Options:**
- `--config-path PATH` - Custom config file location
- `--json` - Output results as JSON
- `--quiet` - Suppress non-error output

**Examples:**
```bash
# Basic validation
mcp-github-pr config validate

# With custom config
mcp-github-pr config validate --config-path ./custom.toml

# For CI (JSON output)
mcp-github-pr config validate --json --quiet
```

**Checks performed:**
- ✓ Token format validity (ghp_* pattern)
- ✓ GitHub API connectivity (timeout: 10s)
- ✓ Required scopes (repo, read:org if applicable)
- ✓ Rate limit status

**Exit codes:**
- 0: All checks passed
- 1: Validation failed
- 2: Configuration file not found

**See also:** https://github.com/.../docs/cli.md#validate
```

#### `docs/migration.md` - Migration Guide
Comprehensive migration documentation:
- **Quick Migration** (single command path for 90% of users)
- **What Changed** (table comparing bash vs CLI)
- **Step-by-Step Migration** (detailed instructions with examples)
- **Agent Config Updates** (snippets for each agent)
- **CI/CD Migration** (updating pipelines)
- **Troubleshooting** (common migration issues)
- **Rollback Procedure** (how to revert if needed)
- **FAQ** (frequently asked questions)

Example table:
```markdown
## Quick Reference

| Old (Bash) | New (CLI) | Notes |
|------------|-----------|-------|
| `./run-server.sh` | `mcp-github-pr server run` | Subprocess-based |
| Edit `.env` manually | `mcp-github-pr config set <key> <value>` | Dotted paths |
| Source code reading | `mcp-github-pr --help` | Built-in docs |
| Shell script edits | Edit `config.toml` | Structured config |
| N/A | `mcp-github-pr doctor` | Health checks |
| N/A | `mcp-github-pr quickstart` | Interactive setup |
```

#### `docs/ci-migration.md` - CI/CD Pipeline Updates
CI-specific migration guide:
- **GitHub Actions examples** (before/after)
- **GitLab CI examples**
- **Jenkins examples**
- **Docker image implications**
- **Environment variable precedence in CI**
- **Validation-only mode** (no interactive prompts)
- **JSON output for parsing**

Example:
```markdown
## GitHub Actions Migration

### Before (Bash Script)
```yaml
- name: Setup MCP Server
  run: ./run-server.sh --validate
  env:
    GITHUB_TOKEN: ${{ secrets.GH_TOKEN }}
```

### After (CLI)
```yaml
- name: Validate MCP Config
  run: |
    uv sync
    uv run mcp-github-pr doctor --ci --json
  env:
    GITHUB_TOKEN: ${{ secrets.GH_TOKEN }}
```
```

#### `docs/quickstart.md` - New User Onboarding
Fast-track guide for new users:
- **Prerequisites** (Python, uv, GitHub token)
- **Installation** (`uv sync`, verify install)
- **First-Time Setup** (using `quickstart` command)
- **Verify Installation** (using `doctor`)
- **Your First PR Comment Fetch** (example workflow)
- **Next Steps** (integrating with agents)

### Updated Documentation Files

#### `README.md`
- **Installation section**: Add CLI-first instructions
- **Quick Start**: Replace bash script with `mcp-github-pr quickstart`
- **Common Tasks table**: Map tasks to CLI commands
- **Configuration section**: Reference new config files and precedence
- **Migration notice**: Link to `docs/migration.md` for existing users
- **Table of Commands**: Quick reference for all CLI commands

Example addition:
```markdown
## Quick Start

### New Users
```bash
# Install dependencies
uv sync

# Interactive setup
uv run mcp-github-pr quickstart

# Verify installation
uv run mcp-github-pr doctor
```

### Common Commands
| Task | Command |
|------|---------|
| Configure server | `mcp-github-pr config init` |
| Set GitHub token | `mcp-github-pr config set github.token ghp_xxx` |
| Validate setup | `mcp-github-pr config validate` |
| Run MCP server | `mcp-github-pr server run` |
| Health check | `mcp-github-pr doctor` |
| Get agent snippets | `mcp-github-pr agents snippet claude-cli` |
```

#### `AGENTS.md`
- Update integration steps to use `agents snippet <name>` instead of manual editing
- Add `agents verify <name>` step after configuration
- Include exact snippet examples for each agent
- Add troubleshooting section specific to agent connectivity

Example:
```markdown
## Claude Desktop Integration

1. Generate configuration snippet:
   \`\`\`bash
   mcp-github-pr agents snippet claude-desktop
   \`\`\`

2. Copy the output into your Claude Desktop config:
   - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - Windows: `%APPDATA%\Claude\claude_desktop_config.json`

3. Verify connectivity:
   \`\`\`bash
   mcp-github-pr agents verify claude-desktop
   \`\`\`

4. Restart Claude Desktop
```

#### `CLAUDE.md`
- Update all command references to use `mcp-github-pr` instead of bash script
- Add quality check command that includes `mcp-github-pr doctor`
- Reference new configuration system

#### `UV_COMMANDS.md`
- Add section on CLI commands: `uv run mcp-github-pr ...`
- Highlight preferred execution paths during development
- Add examples for common CLI operations

#### `SECURITY.md`
- **Config file security**: Note that `.env` requires 0o600 permissions (auto-set by CLI)
- **Token storage**: Emphasize secrets go in `.env`, never in TOML or version control
- **Audit logging**: Document optional audit log feature and format
- **Agent snippet review**: Note that generated snippets still require human review before adding to agent configs
- **Safe practices**: Outline recommendations for token rotation, scope limitation

Example addition:
```markdown
## Configuration Security

### Token Storage
- **Never** store tokens in `config.toml` (version-controlled or world-readable)
- **Always** use `.env` file for secrets
- CLI automatically sets `.env` permissions to 0o600 (owner-only read/write on Unix)
- Windows: CLI applies ACL restrictions to limit access

### Audit Trail
Enable optional audit logging for security-sensitive operations:
```toml
[logging]
audit_log = true  # Creates ~/.config/github-pr-review-mcp/audit.log
```

Audit log format:
```
2025-10-29T10:15:23Z config.set github.token (by user, via CLI)
2025-10-29T10:16:45Z config.validate success (scopes: repo)
```

### Best Practices
1. Use fine-grained tokens with minimum required scopes
2. Rotate tokens regularly (set expiration when creating)
3. Review audit logs for unexpected access
4. Never commit `.env` files (CLI validates `.gitignore`)
```

### Documentation Standards
All documentation should include:
- **Code examples** that are copy-pasteable
- **Expected output** for commands when helpful
- **Common errors** and their solutions
- **Cross-references** to related commands/docs
- **Version compatibility** notes where relevant
- **Platform-specific notes** (Windows/macOS/Linux) where behavior differs

## Doctor Command Implementation

The `doctor` command is a comprehensive health check tool for validating the entire MCP server setup.

### Check Sequence (fail-fast on critical errors)

1. **Python Version Check** (Critical)
   - Verify Python >= 3.10
   - Exit code: 1 if fails
   - Message: "✗ Python 3.10+ required, found 3.9.1. Please upgrade Python."

2. **UV Binary Check** (Critical)
   - Verify `uv` command available
   - Display version: "✓ uv 0.1.23"
   - Exit code: 1 if missing
   - Message: "✗ uv not found. Install: curl -LsSf https://astral.sh/uv/install.sh | sh"

3. **Config File Check** (Warning if missing, not critical)
   - Check if config.toml exists
   - Validate TOML syntax
   - Validate against Pydantic schema
   - Warning if using legacy .env-only setup
   - Message: "⚠ Config file not found. Run: mcp-github-pr config init"

4. **GitHub Token Check** (Critical)
   - Verify token present in environment/config
   - Validate token format (ghp_*, gho_*, etc.)
   - Exit code: 1 if missing/invalid format
   - Message: "✗ GitHub token missing. Set GITHUB_TOKEN or run: mcp-github-pr config set github.token ghp_xxx"

5. **GitHub API Connectivity** (Critical, with timeout)
   - Perform GET /user with token
   - Timeout: 10 seconds
   - Handle responses:
     - 200: "✓ GitHub API accessible (user: username)"
     - 401: "✗ Token invalid (401 Unauthorized)"
     - 403: "✗ Token forbidden (403) - may be expired or revoked"
     - 404: "✗ API endpoint not found - check GH_HOST setting"
     - Timeout: "⚠ GitHub API slow (>10s) - network issues?"
     - 5xx: "⚠ GitHub API error (503) - try again later"

6. **Token Scopes Check** (Warning)
   - Parse X-OAuth-Scopes header from /user response
   - Required: `repo` (or `public_repo` for public-only)
   - Optional: `read:org` (for organization PRs)
   - Message: "✓ Token scopes: repo, read:org"
   - Warning: "⚠ Token missing 'repo' scope - PR fetching may fail"

7. **Rate Limit Check** (Info)
   - Display remaining rate limit from X-RateLimit-Remaining header
   - Warning if <100 remaining
   - Message: "✓ Rate limit: 4,823 / 5,000 remaining"
   - Warning: "⚠ Rate limit low: 42 / 5,000 remaining (resets at HH:MM)"

8. **Git Repository Detection** (Info, not critical)
   - Check if current directory is git repo
   - Required for `resolve_open_pr_url` tool
   - Message: "✓ Git repository detected"
   - Info: "ℹ Not in git repository - PR resolution will require explicit URLs"

9. **MCP Server Smoke Test** (Warning)
   - Attempt to import and validate server module
   - Check if server can initialize (don't start fully)
   - Message: "✓ MCP server module loads successfully"
   - Error: "✗ Server import failed: ModuleNotFoundError: httpx"

10. **Config Validation Summary** (Info)
    - Display effective configuration (with sources)
    - Show which values come from CLI/env/TOML/.env
    - Mask secrets
    - Example: "Config: github.api_url=https://api.github.com (TOML), github.token=ghp_abc...xyz (ENV)"

### Output Formats

#### Default (Human-Readable)
```
Running MCP GitHub PR Review health checks...

✓ Python 3.11.7
✓ uv 0.1.23
✓ Config file valid (/Users/user/.config/github-pr-review-mcp/config.toml)
✓ GitHub token present (ghp_abc...xyz)
✓ GitHub API accessible (user: octocat)
✓ Token scopes: repo, read:org
✓ Rate limit: 4,823 / 5,000 remaining
ℹ Not in git repository - PR resolution will require explicit URLs
✓ MCP server module loads successfully

All checks passed! ✓

Run the server: mcp-github-pr server run
```

#### JSON Output (`--json`)
```json
{
  "status": "success",
  "checks": [
    {"name": "python_version", "status": "pass", "version": "3.11.7"},
    {"name": "uv_binary", "status": "pass", "version": "0.1.23"},
    {"name": "config_file", "status": "pass", "path": "/Users/..."},
    {"name": "github_token", "status": "pass", "masked": "ghp_abc...xyz"},
    {"name": "github_api", "status": "pass", "user": "octocat", "duration_ms": 234},
    {"name": "token_scopes", "status": "pass", "scopes": ["repo", "read:org"]},
    {"name": "rate_limit", "status": "pass", "remaining": 4823, "limit": 5000},
    {"name": "git_repo", "status": "info", "detected": false},
    {"name": "server_module", "status": "pass"}
  ],
  "summary": {
    "passed": 8,
    "warnings": 0,
    "errors": 0,
    "info": 1
  }
}
```

#### CI Mode (`--ci`)
- Non-interactive
- Faster timeout (5s instead of 10s)
- Treat warnings as errors (exits 1)
- No color output
- Concise messages

### Exit Codes
- **0**: All critical checks passed (warnings allowed in default mode)
- **1**: One or more critical checks failed
- **2**: Invalid usage (bad flags, etc.)

### Implementation Notes
- Use `asyncio` for GitHub API calls (reuse existing httpx client setup)
- Progress indicator during network operations
- `--verbose` flag shows detailed information for each check
- `--check <name>` flag runs single check only (for debugging)
- Checks run in sequence, fail-fast on critical errors
- Results cached for 60 seconds (avoid redundant checks in quick succession)

## Risks & Mitigations

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| **Config migration errors** | High - Users lose settings or credentials | Medium | - Automatic timestamped backups before all migrations<br>- `config migrate --dry-run` to preview changes<br>- `config rollback` command for easy recovery<br>- Comprehensive validation before committing changes<br>- Clear migration logs showing what was changed |
| **Agent config auto-writing breaks** | High - Agent clients become unusable | Low (eliminated) | - **Design change**: Never auto-write to agent configs<br>- Generate snippets for users to copy<br>- Provide `agents verify` to test connectivity<br>- Clear documentation with examples |
| **MCP stdio protocol conflicts** | Critical - Server unusable | Low (eliminated) | - **Design change**: Always spawn server as subprocess<br>- Never run server in-process<br>- CLI output to stdout, server uses stdin/stdout<br>- Comprehensive integration tests |
| **Cross-platform filesystem quirks** | Medium - Commands fail on some OSes | Medium | - Dedicated `config/security.py` with per-OS helpers<br>- Parametrized pytest tests for Windows/macOS/Linux<br>- XDG_CONFIG_HOME and %APPDATA% support<br>- Platform-specific permission handling (0o600 vs ACL) |
| **Token exposure in logs/output** | Critical - Security breach | Medium | - Token masking in all output (`ghp_abc...xyz`)<br>- Never log full tokens<br>- Secure file permissions (0o600 on .env)<br>- Audit logging for config changes<br>- Security testing suite |
| **Config precedence confusion** | Medium - Users don't know which config applies | High | - Clear documentation with examples<br>- `config show` displays effective config with sources<br>- `doctor` command validates config<br>- Help text explains precedence |
| **Breaking changes for existing users** | High - Users unable to use new version | Medium | - Three-phase migration (introduce → promote → remove)<br>- Bash script works in version N+1<br>- Clear migration guide and tooling<br>- Backward compatibility warnings |
| **CI/CD pipeline disruption** | High - Automated workflows break | Medium | - Dedicated `docs/ci-migration.md`<br>- Examples for major CI platforms<br>- `--json` and `--quiet` flags for automation<br>- Exit codes consistent with Unix conventions<br>- Bash script continues working during N+1 |
| **Dependency footprint increase** | Low - Larger install size | High | - Make CLI dependencies optional via `[cli]` extras<br>- Server-only users: `uv sync` (no CLI deps)<br>- CLI users: `uv sync --extra cli`<br>- Document install options |
| **User adoption resistance** | Medium - Users stick with bash | High | - Emit clear deprecation warnings in bash script<br>- Superior UX in CLI (color, progress, help)<br>- Auto-complete support via `typer[all]`<br>- `quickstart` command reduces friction<br>- Clear "what's in it for me" messaging |
| **Windows-specific bugs** | Medium - CLI broken on Windows | Medium | - Windows-specific test suite<br>- Path handling with `pathlib.Path`<br>- ACL-based permission restrictions<br>- Test on Windows CI runners |
| **Incomplete migration** | Medium - Users partially migrate, confused state | Medium | - `doctor` command detects mixed state<br>- `config migrate` is atomic (all or nothing)<br>- Clear warnings if .env + no TOML found<br>- Migration completion checklist |

## Acceptance Criteria

### Core Functionality
- ✅ `mcp-github-pr --help` and all subcommands provide meaningful guidance including:
  - One-line description
  - Usage examples (not just synopsis)
  - Environment variable alternatives
  - Default values
  - Links to detailed documentation
- ✅ All commands exit with appropriate Unix-convention status codes (0=success, 1=error, 2=usage error)

### Configuration Management
- ✅ `mcp-github-pr quickstart` provides interactive first-time setup completing in <2 minutes
- ✅ `mcp-github-pr config init` creates both `config.toml` and `.env` with proper structure and permissions
- ✅ `mcp-github-pr config set` supports dotted paths (e.g., `github.token`) and validates values
- ✅ `mcp-github-pr config show` displays effective config with secrets masked and source annotations
- ✅ `mcp-github-pr config migrate` successfully migrates existing `.env` setups with automatic backup
- ✅ `mcp-github-pr config validate` performs real network checks:
  - Token format validation
  - GitHub API connectivity (with timeout)
  - Required scope verification (repo, read:org)
  - Surfaces actionable error messages with recovery steps
- ✅ Config precedence works correctly: CLI flags > env vars > TOML > .env (legacy)
- ✅ `.env` files created with secure permissions (0o600 on Unix, ACL on Windows)
- ✅ `.env` presence in `.gitignore` validated for git repositories

### Agent Integration
- ✅ `mcp-github-pr agents snippet <name>` generates syntactically valid configuration snippets for:
  - Claude CLI
  - Claude Desktop (macOS and Windows paths)
  - Codex CLI
  - Gemini
- ✅ `mcp-github-pr agents verify <name>` successfully tests agent connectivity
- ✅ `mcp-github-pr agents list` shows available agents with integration status
- ✅ **No automated writing** to agent config files (snippet-only approach)

### Server Management
- ✅ `mcp-github-pr server run` spawns MCP server as subprocess (never in-process):
  - Supports `--log`, `--no-sync`, `--follow` options
  - Can fully replace `./run-server.sh` in CI and README instructions
  - Properly handles stdin/stdout for MCP protocol
  - Returns appropriate exit codes
- ✅ `mcp-github-pr server debug` runs with verbose logging to stderr
- ✅ `mcp-github-pr server logs` tails previous server logs if `--log` was used

### Health Checks
- ✅ `mcp-github-pr doctor` performs comprehensive health checks:
  - ✓ Python version >= 3.10
  - ✓ uv binary available and version
  - ✓ GitHub token present and valid format
  - ✓ GitHub API connectivity
  - ✓ Token scopes (repo, read:org if needed)
  - ✓ Config file syntax and schema validity
  - ✓ MCP server smoke test (can start)
  - ✓ Git repository detection (for PR resolution)
- ✅ `doctor` provides clear ✓/✗/⚠ indicators and actionable next steps for failures
- ✅ `doctor --ci` and `doctor --json` modes work for automation

### Security
- ✅ Tokens are **never** exposed in full in any output (always masked: `ghp_abc...xyz`)
- ✅ Tokens are **never** stored in TOML files (only in `.env`)
- ✅ `.env` files have secure permissions set automatically
- ✅ Audit logging (optional) records config changes
- ✅ All security tests pass (token masking, file permissions, .gitignore validation)

### Migration & Backward Compatibility
- ✅ Bash script continues to work in current release
- ✅ Migration tooling (`config migrate`) successfully handles all legacy `.env` setups
- ✅ Automatic backups created before migration (timestamped)
- ✅ `config rollback` can restore from backups
- ✅ Mixed state (partial migration) detected and warned about by `doctor`

### Documentation
- ✅ New documentation files created:
  - `docs/cli.md` - Complete CLI reference
  - `docs/migration.md` - Migration guide
  - `docs/ci-migration.md` - CI/CD pipeline updates
  - `docs/quickstart.md` - New user onboarding
- ✅ Updated documentation:
  - `README.md` - CLI-first instructions with migration notice
  - `AGENTS.md` - Snippet-based integration steps
  - `CLAUDE.md` - Updated command references
  - `UV_COMMANDS.md` - CLI command examples
  - `SECURITY.md` - Config security and token storage practices
- ✅ All code examples in documentation are copy-pasteable and tested
- ✅ Bash script marked as deprecated with clear migration path

### Testing
- ✅ Comprehensive test suite covers:
  - All CLI commands (unit tests with `CliRunner`)
  - Integration flows (init → validate → run)
  - Cross-platform behavior (Windows/macOS/Linux)
  - Security (permissions, masking, .gitignore)
  - Migration scenarios (various legacy setups)
  - HTTP interactions (mocked with `pytest-httpx`)
  - Error cases with proper exit codes
- ✅ Test coverage >= 90% for CLI code
- ✅ All tests pass on Windows, macOS, and Linux

### User Experience
- ✅ First-time users can go from zero to working in <5 minutes using `quickstart`
- ✅ Error messages include context, root cause, and numbered recovery steps
- ✅ `--json` output available for all commands that benefit from machine parsing
- ✅ `--quiet` flag suppresses non-error output for scripting
- ✅ Rich output with color, progress bars, and status indicators (✓/✗/⚠)
- ✅ Shell completion available (via `typer[all]`)

### Performance
- ✅ Config operations (read/write) complete in <100ms
- ✅ `doctor` health checks complete in <5 seconds (with network)
- ✅ Help text displays instantly (<50ms)
- ✅ No performance regression for MCP server startup

