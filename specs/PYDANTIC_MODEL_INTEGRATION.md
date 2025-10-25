# Spec: Pydantic Modeling for GitHub PR Review MCP Server

## Background
- The server currently models GitHub review data with `TypedDict` aliases and ad-hoc dictionaries (`src/mcp_github_pr_review/server.py:125-144`).
- Tool inputs are validated by custom helper functions (`src/mcp_github_pr_review/server.py:928-1037`) producing repetitive range checks and manual error handling.
- GraphQL responses are flattened via nested `dict.get` lookups (`src/mcp_github_pr_review/server.py:400-420`), which makes it easy to miss shape changes from the API.
- Git context is represented as a plain dataclass without runtime validation (`src/mcp_github_pr_review/git_pr_resolver.py:20-25`).

## Goals
- Introduce Pydantic models to enforce structured data for GitHub comments, tool inputs, and git context.
- Centralize validation and coercion of numeric bounds and optional fields.
- Preserve the external behaviour of MCP tools (still returning JSON/markdown strings) while improving internal type safety.
- Keep compatibility with existing async flow and error handling.

## Non-Goals
- Changing the underlying HTTP retry/backoff logic.
- Replacing `argparse` in the CLI.
- Altering the MCP protocol surface area beyond stronger validation.

## Proposed Design

### 1. Domain Models for Comments
- Create `src/mcp_github_pr_review/models.py` with Pydantic `BaseModel` classes using `from __future__ import annotations` for forward references:
  - **`GitHubUserModel`**:
    - `login: str = Field(default="unknown", min_length=1)` - Always has a value, never empty
  - **`ReviewCommentModel`**:
    - `user: GitHubUserModel` - Nested model, validated recursively
    - `path: str = Field(min_length=1)` - File path, never empty
    - `line: int = Field(default=0, ge=0)` - Line number, defaults to 0 for file-level comments
    - `body: str` - Comment text, can be empty string
    - `diff_hunk: str = Field(default="")` - Diff context, defaults to empty if missing
    - `is_resolved: bool = False` - Resolution status
    - `is_outdated: bool = False` - Outdated flag
    - `resolved_by: str | None = None` - Resolver username if resolved
  - **`ErrorMessageModel`**:
    - `error: str = Field(min_length=1)` - Error description, never empty
  - **Conversion methods** (class methods on `ReviewCommentModel`):
    - `@classmethod from_rest(cls, data: dict[str, Any]) -> ReviewCommentModel` - Parses REST API responses
    - `@classmethod from_graphql(cls, node: dict[str, Any]) -> ReviewCommentModel` - Parses GraphQL node responses
    - Both methods use `model_validate` internally and handle missing/null fields via model defaults
- **Model Configuration**:
  - Enable `ConfigDict(extra="forbid")` to catch API schema changes
  - Use `ConfigDict(validate_assignment=True)` for runtime safety
- Replace the existing `TypedDict` definitions in `server.py` with imports from the new module. Keep the public return type as `list[dict[str, Any]]` by calling `.model_dump()` where we currently return dictionaries.

### 2. Structured Parsing for GraphQL and REST Responses
- Define lightweight Pydantic models mirroring the nested GraphQL response (thread, comment nodes, author). Use validators to normalise missing fields, handle `None` authors, and clamp lengths.
- Update `fetch_pr_comments_graphql` (`src/mcp_github_pr_review/server.py:261-420`) to:
  - Validate the raw JSON with the new models.
  - Convert each thread/comment node into `ReviewCommentModel` instances.
  - Honour `max_comments` by slicing the validated list before dumping to plain dicts.
- Update `fetch_pr_comments` (`src/mcp_github_pr_review/server.py:520-649`) to validate each REST comment via `ReviewCommentModel.from_rest` before appending.

### 3. Tool Argument Validation via Pydantic
- Introduce tool argument models in `models.py`:
  - **`FetchPRReviewCommentsArgs`**:
    - `pr_url: str | None = None` - Optional PR URL (can be auto-resolved)
    - `output: Literal["markdown", "json", "both"] = "markdown"` - Output format with explicit enum
    - `per_page: int | None = Field(default=None, ge=1, le=100)` - GitHub API page size
    - `max_pages: int | None = Field(default=None, ge=1, le=200)` - Server-capped pagination limit
    - `max_comments: int | None = Field(default=None, ge=100, le=100000)` - Server-capped total comment limit
    - `max_retries: int | None = Field(default=None, ge=0, le=10)` - Retry limit for transient errors
    - `owner: str | None = None` - Override repo owner
    - `repo: str | None = None` - Override repo name
    - `branch: str | None = None` - Override branch for PR resolution
    - `select_strategy: Literal["branch", "latest", "first", "error"] = "branch"` - PR selection strategy
    - **Custom validator**: `@field_validator` to ensure booleans are rejected for numeric fields (matching current `_validate_int` behavior)
  - **`ResolveOpenPrUrlArgs`**:
    - `host: str | None = None` - GitHub host (defaults to github.com)
    - `owner: str | None = None` - Override repo owner
    - `repo: str | None = None` - Override repo name
    - `branch: str | None = None` - Override branch
    - `select_strategy: Literal["branch", "latest", "first", "error"] = "branch"` - PR selection strategy
- **Error Handling Strategy**:
  - Wrap `model_validate(arguments)` in try/except within `handle_call_tool`
  - Catch `ValidationError` and transform to `ValueError` with user-friendly message formatting
  - Preserve existing error message patterns: `"Invalid type for {field}: expected integer"` and `"{field} must be between {min} and {max}"`
  - Example transformation: `ValidationError` with field context → `ValueError(f"Invalid type for {field_name}: expected {expected_type}")`
- Replace `_validate_int` helper function entirely with Pydantic field validation
- Use `model_dump(exclude_none=True)` to pass validated arguments to fetcher functions

### 4. Git Context Validation
- Replace the `GitContext` dataclass with a Pydantic `BaseModel` in `models.py`:
  - **`GitContextModel`**:
    - `host: str = Field(min_length=1)` - GitHub hostname, never empty
    - `owner: str = Field(min_length=1)` - Repository owner/org, never empty
    - `repo: str = Field(min_length=1)` - Repository name, never empty
    - `branch: str = Field(min_length=1)` - Branch name, never empty
    - **Validators**:
      - `@field_validator("host")` - Normalize to lowercase and strip whitespace
      - `@field_validator("owner", "repo", "branch")` - Strip leading/trailing whitespace
- Update `git_pr_resolver.py`:
  - Replace `@dataclass class GitContext` with import of `GitContextModel` from `models.py`
  - Update all function signatures and returns to use `GitContextModel`
  - Remove manual validation logic that's now handled by the model

### 5. Configuration Helpers
- **Decision**: Defer `BaseSettings` refactor to a separate PR to keep scope focused
- **Rationale**:
  - The current `_int_conf` and `_float_conf` helpers work well and don't involve data validation issues
  - `BaseSettings` would require additional Pydantic dependency setup and testing
  - Core models provide immediate value; configuration refactor is nice-to-have
- Keep existing environment variable loading pattern for now
- Document as future enhancement in a separate issue

### 6. Dependency & Packaging Updates
- Add `pydantic>=2.7,<3.0` to `pyproject.toml` dependencies
- Run `uv sync` to regenerate `uv.lock` with the new dependency
- **MyPy Configuration**:
  - Add `plugins = ["pydantic.mypy"]` to `[tool.mypy]` in `pyproject.toml`
  - Enable `warn_required_dynamic_aliases = true` for better type checking with Pydantic
  - Add Pydantic plugin settings:
    ```toml
    [tool.pydantic-mypy]
    init_forbid_extra = true
    init_typed = true
    warn_required_dynamic_aliases = true
    ```
- Use `from __future__ import annotations` at the top of `models.py` for forward references
- Ensure all model files use modern type hints (no `typing.List`, use `list` instead)

### 7. Performance Monitoring
- **Approach**: Add lightweight timing instrumentation without changing external behavior
- **Implementation**:
  - Add optional debug logging around model validation in `fetch_pr_comments` and `fetch_pr_comments_graphql`
  - Log validation time for comment batches when `DEBUG` env var is set
  - Example: `logger.debug(f"Validated {count} comments in {elapsed:.3f}s")`
- **Acceptance Criteria**:
  - Validation overhead should be <5% of total API fetch time for typical PRs (100-500 comments)
  - No measurable difference in end-to-end tool execution time for users
- **Testing**: Add a performance test that validates 1000 comment objects and asserts completion in <100ms on typical hardware

## Implementation Plan
1. Add the new `models.py` module with comment, error, tool argument, and git context models plus conversion helpers.
2. Update `server.py` to import the models, remove the old `TypedDict` definitions, and refactor `fetch_pr_comments_graphql`, `fetch_pr_comments`, and `generate_markdown` to operate on `ReviewCommentModel` / `ErrorMessageModel` before dumping to JSON/markdown.
3. Replace manual argument validation in `handle_call_tool` with Pydantic parsing and adjust error handling to keep existing ValueError semantics.
4. Swap the `GitContext` dataclass for the Pydantic model, updating `git_pr_resolver.py` accordingly and adjusting any tests relying on the dataclass.
5. Update tests to construct/compare against Pydantic outputs (use `.model_dump()` to keep existing assertions where convenient). Add targeted unit tests for the new models (e.g. ensuring defaults for missing `user.login`, range enforcement for arguments).
6. Update project dependencies and run the full quality gate (`uv run ruff format . && uv run ruff check --fix . && uv run mypy . && make compile-check && uv run pytest`).

## Testing Strategy

### Unit Tests for Models (`tests/test_models.py` - new file)
- **`GitHubUserModel`**:
  - Default "unknown" login when instantiated with no data
  - Rejects empty string login
  - Strips whitespace from login
- **`ReviewCommentModel`**:
  - Successfully parses REST API format via `from_rest()`
  - Successfully parses GraphQL node format via `from_graphql()`
  - Handles null/missing user gracefully (defaults to "unknown")
  - Handles missing optional fields (line, diff_hunk, resolved_by)
  - Rejects invalid field types (e.g., string for line number)
  - `.model_dump()` produces dict matching current `ReviewComment` TypedDict format
- **`ErrorMessageModel`**:
  - Rejects empty error string
  - Preserves error message content exactly
- **Tool Argument Models**:
  - `FetchPRReviewCommentsArgs` validates all numeric ranges (per_page 1-100, max_pages 1-200, etc.)
  - Rejects boolean values for numeric fields
  - Accepts None for optional fields
  - Validates output enum (markdown/json/both)
  - Validates select_strategy enum
- **`GitContextModel`**:
  - Rejects empty strings for all fields
  - Normalizes host to lowercase
  - Strips whitespace from all fields
  - Preserves field values after validation

### Integration Tests (extend existing)
- **`tests/test_integration.py`**:
  - Existing tests should pass without modification (models are internal)
  - Verify `.model_dump()` output matches expected dict structure
- **`tests/test_status_fields.py`**:
  - Update fixtures if they directly construct TypedDict instances
  - Verify status field handling remains unchanged

### Error Handling Tests (extend existing)
- **`tests/test_pagination_limits.py`**:
  - Verify ValidationError → ValueError transformation preserves existing error messages
  - Test boolean rejection for numeric fields (existing `_validate_int` behavior)
  - Test range validation error messages match current format

### Performance Tests (`tests/test_performance.py` - new file)
- Benchmark validation of 1000 comment objects (<100ms requirement)
- Compare validation overhead vs. mock HTTP request time
- Ensure <5% overhead for typical workloads

### Type Checking
- Run `uv run mypy .` and ensure no new errors
- Verify Pydantic plugin correctly infers model field types
- Check that fixtures don't rely on old dataclass signature

## Risks & Mitigations

### Validation Strictness
- **Risk**: Pydantic may reject data that previously passed silently (e.g., GitHub API returning unexpected null values)
- **Mitigation**:
  - Align field defaults with current fallback behavior (`line=0`, `login="unknown"`, `diff_hunk=""`)
  - Use `extra="forbid"` to catch schema changes early in development/testing
  - Add comprehensive test coverage for null/missing field scenarios
  - Document expected API contract in model docstrings

### Performance Overhead
- **Risk**: Model validation adds computational overhead that could slow down API-heavy operations
- **Mitigation**:
  - API call latency (100-1000ms) dominates over validation time (expected <1ms per comment)
  - Add performance tests to catch regressions (1000 comments in <100ms)
  - Use debug logging to measure actual overhead in integration tests
  - Keep models flat and avoid unnecessary nested validation

### Test Churn
- **Risk**: Existing test fixtures may break when switching from TypedDict to Pydantic models
- **Mitigation**:
  - Maintain backward-compatible return types (still return `list[dict[str, Any]]`)
  - Use `.model_dump()` to convert models back to dicts for existing assertions
  - Update fixtures incrementally, focusing on those that directly construct TypedDict instances
  - Add new model-specific tests separately from existing integration tests

### Breaking API Changes
- **Risk**: GitHub API schema changes could cause validation failures in production
- **Mitigation**:
  - Use optional fields with sensible defaults for non-critical data
  - Log validation errors at DEBUG level before raising
  - Consider adding a "lenient mode" env var for emergency fallback (future enhancement)
  - Monitor for ValidationError exceptions in production logs

### MyPy Configuration
- **Risk**: Pydantic plugin may conflict with existing mypy configuration or introduce new type errors
- **Mitigation**:
  - Add Pydantic plugin incrementally and test with `mypy .` after each change
  - Use `# type: ignore` comments sparingly and document reasoning
  - Ensure Python 3.10+ type hints are used consistently (no legacy `typing.List`)

## Resolved Decisions

### BaseSettings Refactor
- **Decision**: Defer to separate PR
- **Rationale**: Configuration loading works well currently; focus on data validation improvements first
- **Follow-up**: Create GitHub issue for future BaseSettings migration

### MCP Schema Export
- **Decision**: Keep models internal for now
- **Rationale**:
  - External API contract (JSON/markdown strings) remains unchanged
  - Exposing Pydantic models would create additional maintenance burden
  - MCP clients don't benefit from schema export currently
- **Future Consideration**: Re-evaluate if MCP protocol adds schema negotiation capabilities

