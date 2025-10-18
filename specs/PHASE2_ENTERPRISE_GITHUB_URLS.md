# Phase 2: Enterprise GitHub URL Support - Implementation Spec

## Overview

Enable enterprise GitHub support by leveraging existing URL construction utilities from `git_pr_resolver.py` and introducing environment variable configuration. This allows the MCP server to work with GitHub Enterprise Server (GHES) installations.

## Current State Analysis

### Existing Infrastructure (git_pr_resolver.py)

The codebase already contains robust enterprise GitHub URL handling:

- **`api_base_for_host(host: str)`** (line 109): Public function that constructs REST API base URLs
  - Returns `https://api.github.com` for github.com
  - Returns `https://{host}/api/v3` for enterprise
  - Respects `GITHUB_API_URL` environment variable override

- **`_graphql_url_for_host(host: str)`** (line 234): Private function that constructs GraphQL API URLs
  - Handles github.com → `https://api.github.com/graphql`
  - Handles enterprise → `https://{host}/api/graphql`
  - Respects `GITHUB_GRAPHQL_URL` environment variable override
  - Intelligently infers GraphQL URL from `GITHUB_API_URL` if set

### Current Hardcoded URLs (src/mcp_github_pr_review/server.py)

These need to be replaced with dynamic URL construction:

1. **GraphQL URL** (line 248):
   ```python
   response = await client.post(
       "https://api.github.com/graphql",  # ← Hardcoded
       headers=headers,
       json={"query": query, "variables": variables},
   )
   ```

2. **REST API URL** (lines 407-409):
   ```python
   base_url = (
       "https://api.github.com/repos/"  # ← Hardcoded
       f"{safe_owner}/{safe_repo}/pulls/{pull_number}/comments?per_page={per_page_v}"
   )
   ```

## Implementation Plan

### Step 1: Make GraphQL URL Helper Public

**File**: `git_pr_resolver.py`

**Change**: Rename `_graphql_url_for_host` → `graphql_url_for_host`

**Rationale**:
- This function is already well-tested through `resolve_pr_url()` usage
- Contains sophisticated logic for environment variable precedence
- Handles both github.com and enterprise cases correctly

**Code change** (line 234):
```python
# Before
def _graphql_url_for_host(host: str) -> str:

# After
def graphql_url_for_host(host: str) -> str:
```

**Update internal reference** (line 285):
```python
# Before
graphql_url = _graphql_url_for_host(host)

# After
graphql_url = graphql_url_for_host(host)
```

### Step 2: Import Enterprise URL Helpers in src/mcp_github_pr_review/server.py

**File**: `src/mcp_github_pr_review/server.py`

**Add to imports** (after line 23):
```python
from git_pr_resolver import (
    api_base_for_host,
    git_detect_repo_branch,
    graphql_url_for_host,
    resolve_pr_url,
)
```

**Note**: `git_detect_repo_branch` and `resolve_pr_url` are already imported (line 23), so we're just adding the URL helpers.

### Step 3: Extract Host from PR URL

**File**: `src/mcp_github_pr_review/server.py`

**Modify `get_pr_info()` function** (line 136):

Current signature:
```python
def get_pr_info(pr_url: str) -> tuple[str, str, str]:
```

New signature:
```python
def get_pr_info(pr_url: str) -> tuple[str, str, str, str]:
```

**Update pattern** (line 147):
```python
# Before
pattern = r"^https://github\.com/([^/]+)/([^/]+)/pull/(\d+)(?:[/?#].*)?$"

# After
pattern = r"^https://([^/]+)/([^/]+)/([^/]+)/pull/(\d+)(?:[/?#].*)?$"
```

**Update return** (line 156):
```python
# Before
owner, repo, num = groups[0], groups[1], groups[2]
return owner, repo, num

# After
host, owner, repo, num = groups[0], groups[1], groups[2], groups[3]
return host, owner, repo, num
```

**Update error message** (line 150):
```python
# Before
"Invalid PR URL format. Expected format: https://github.com/owner/repo/pull/123"

# After
"Invalid PR URL format. Expected format: https://{host}/owner/repo/pull/123"
```

### Step 4: Use Dynamic URLs in GraphQL Function

**File**: `src/mcp_github_pr_review/server.py`

**Update `fetch_pr_comments_graphql()` signature** (line 159):
```python
# Add host parameter
async def fetch_pr_comments_graphql(
    owner: str,
    repo: str,
    pull_number: int,
    *,
    host: str = "github.com",  # ← New parameter
    max_comments: int | None = None,
    max_retries: int | None = None,
) -> list[CommentResult] | None:
```

**Replace hardcoded GraphQL URL** (line 248):
```python
# Before
response = await client.post(
    "https://api.github.com/graphql",
    headers=headers,
    json={"query": query, "variables": variables},
)

# After
graphql_url = graphql_url_for_host(host)
response = await client.post(
    graphql_url,
    headers=headers,
    json={"query": query, "variables": variables},
)
```

### Step 5: Use Dynamic URLs in REST Function

**File**: `src/mcp_github_pr_review/server.py`

**Update `fetch_pr_comments()` signature** (line 357):
```python
# Add host parameter
async def fetch_pr_comments(
    owner: str,
    repo: str,
    pull_number: int,
    *,
    host: str = "github.com",  # ← New parameter
    per_page: int | None = None,
    max_pages: int | None = None,
    max_comments: int | None = None,
    max_retries: int | None = None,
) -> list[CommentResult] | None:
```

**Replace hardcoded REST URL** (lines 407-409):
```python
# Before
base_url = (
    "https://api.github.com/repos/"
    f"{safe_owner}/{safe_repo}/pulls/{pull_number}/comments?per_page={per_page_v}"
)

# After
api_base = api_base_for_host(host)
base_url = (
    f"{api_base}/repos/"
    f"{safe_owner}/{safe_repo}/pulls/{pull_number}/comments?per_page={per_page_v}"
)
```

### Step 6: Thread Host Through Call Chain

**File**: `src/mcp_github_pr_review/server.py`

**Update `fetch_pr_review_comments()` method** (line 996):
```python
# Extract host from URL
owner, repo, pull_number_str = get_pr_info(pr_url)
# ↓ Change to extract host
host, owner, repo, pull_number_str = get_pr_info(pr_url)
pull_number = int(pull_number_str)

# Pass host to GraphQL function
comments = await fetch_pr_comments_graphql(
    owner,
    repo,
    pull_number,
    host=host,  # ← New parameter
    max_comments=max_comments,
    max_retries=max_retries,
)
```

### Step 7: Update .env.example

**File**: `.env.example`

**Add after GITHUB_TOKEN section** (after line 6):
```bash
# GitHub API base URLs (optional, defaults based on GH_HOST)
# GITHUB_API_URL=https://api.github.com
# GITHUB_GRAPHQL_URL=https://api.github.com/graphql

# GitHub host (default: github.com)
# For github.com (default):
# GH_HOST=github.com

# For GitHub Enterprise Server:
# GH_HOST=github.enterprise.com
# GITHUB_API_URL=https://github.enterprise.com/api/v3
# GITHUB_GRAPHQL_URL=https://github.enterprise.com/api/graphql
```

## Testing Strategy

### Unit Tests (New File: tests/test_enterprise_url_support.py)

**Test Coverage**:

1. **`test_graphql_url_for_host_is_public`**
   - Verify function can be imported from `git_pr_resolver`
   - Verify it's not prefixed with underscore

2. **`test_get_pr_info_returns_host`**
   - Test github.com URL: `https://github.com/owner/repo/pull/123`
   - Test enterprise URL: `https://github.enterprise.com/owner/repo/pull/456`
   - Verify returns 4-tuple: `(host, owner, repo, number)`

3. **`test_get_pr_info_enterprise_with_query_params`**
   - Test `https://github.enterprise.com/owner/repo/pull/789?diff=split`
   - Verify host extraction works with query parameters

4. **`test_fetch_pr_comments_graphql_uses_enterprise_url`**
   - Mock httpx client
   - Call with `host="github.enterprise.com"`
   - Verify POST request goes to `https://github.enterprise.com/api/graphql`

5. **`test_fetch_pr_comments_rest_uses_enterprise_url`**
   - Mock httpx client
   - Call with `host="github.enterprise.com"`
   - Verify GET request goes to `https://github.enterprise.com/api/v3/repos/...`

6. **`test_fetch_pr_comments_graphql_respects_env_override`**
   - Set `GITHUB_GRAPHQL_URL=https://custom.api/graphql`
   - Call with `host="github.com"`
   - Verify uses custom URL from environment

7. **`test_fetch_pr_comments_rest_respects_env_override`**
   - Set `GITHUB_API_URL=https://custom.api`
   - Call with `host="github.com"`
   - Verify uses custom URL from environment

8. **`test_get_pr_info_invalid_url_format`**
   - Test malformed URLs raise ValueError
   - Verify error message is helpful

### Integration Tests (Update: tests/test_integration.py)

**Add tests**:

1. **`test_end_to_end_enterprise_pr_url`**
   - Mock GitHub Enterprise API responses
   - Provide enterprise PR URL
   - Verify full fetch flow uses correct URLs

2. **`test_server_tool_with_enterprise_pr_url`**
   - Test MCP tool invocation with enterprise URL
   - Verify markdown generation works

### Regression Tests

**Update existing tests**:

1. **`tests/test_git_pr_resolver.py`**
   - Rename `_graphql_url_for_host` → `graphql_url_for_host` in tests
   - Add test for public API availability

2. **`tests/test_integration.py`**
   - Update `get_pr_info()` call sites to handle 4-tuple return
   - Verify github.com still works (regression protection)

3. **`tests/test_rest_error_handling.py`**
   - May need minor updates if function signatures changed

## Documentation Updates

### README.md

Add section after "Installation":

```markdown
## Enterprise GitHub Support

This MCP server supports both GitHub.com and GitHub Enterprise Server (GHES).

### Configuration

**For GitHub.com (default)**:
```bash
GITHUB_TOKEN=ghp_your_token_here
```

**For GitHub Enterprise Server**:
```bash
GH_HOST=github.enterprise.com
GITHUB_TOKEN=your_enterprise_token
```

The server automatically constructs API endpoints based on `GH_HOST`:
- REST API: `https://{GH_HOST}/api/v3`
- GraphQL API: `https://{GH_HOST}/api/graphql`

**Advanced: Custom API URLs**

For non-standard enterprise configurations:
```bash
GITHUB_API_URL=https://custom.github.company.com/api
GITHUB_GRAPHQL_URL=https://custom.github.company.com/graphql
```

### URL Format

The server accepts PR URLs in this format:
```
https://{host}/owner/repo/pull/123
```

Examples:
- `https://github.com/owner/repo/pull/123` (GitHub.com)
- `https://github.enterprise.com/owner/repo/pull/456` (GHES)
```

### CLAUDE.md

Update "Environment Configuration" section:

```markdown
**Enterprise GitHub Variables**:
- `GH_HOST` (default "github.com"): GitHub hostname for enterprise installations
- `GITHUB_API_URL` (optional): Explicit REST API base URL override
- `GITHUB_GRAPHQL_URL` (optional): Explicit GraphQL API URL override
```

## Backward Compatibility

✅ **Zero Breaking Changes**:
- All new parameters have defaults (`host="github.com"`)
- Existing github.com users require no configuration changes
- Environment variables are optional
- URL helpers use smart defaults

## Success Criteria

- [ ] All existing tests pass without modification
- [ ] New tests cover enterprise URL construction
- [ ] `get_pr_info()` correctly extracts host from URLs
- [ ] GraphQL calls use `graphql_url_for_host()`
- [ ] REST calls use `api_base_for_host()`
- [ ] Environment variable overrides work correctly
- [ ] Documentation explains enterprise usage
- [ ] Pre-commit checks pass: `uv run ruff format . && uv run ruff check --fix . && uv run mypy . && make compile-check && uv run pytest`

## Risk Assessment

**Risk Level**: Low-Medium

**Mitigation**:
- Reusing battle-tested functions from `git_pr_resolver.py`
- Comprehensive test coverage for new behavior
- Defaults ensure backward compatibility
- Gradual rollout via feature branch

## Estimated Implementation Time

- Code changes: 2 hours
- Test development: 2 hours
- Documentation: 30 minutes
- Testing and validation: 30 minutes
- **Total**: 5 hours

## Implementation Order

1. ✅ Create feature branch
2. ✅ Create spec file (this document)
3. Make `_graphql_url_for_host` public
4. Update imports in `src/mcp_github_pr_review/server.py`
5. Modify `get_pr_info()` to extract host
6. Update `fetch_pr_comments_graphql()` to use dynamic URL
7. Update `fetch_pr_comments()` to use dynamic URL
8. Thread host parameter through call chain
9. Write unit tests
10. Update integration tests
11. Update documentation
12. Run full test suite
13. Manual validation with mock enterprise URLs
14. Create commit with descriptive message
15. Open PR for review

## Commit Message

```
feat(api): add enterprise GitHub support via env vars

Enable GitHub Enterprise Server (GHES) support by leveraging existing
URL construction utilities from git_pr_resolver.py. The server now
dynamically constructs API endpoints based on GH_HOST or explicit URL
overrides.

Changes:
- Make graphql_url_for_host() public in git_pr_resolver.py
- Update get_pr_info() to extract host from PR URLs
- Thread host parameter through API call chain
- Add GITHUB_API_URL and GITHUB_GRAPHQL_URL env var support
- Add comprehensive tests for enterprise URL construction
- Document enterprise GitHub configuration

Backward compatible: All changes use smart defaults for github.com.

Addresses issue #35 Phase 2
```
