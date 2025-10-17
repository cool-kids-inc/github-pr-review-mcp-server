# GitHub API Robustness Implementation Specification

## Overview

This specification outlines the implementation plan for hardening GitHub API interactions in the MCP PR Review server. The improvements address modern API standards, enterprise GitHub support, sophisticated rate limiting, and enhanced retry strategies.

## Branch Strategy

**Feature branch**: `feature/github-api-robustness`

**Development approach**: Phased implementation with 5 distinct commits, each independently testable and valuable.

## Implementation Phases

### Phase 1: Modern Header Standardization

**Objective**: Update all GitHub API calls to use modern, versioned headers.

**Files Modified**:
- `src/mcp_github_pr_review/server.py`
- `git_pr_resolver.py`

**Changes**:

1. **REST API Headers** (both files):
   - Change: `Accept: application/vnd.github.v3+json` → `Accept: application/vnd.github+json`
   - Add: `X-GitHub-Api-Version: 2022-11-28`
   - Location in `src/mcp_github_pr_review/server.py`: Lines 380-386
   - Location in `git_pr_resolver.py`: Lines 137-138

2. **GraphQL API Headers** (both files):
   - Add: `Accept: application/vnd.github+json` (currently missing)
   - Add: `X-GitHub-Api-Version: 2022-11-28`
   - Location in `src/mcp_github_pr_review/server.py`: Lines 172-176
   - Location in `git_pr_resolver.py`: GraphQL header construction

3. **User-Agent Consistency**:
   - Maintain: `User-Agent: mcp-pr-review-spec-maker/1.0`
   - Ensure present in all API calls

**Rationale**:
- `application/vnd.github.v3+json` is deprecated by GitHub
- `X-GitHub-Api-Version: 2022-11-28` enables API versioning for stability
- GraphQL should include Accept header for consistency
- Prevents future breaking changes from GitHub API evolution

**Risk Assessment**: Low risk, high value. GitHub supports both header formats during transition period.

**Testing Requirements**:
- Validate headers present in all REST API calls
- Validate headers present in all GraphQL API calls
- Ensure existing tests pass with new headers
- Add header validation to test fixtures

---

### Phase 2: URL Environment Variable Support

**Objective**: Enable enterprise GitHub support through environment variable configuration.

**Files Modified**:
- `src/mcp_github_pr_review/server.py`
- `git_pr_resolver.py`
- `.env.example`

**New Environment Variables**:

```bash
# GitHub API base URLs (optional, defaults based on GH_HOST)
GITHUB_API_URL=https://api.github.com
GITHUB_GRAPHQL_URL=https://api.github.com/graphql

# For GitHub Enterprise Server
GH_HOST=github.com  # Default: github.com

# Example enterprise configuration:
# GH_HOST=github.company.com
# GITHUB_API_URL=https://github.company.com/api/v3
# GITHUB_GRAPHQL_URL=https://github.company.com/api/graphql
```

**Implementation Details**:

1. **Export existing functions from `git_pr_resolver.py`**:
   - Make `_api_base_for_host(host: str) -> str` public
   - Make `_graphql_url_for_host(host: str) -> str` public
   - These already handle enterprise GitHub URL construction

2. **Update `src/mcp_github_pr_review/server.py` URL construction**:
   - Line 241: Change hardcoded `https://api.github.com/graphql` to use `_graphql_url_for_host()`
   - Lines 400-402: Change hardcoded REST base URL to use `_api_base_for_host()`

3. **Environment variable precedence**:
   ```python
   GH_HOST = os.getenv("GH_HOST", "github.com")
   GITHUB_API_URL = os.getenv("GITHUB_API_URL") or _api_base_for_host(GH_HOST)
   GITHUB_GRAPHQL_URL = os.getenv("GITHUB_GRAPHQL_URL") or _graphql_url_for_host(GH_HOST)
   ```

**Rationale**:
- Existing enterprise logic in `git_pr_resolver.py` not used by `src/mcp_github_pr_review/server.py`
- Hardcoded URLs prevent enterprise GitHub customers from using the tool
- Smart defaults maintain backward compatibility
- Explicit overrides support edge cases

**Risk Assessment**: Medium complexity. Requires careful testing of URL construction logic.

**Testing Requirements**:
- Test default URL construction (github.com)
- Test enterprise URL construction from GH_HOST
- Test explicit GITHUB_API_URL override
- Test explicit GITHUB_GRAPHQL_URL override
- Validate URL encoding for owner/repo parameters

---

### Phase 3: Enhanced Rate Limit Handling

**Objective**: Differentiate between primary and secondary (abuse detection) rate limits for appropriate handling.

**Files Modified**:
- `src/mcp_github_pr_review/server.py`
- `git_pr_resolver.py`

**New Helper Functions**:

```python
def _is_secondary_rate_limit(response: httpx.Response) -> bool:
    """Detect GitHub secondary/abuse rate limits vs primary limits.

    Args:
        response: HTTP response from GitHub API

    Returns:
        True if response indicates secondary rate limit, False otherwise
    """
    if response.status_code not in (403, 429):
        return False
    try:
        body = response.json()
        message = body.get("message", "").lower()
        # GitHub's actual error messages for secondary limits
        return any(indicator in message for indicator in [
            "secondary rate limit",
            "abuse detection",
            "exceeded a secondary rate limit"
        ])
    except (json.JSONDecodeError, KeyError, AttributeError):
        return False

def _log_request_id(response: httpx.Response, context: str) -> None:
    """Log GitHub request ID for debugging/support tickets.

    Args:
        response: HTTP response from GitHub API
        context: Contextual description of the request
    """
    request_id = response.headers.get("X-GitHub-Request-Id")
    if request_id:
        print(f"GitHub Request ID ({context}): {request_id}", file=sys.stderr)
```

**Rate Limit Handling Logic**:

1. **Secondary Rate Limit Handling**:
   - Detection: Parse response JSON for abuse detection messages
   - Action: Fixed 60-second wait + single retry (not indefinite)
   - Logging: Log request ID for GitHub support tickets
   - Location: `src/mcp_github_pr_review/server.py` lines 458-481 (existing rate limit handling)

2. **Primary Rate Limit Handling**:
   - Detection: `X-RateLimit-Remaining: 0` or standard 403/429
   - Action: Use `Retry-After` or `X-RateLimit-Reset` headers
   - Behavior: Existing logic (already correct)

3. **GraphQL Rate Limit Handling**:
   - Location: `src/mcp_github_pr_review/server.py` lines 260-279
   - Currently missing: Add rate limit detection and handling
   - Apply same logic as REST API

**Implementation Steps**:

1. Add `_is_secondary_rate_limit()` helper function
2. Add `_log_request_id()` helper function
3. Update rate limit handling in REST retry loop:
   ```python
   if response.status_code in (403, 429):
       _log_request_id(response, "rate_limit_check")
       if _is_secondary_rate_limit(response):
           print("Secondary rate limit detected. Waiting 60s...", file=sys.stderr)
           await asyncio.sleep(60)
           # Only retry once for secondary limits
           if secondary_retry_count >= 1:
               return None
           secondary_retry_count += 1
           continue
       else:
           # Existing primary rate limit handling
           retry_after = response.headers.get("Retry-After")
           # ... existing logic ...
   ```
4. Add rate limit handling to GraphQL retry loop (currently missing)

**Rationale**:
- GitHub has two distinct rate limiting mechanisms
- Secondary (abuse) limits require longer, fixed backoff
- Indefinite retries on abuse limits can lead to temporary IP blocks
- Request ID logging aids debugging and support escalation

**Risk Assessment**: Medium complexity, high value. Critical for avoiding GitHub abuse detection penalties.

**Testing Requirements**:
- Mock secondary rate limit response with abuse message
- Mock primary rate limit response with Retry-After header
- Verify 60s wait for secondary limits
- Verify single retry attempt for secondary limits
- Verify existing behavior for primary limits
- Test request ID logging

---

### Phase 4: Extended 5xx Retry Strategy

**Objective**: Increase retry backoff ceiling to handle GitHub infrastructure issues more gracefully.

**Files Modified**:
- `src/mcp_github_pr_review/server.py`
- `git_pr_resolver.py`

**Changes**:

1. **Increase backoff ceiling**:
   - Current: `min(5.0, backoff)`
   - New: `min(15.0, backoff)`
   - Location in `src/mcp_github_pr_review/server.py`: Line 488
   - Location in `git_pr_resolver.py`: Similar 5xx retry logic

2. **Maintain existing formula**:
   - Keep: `(0.5 * 2^attempt) + random.uniform(0, 0.25)`
   - Keep: Exponential backoff with jitter
   - Keep: `max_retries` configuration parameter

**Before**:
```python
delay = min(
    5.0,
    (0.5 * (2**attempt)) + random.uniform(0, 0.25),
)
```

**After**:
```python
delay = min(
    15.0,
    (0.5 * (2**attempt)) + random.uniform(0, 0.25),
)
```

**Rationale**:
- 5-second ceiling insufficient for GitHub infrastructure incidents
- GitHub recommends up to 15 seconds for 5xx errors
- Larger backoff reduces load during platform issues
- Improves success rate for transient failures

**Risk Assessment**: Low complexity, high reliability improvement. Only affects error cases.

**Testing Requirements**:
- Verify backoff calculation with new ceiling
- Ensure retry count still respected
- Test with mocked 500, 502, 503, 504 responses
- Validate exponential backoff progression

---

### Phase 5: Testing & Documentation

**Objective**: Comprehensive test coverage and user documentation for all changes.

**Files Created/Modified**:
- `tests/test_rest_error_handling.py` (update)
- `tests/test_github_api_config.py` (new)
- `tests/conftest.py` (update)
- `.env.example` (update)
- `README.md` (update)
- `CLAUDE.md` (update)

**Testing Requirements**:

1. **New Test Cases**:
   - Secondary rate limit detection with various abuse messages
   - Primary rate limit handling (ensure no regression)
   - Enterprise GitHub URL construction
   - Environment variable precedence
   - Header validation (REST + GraphQL)
   - Extended 5xx backoff ceiling
   - Request ID logging

2. **Test File: `tests/test_github_api_config.py`** (new):
   ```python
   # Test header construction
   # Test URL building for github.com
   # Test URL building for enterprise GitHub
   # Test environment variable overrides
   # Test secondary rate limit detection
   # Test request ID logging
   ```

3. **Update Test Fixtures** (`tests/conftest.py`):
   - Add `X-GitHub-Api-Version` to header validation
   - Add mock responses for secondary rate limits
   - Add enterprise GitHub URL fixtures

4. **Update Existing Tests** (`tests/test_rest_error_handling.py`):
   - Add secondary rate limit scenarios
   - Validate new header presence
   - Test 15s backoff ceiling

**Documentation Updates**:

1. **`.env.example`**:
   ```bash
   # GitHub token for accessing private repositories
   GITHUB_TOKEN=your_github_token_here

   # GitHub API base URLs (optional, defaults based on GH_HOST)
   # GITHUB_API_URL=https://api.github.com
   # GITHUB_GRAPHQL_URL=https://api.github.com/graphql

   # GitHub host (default: github.com)
   # GH_HOST=github.com

   # For GitHub Enterprise Server:
   # GH_HOST=github.company.com
   # GITHUB_API_URL=https://github.company.com/api/v3
   # GITHUB_GRAPHQL_URL=https://github.company.com/api/graphql

   # Optional safety/performance settings
   # (existing configuration...)
   ```

2. **`README.md`**:
   - Add "Enterprise GitHub Support" section
   - Document new environment variables
   - Explain rate limiting behavior
   - Add troubleshooting tips for secondary limits

3. **`CLAUDE.md`**:
   - Update "Architecture Overview" with new helper functions
   - Update "Environment Configuration" section
   - Document rate limiting strategy
   - Note enterprise GitHub support

**Documentation Sections**:

```markdown
## Enterprise GitHub Support

This MCP server supports both GitHub.com and GitHub Enterprise Server (GHES).

### Configuration

For GitHub.com (default):
- No configuration needed
- Uses `https://api.github.com` by default

For GitHub Enterprise Server:
1. Set `GH_HOST` to your enterprise GitHub hostname
2. Optionally override API URLs with `GITHUB_API_URL` and `GITHUB_GRAPHQL_URL`

Example `.env`:
```bash
GH_HOST=github.company.com
GITHUB_TOKEN=your_enterprise_token
```

The server automatically constructs appropriate API endpoints:
- REST API: `https://github.company.com/api/v3`
- GraphQL API: `https://github.company.com/api/graphql`

### Rate Limiting

The server handles two types of GitHub rate limits:

1. **Primary Rate Limits**: 5000 requests/hour (authenticated)
   - Detection: `X-RateLimit-Remaining: 0`
   - Behavior: Wait based on `Retry-After` or `X-RateLimit-Reset` headers

2. **Secondary Rate Limits** (Abuse Detection): Triggered by rapid requests
   - Detection: Response body contains "secondary rate limit" or "abuse detection"
   - Behavior: Fixed 60-second wait, single retry attempt
   - Prevention: Avoid concurrent requests, respect pagination limits

All rate limit events include `X-GitHub-Request-Id` in logs for support tickets.
```

**Rationale**:
- Comprehensive testing prevents regressions
- Documentation enables enterprise adoption
- Clear rate limiting explanation helps users troubleshoot

**Risk Assessment**: Essential for quality and adoption. No deployment risk.

**Validation Checklist**:
- [ ] All existing tests pass
- [ ] New test coverage ≥90% for new code
- [ ] Headers validated in all code paths
- [ ] Enterprise GitHub URL construction tested
- [ ] Secondary rate limit detection tested
- [ ] Documentation reviewed for accuracy
- [ ] Pre-commit checks pass: `uv run ruff format . && uv run ruff check --fix . && uv run mypy . && make compile-check && uv run pytest`

---

## Implementation Timeline

| Phase | Estimated Time | Complexity | Value |
|-------|---------------|------------|-------|
| Phase 1: Headers | 1-2 hours | Low | High |
| Phase 2: URLs | 2-3 hours | Medium | High |
| Phase 3: Rate Limits | 3-4 hours | Medium | Critical |
| Phase 4: Retry Strategy | 1 hour | Low | High |
| Phase 5: Testing & Docs | 2-3 hours | Medium | Essential |
| **Total** | **10-13 hours** | - | - |

## Commit Strategy

Each phase should be a separate commit for easy review and potential rollback:

1. `feat(api): modernize GitHub API headers for stability`
2. `feat(api): add enterprise GitHub support via env vars`
3. `feat(api): implement secondary rate limit detection`
4. `feat(api): extend 5xx retry backoff to 15s`
5. `test(api): comprehensive coverage for API robustness`

## Key Technical Decisions

1. **Reuse existing utilities**: Export and leverage `_api_base_for_host()` and `_graphql_url_for_host()` from `git_pr_resolver.py`
2. **Helper functions**: Create `_is_secondary_rate_limit()` and `_log_request_id()` for clarity and testability
3. **Environment variables**: Optional with intelligent defaults (GH_HOST-based) for backward compatibility
4. **Retry structure**: Maintain existing patterns, only adjust parameters
5. **Phased development**: Each phase independently testable and valuable

## Backward Compatibility

All changes maintain backward compatibility:
- New environment variables are optional
- Default behavior unchanged for GitHub.com users
- Existing retry logic preserved (only parameters adjusted)
- Header changes supported by GitHub during transition period

## Success Criteria

- [ ] All tests pass (existing + new)
- [ ] Code coverage maintained or improved
- [ ] Pre-commit hooks pass
- [ ] Documentation complete and accurate
- [ ] Tested against both GitHub.com and enterprise GitHub (if available)
- [ ] No breaking changes for existing users
- [ ] Rate limiting correctly differentiates primary vs secondary
- [ ] Headers include modern versioning

## Additional Opportunities (Future Work)

Lower priority improvements identified during analysis:

1. **ETag/conditional request support**: Save API quota with `If-None-Match` headers
2. **GraphQL query complexity tracking**: Monitor and optimize query costs
3. **Circuit breaker pattern**: Pause API calls after repeated failures
4. **Multi-token rotation**: Support multiple tokens for higher rate limits
5. **Response validation**: Validate JSON structure before parsing
6. **GraphQL persisted queries**: Reduce bandwidth for repeated queries

These can be considered for future iterations after core robustness improvements are complete.

## References

- [GitHub REST API Documentation](https://docs.github.com/en/rest)
- [GitHub GraphQL API Documentation](https://docs.github.com/en/graphql)
- [GitHub API Versioning](https://docs.github.com/en/rest/overview/api-versions)
- [GitHub Rate Limiting](https://docs.github.com/en/rest/overview/rate-limits-for-the-rest-api)
- [GitHub Secondary Rate Limits](https://docs.github.com/en/rest/overview/rate-limits-for-the-rest-api#about-secondary-rate-limits)
- [GitHub Enterprise Server API](https://docs.github.com/en/enterprise-server@latest/rest)
