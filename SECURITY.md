# Security Considerations

This document outlines the security design decisions, hardening measures, and important safety considerations for the GitHub PR Review MCP Server MCP server.

## File Creation Removal

### Background

This MCP server originally included functionality to create markdown markdown files on disk via a `create_review_spec_file` tool. This feature was intentionally removed due to security complexity and concerns.

### Security Rationale

File creation operations introduce several security vectors:

- **Path traversal attacks**: Even with validation, filename manipulation could potentially escape intended directories
- **Symlink attacks**: Malicious symlinks could redirect writes to unintended locations
- **File overwrite risks**: Accidental or intentional overwriting of existing files
- **Permission escalation**: File creation with inappropriate permissions
- **Disk space exhaustion**: Potential for abuse to fill disk space

### Alternative Solutions

Instead of server-side file creation, we recommend:

1. **Agentic agents handle file operations**: Modern AI agents and tools have robust, native file handling capabilities that are better suited for this task
2. **External CLI tool**: Use [`gh-pr-rev-md`](https://github.com/petems/gh-pr-rev-md) - a dedicated, non-MCP command-line tool specifically designed for creating PR review markdown files
3. **Client-side processing**: Let the consuming application handle file operations using the markdown content returned by the MCP server

This approach follows the principle of least privilege and separates concerns appropriately.

## Security Hardening Measures

### GitHub API Security

- **Token-based authentication**: Supports both fine-grained Personal Access Tokens (PATs) and classic PATs
- **Automatic fallback handling**: If Bearer token fails with 401, automatically retries with token scheme for classic PATs
- **Minimal required scopes**: 
  - Public repos: `public_repo` scope only
  - Private repos: `repo` scope only
  - Fine-grained PATs: Pull requests → Read access only

### Network Security

- **Request timeouts**: 30-second total timeout, 10-second connection timeout
- **Rate limiting respect**: Automatic handling of GitHub API rate limits with proper backoff
- **Retry logic with exponential backoff**: Maximum 3 retries with jitter to prevent thundering herd
- **Input validation**: URL parsing with strict regex validation for GitHub PR URLs
- **Safe HTTP headers**: Proper User-Agent and Accept headers

### Input Validation & Sanitization

- **URL validation**: Strict regex pattern matching for GitHub PR URLs
- **Parameter validation**: All numeric parameters validated within safe ranges
- **Type checking**: Strong typing throughout with runtime validation
- **URL encoding**: Proper encoding of repository owner/name in API calls

### Memory & Resource Protection

- **Pagination limits**: 
  - Maximum 200 pages (configurable, default 50)
  - Maximum 100,000 comments (configurable, default 2,000)
- **Per-page limits**: 1-100 comments per page (GitHub API limit)
- **Early termination**: Stops fetching when safety limits are reached

### Code Security

- **No dynamic code execution**: No `eval()`, `exec()`, or similar dangerous functions
- **Exception handling**: Comprehensive error handling without information leakage
- **Dependency management**: Locked dependencies with known versions

## Important Security Warnings

### ⚠️ Agentic Workflow Risks

**CRITICAL**: This MCP server fetches and returns PR review comments as-is from GitHub. When using this in agentic workflows, be aware of serious security risks:

#### Code Injection via Comments

- **Malicious suggestions**: Bad actors could submit PR comments containing malicious code suggestions
- **Social engineering**: Comments could trick AI agents into implementing harmful changes
- **Supply chain attacks**: Compromised contributor accounts could inject malicious suggestions

#### Unintentional Breakages

- **Incorrect implementations**: AI agents might misinterpret comments and implement broken code
- **Context loss**: Comments may reference code that has changed since the comment was made
- **Incomplete implementations**: Partial or incorrect implementation of suggested changes

#### Recommended Safeguards

1. **Human review required**: Never auto-implement PR comments without human review
2. **Sandboxed testing**: Test all generated code in isolated environments
3. **Limited scope**: Restrict AI agent permissions and capabilities
4. **Audit trails**: Maintain logs of all changes made based on PR comments
5. **Validation gates**: Implement automated testing and validation before deployment
6. **Trust boundaries**: Treat all PR comments as untrusted input

### Data Privacy Considerations

- **Sensitive information exposure**: PR comments may contain sensitive data, API keys, or internal information
- **Access control**: Ensure proper repository access controls before fetching comments
- **Data retention**: Consider how long fetched comment data is retained in memory or logs

## Environment Security

### Token Management

```bash
# Use environment variables, never hardcode tokens
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Restrict token permissions to minimum required
# Fine-grained PAT: Repository access + Pull requests: Read
# Classic PAT: public_repo (public) or repo (private)
```

### Network Configuration

```bash
# Optional: Configure stricter limits
PR_FETCH_MAX_PAGES=10          # Reduce from default 50
PR_FETCH_MAX_COMMENTS=500      # Reduce from default 2000
HTTP_MAX_RETRIES=1             # Reduce from default 3
```

## Reporting Security Issues

If you discover a security vulnerability in this MCP server:

1. **Do not** create a public GitHub issue
2. Report privately via GitHub Security Advisories
3. Include detailed reproduction steps
4. Allow reasonable time for response and fix

## Security Updates

This MCP server follows semantic versioning. Security updates will be released as:

- **Patch releases** (x.x.X) for security fixes
- **Minor releases** (x.X.x) for security enhancements
- **Major releases** (X.x.x) for breaking security changes

Always use the latest version and monitor security advisories.

## License and Liability

This software is provided "as-is" without warranty. Users are responsible for:

- Proper token management and access controls
- Validating and reviewing all generated content
- Implementing appropriate safeguards in their workflows
- Compliance with their organization's security policies

See the LICENSE file for complete terms and conditions.