# Pydantic BaseSettings Migration Implementation Plan

## Status: In Progress

Related Issue: #45

## Overview

Migrating from custom helper functions (`_int_conf`, `_float_conf`) to Pydantic `BaseSettings` for unified configuration management.

## Progress

### ✅ Completed

1. **Dependency Management**
   - Added `pydantic-settings>=2.0.0` to `pyproject.toml`
   - Verified pydantic-settings v2.10.1 is installed

2. **Config Module Created** (`src/mcp_github_pr_review/config.py`)
   - Created `ServerSettings` class with all configuration fields
   - Implemented custom validators for clamping behavior (preserves backward compatibility)
   - Added `with_overrides()` method for function parameter overrides
   - Added `get_settings()` singleton pattern
   - Full type safety with Pydantic Field constraints

3. **Configuration Fields Implemented**
   - `github_token`: GitHub PAT (required)
   - `gh_host`: GitHub hostname (default: "github.com")
   - `github_api_url`: REST API URL override (optional)
   - `github_graphql_url`: GraphQL API URL override (optional)
   - `http_per_page`: Per page (default: 100, range: 1-100)
   - `pr_fetch_max_pages`: Max pages (default: 50, range: 1-200)
   - `pr_fetch_max_comments`: Max comments (default: 2000, range: 100-100000)
   - `http_max_retries`: Max retries (default: 3, range: 0-10)
   - `http_timeout`: Total timeout (default: 30.0, range: 1.0-300.0)
   - `http_connect_timeout`: Connect timeout (default: 10.0, range: 1.0-60.0)

### 🚧 In Progress

1. **Server.py Integration**
   - Import added: `from .config import ServerSettings, get_settings`
   - Need to replace `_int_conf` and `_float_conf` calls

### ⏳ Remaining Tasks

1. **Update server.py** (2-3 hours)
   - Replace all `_int_conf()` calls with settings access
   - Replace all `_float_conf()` calls with settings access
   - Update `fetch_pr_comments_graphql()` function
   - Update `fetch_pr_comments()` function
   - Keep old functions temporarily for gradual migration

2. **Update Tests** (3-4 hours)
   - Update `tests/test_config_helpers.py` to test ServerSettings
   - Update `tests/test_config_edge_cases.py` for new config
   - Create `tests/test_server_settings.py` for comprehensive settings tests
   - Update tests that import or mock `_int_conf`/`_float_conf`

3. **Documentation Updates** (1 hour)
   - Update CLAUDE.md with new configuration approach
   - Update README.md if it mentions configuration
   - Add docstrings and examples for ServerSettings usage

4. **Cleanup** (30 minutes)
   - Remove old `_int_conf` and `_float_conf` functions
   - Remove old constants (PER_PAGE_MIN, etc.) if no longer needed
   - Run full quality check pipeline

5. **Integration Testing** (1 hour)
   - Test with various .env configurations
   - Test override mechanisms
   - Test clamping behavior
   - Test with missing/invalid values

## Implementation Strategy

### Phase 1: Parallel Implementation (Current)
- New config module exists alongside old helpers
- Both systems work independently
- Allows gradual migration with testing at each step

### Phase 2: Migration
```python
# OLD CODE (before)
max_comments_v = _int_conf("PR_FETCH_MAX_COMMENTS", 2000, 100, 100000, max_comments)
max_retries_v = _int_conf("HTTP_MAX_RETRIES", 3, 0, 10, max_retries)

# NEW CODE (after)
settings = get_settings().with_overrides(
    max_comments=max_comments,
    max_retries=max_retries
)
max_comments_v = settings.pr_fetch_max_comments
max_retries_v = settings.http_max_retries
```

### Phase 3: Cleanup
- Remove old helper functions
- Remove old test files or update them
- Final documentation pass

## Key Design Decisions

### 1. Clamping vs Validation Errors
**Decision**: Preserve clamping behavior (no validation errors)

**Rationale**:
- Maintains backward compatibility
- Existing .env files won't break
- Operator-friendly (fix values instead of crashing)

**Implementation**: Custom `field_validator` with `mode="before"` that clamps before Pydantic validation

### 2. Override Mechanism
**Decision**: Provide `with_overrides()` method

**Rationale**:
- Functions accept optional parameters that override env vars
- Need to preserve this API for backward compatibility
- `model_copy(update=...)` provides clean Pydantic way to do this

### 3. Singleton Pattern
**Decision**: Use module-level `get_settings()` function

**Rationale**:
- Settings are expensive to load (env parsing, validation)
- Should load once per process
- Easy to override in tests with monkeypatch

## Testing Strategy

### Unit Tests
- Test each field loads from env correctly
- Test clamping behavior for out-of-range values
- Test invalid values return defaults
- Test override mechanism works
- Test missing env vars use defaults

### Integration Tests
- Test with real .env files
- Test both functions (GraphQL and REST) with new settings
- Test that behavior matches old implementation exactly

### Backward Compatibility Tests
- Run full existing test suite
- All tests should pass without modification (except config test updates)
- No behavior changes for end users

## Migration Checklist

- [x] Add pydantic-settings dependency
- [x] Create ServerSettings class
- [x] Implement clamping validators
- [x] Implement override mechanism
- [x] Add get_settings() singleton
- [ ] Update fetch_pr_comments_graphql()
- [ ] Update fetch_pr_comments()
- [ ] Update test_config_helpers.py
- [ ] Update test_config_edge_cases.py
- [ ] Create test_server_settings.py
- [ ] Update any tests that mock config functions
- [ ] Update CLAUDE.md
- [ ] Update README.md (if needed)
- [ ] Remove old helper functions
- [ ] Remove old constants (if not needed)
- [ ] Run full quality check
- [ ] Manual testing with various configs

## Estimated Time Remaining

- Implementation: 6-8 hours
- Testing: 2-3 hours
- Documentation: 1 hour
- **Total**: 9-12 hours of focused work

## Benefits After Migration

1. **Unified Validation**: All config in one place with consistent validation
2. **Type Safety**: Full Pydantic type checking and IDE support
3. **Auto-Documentation**: Settings are self-documenting with Field descriptions
4. **Better Testing**: Easy to mock and override in tests
5. **IDE Support**: Auto-complete for all settings fields
6. **Nested Config**: Future support for complex nested configurations
7. **Consistent Patterns**: Aligns with modern Python best practices

## Risks and Mitigations

### Risk: Breaking Changes
**Mitigation**: Extensive backward compatibility testing, parallel implementation period

### Risk: Test Failures
**Mitigation**: Update tests incrementally, maintain old tests during migration

### Risk: Performance Impact
**Mitigation**: Singleton pattern prevents repeated parsing, lazy loading

### Risk: Unclear Behavior Change
**Mitigation**: Comprehensive documentation, migration guide for contributors

## Next Steps

1. Complete server.py updates (replace all config function calls)
2. Run existing tests to identify failures
3. Update failing tests one by one
4. Add new comprehensive settings tests
5. Update documentation
6. Final cleanup and quality checks

## Notes for Reviewers

- This is a large refactor but maintains 100% backward compatibility
- No user-facing behavior changes
- All existing .env files will continue to work
- Clamping behavior is preserved (no validation errors on out-of-range)
- Override mechanism is preserved via `with_overrides()` method
