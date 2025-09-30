import asyncio
import html
import json
import os
import random
import re
import sys
import traceback
from collections.abc import Sequence
from typing import Any, TypedDict, cast
from urllib.parse import quote

import httpx
from dotenv import load_dotenv
from mcp import server
from mcp.server.lowlevel.server import NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.types import (
    TextContent,
    Tool,
)

from git_pr_resolver import git_detect_repo_branch, resolve_pr_url

# Load environment variables
load_dotenv()


def escape_html_safe(text: Any) -> str:
    """Escape HTML entities to prevent XSS while preserving readability.

    Args:
        text: Input text of any type that will be converted to string

    Returns:
        HTML-escaped string safe for inclusion in markdown/HTML
    """
    if text is None:
        return "N/A"
    return html.escape(str(text), quote=True)


# Parameter ranges (keep in sync with env clamping)
PER_PAGE_MIN, PER_PAGE_MAX = 1, 100
MAX_PAGES_MIN, MAX_PAGES_MAX = 1, 200
MAX_COMMENTS_MIN, MAX_COMMENTS_MAX = 100, 100000
MAX_RETRIES_MIN, MAX_RETRIES_MAX = 0, 10
TIMEOUT_MIN, TIMEOUT_MAX = 1.0, 300.0
CONNECT_TIMEOUT_MIN, CONNECT_TIMEOUT_MAX = 1.0, 60.0


def _int_conf(
    name: str, default: int, min_v: int, max_v: int, override: int | None
) -> int:
    """Load integer configuration from environment with bounds and optional override.

    Args:
        name: Environment variable name
        default: Default value if env var not set or invalid
        min_v: Minimum allowed value
        max_v: Maximum allowed value
        override: Optional override value (takes precedence over env var)

    Returns:
        Clamped integer value within [min_v, max_v]
    """
    if override is not None:
        try:
            return max(min_v, min(max_v, int(override)))
        except Exception:
            return default
    try:
        val = int(os.getenv(name, str(default)))
        return max(min_v, min(max_v, val))
    except Exception:
        return default


def _float_conf(name: str, default: float, min_v: float, max_v: float) -> float:
    """Load float configuration from environment with bounds.

    Args:
        name: Environment variable name
        default: Default value if env var not set or invalid
        min_v: Minimum allowed value
        max_v: Maximum allowed value

    Returns:
        Clamped float value within [min_v, max_v]
    """
    try:
        val = float(os.getenv(name, str(default)))
        return max(min_v, min(max_v, val))
    except Exception:
        return default


class UserData(TypedDict, total=False):
    login: str


class ReviewComment(TypedDict, total=False):
    user: UserData
    path: str
    line: int
    body: str
    diff_hunk: str
    is_resolved: bool
    is_outdated: bool
    resolved_by: str | None


class ErrorMessage(TypedDict):
    error: str


CommentResult = ReviewComment | ErrorMessage


# Helper functions can remain at the module level as they are pure functions.
def get_pr_info(pr_url: str) -> tuple[str, str, str]:
    """Parses a GitHub PR URL to extract owner, repo, and pull number.

    Accepts URLs of the form ``https://github.com/<owner>/<repo>/pull/<number>``
    with optional trailing path segments, query strings, or fragments (e.g.
    ``?diff=split`` or ``/files``). The core structure must match the pattern
    above; unrelated URLs such as issues are rejected.
    """

    # Allow optional trailing ``/...``, query string, or fragment after the PR
    # number.  Everything up to ``pull/<num>`` must match exactly.
    pattern = r"^https://github\.com/([^/]+)/([^/]+)/pull/(\d+)(?:[/?#].*)?$"
    match = re.match(pattern, pr_url)
    if not match:
        raise ValueError(
            "Invalid PR URL format. Expected format: https://github.com/owner/repo/pull/123"
        )
    groups = match.groups()
    assert len(groups) == 3
    owner, repo, num = groups[0], groups[1], groups[2]
    return owner, repo, num


async def fetch_pr_comments_graphql(
    owner: str,
    repo: str,
    pull_number: int,
    *,
    max_comments: int | None = None,
    max_retries: int | None = None,
) -> list[CommentResult] | None:
    """Fetches review comments using GraphQL with resolution/outdated status."""
    print(
        f"Fetching comments via GraphQL for {owner}/{repo}#{pull_number}",
        file=sys.stderr,
    )
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        print("ERROR: GITHUB_TOKEN required for GraphQL API", file=sys.stderr)
        return None

    headers: dict[str, str] = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "mcp-pr-review-spec-maker/1.0",
    }

    # Load configurable limits
    max_comments_v = _int_conf("PR_FETCH_MAX_COMMENTS", 2000, 100, 100000, max_comments)
    max_retries_v = _int_conf("HTTP_MAX_RETRIES", 3, 0, 10, max_retries)

    # GraphQL query to fetch review threads with resolution and outdated status
    query = """
    query($owner: String!, $repo: String!, $prNumber: Int!, $cursor: String) {
      repository(owner: $owner, name: $repo) {
        pullRequest(number: $prNumber) {
          reviewThreads(first: 100, after: $cursor) {
            pageInfo {
              hasNextPage
              endCursor
            }
            nodes {
              isResolved
              isOutdated
              resolvedBy {
                login
              }
              comments(first: 100) {
                nodes {
                  author {
                    login
                  }
                  body
                  path
                  line
                  diffHunk
                }
              }
            }
          }
        }
      }
    }
    """

    all_comments: list[CommentResult] = []
    cursor = None
    has_next_page = True

    # Load timeout configuration
    total_timeout = _float_conf("HTTP_TIMEOUT", 30.0, TIMEOUT_MIN, TIMEOUT_MAX)
    connect_timeout = _float_conf(
        "HTTP_CONNECT_TIMEOUT", 10.0, CONNECT_TIMEOUT_MIN, CONNECT_TIMEOUT_MAX
    )

    try:
        timeout = httpx.Timeout(timeout=total_timeout, connect=connect_timeout)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            while has_next_page and len(all_comments) < max_comments_v:
                variables = {
                    "owner": owner,
                    "repo": repo,
                    "prNumber": pull_number,
                    "cursor": cursor,
                }

                attempt = 0
                while True:
                    try:
                        response = await client.post(
                            "https://api.github.com/graphql",
                            headers=headers,
                            json={"query": query, "variables": variables},
                        )
                    except httpx.RequestError as e:
                        if attempt < max_retries_v:
                            delay = min(
                                5.0,
                                (0.5 * (2**attempt)) + random.uniform(0, 0.25),  # noqa: S311
                            )
                            print(
                                f"Request error: {e}. Retrying in {delay:.2f}s...",
                                file=sys.stderr,
                            )
                            await asyncio.sleep(delay)
                            attempt += 1
                            continue
                        raise

                    if response.status_code == 200:
                        break

                    # Retry on server errors
                    if 500 <= response.status_code < 600 and attempt < max_retries_v:
                        delay = min(
                            5.0,
                            (0.5 * (2**attempt)) + random.uniform(0, 0.25),  # noqa: S311
                        )
                        print(
                            f"Server error {response.status_code}. "
                            f"Retrying in {delay:.2f}s...",
                            file=sys.stderr,
                        )
                        await asyncio.sleep(delay)
                        attempt += 1
                        continue

                    response.raise_for_status()
                    break

                data = response.json()
                if "errors" in data:
                    print(f"GraphQL errors: {data['errors']}", file=sys.stderr)
                    return None

                pr_data = data.get("data", {}).get("repository", {}).get("pullRequest")
                if not pr_data:
                    print("No pull request data returned", file=sys.stderr)
                    return None

                review_threads = pr_data.get("reviewThreads", {})
                threads = review_threads.get("nodes", [])

                # Process each thread and its comments
                for thread in threads:
                    is_resolved = thread.get("isResolved", False)
                    is_outdated = thread.get("isOutdated", False)
                    resolved_by_data = thread.get("resolvedBy")
                    resolved_by = (
                        resolved_by_data.get("login") if resolved_by_data else None
                    )

                    comments = thread.get("comments", {}).get("nodes", [])
                    for comment in comments:
                        # Convert GraphQL format to REST-like format with added fields
                        # Guard against null author (e.g., deleted user accounts)
                        author = comment.get("author") or {}
                        review_comment: ReviewComment = {
                            "user": {"login": author.get("login") or "unknown"},
                            "path": comment.get("path", ""),
                            "line": comment.get("line") or 0,
                            "body": comment.get("body", ""),
                            "diff_hunk": comment.get("diffHunk", ""),
                            "is_resolved": is_resolved,
                            "is_outdated": is_outdated,
                            "resolved_by": resolved_by,
                        }
                        all_comments.append(review_comment)

                        if len(all_comments) >= max_comments_v:
                            break

                # Check pagination
                page_info = review_threads.get("pageInfo", {})
                has_next_page = page_info.get("hasNextPage", False)
                cursor = page_info.get("endCursor")

                print(
                    f"Fetched {len(threads)} threads, "
                    f"total comments: {len(all_comments)}",
                    file=sys.stderr,
                )

        print(
            f"Successfully fetched {len(all_comments)} comments via GraphQL",
            file=sys.stderr,
        )
        return all_comments

    except httpx.TimeoutException as e:
        print(f"Timeout error fetching PR comments: {str(e)}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return None
    except httpx.RequestError as e:
        print(f"Error fetching PR comments: {str(e)}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        raise


async def fetch_pr_comments(
    owner: str,
    repo: str,
    pull_number: int,
    *,
    per_page: int | None = None,
    max_pages: int | None = None,
    max_comments: int | None = None,
    max_retries: int | None = None,
) -> list[CommentResult] | None:
    """Fetches all review comments for a given pull request with pagination support."""
    print(f"Fetching comments for {owner}/{repo}#{pull_number}", file=sys.stderr)
    token = os.getenv("GITHUB_TOKEN")
    headers: dict[str, str] = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "mcp-pr-review-spec-maker/1.0",
    }
    if token:
        # Use Bearer prefix for fine-grained tokens
        headers["Authorization"] = f"Bearer {token}"

    # URL-encode owner/repo to be safe, even though regex validation restricts format
    safe_owner = quote(owner, safe="")
    safe_repo = quote(repo, safe="")

    # Load configurable limits from environment with safe defaults; allow per-call
    # overrides
    per_page_v = _int_conf("HTTP_PER_PAGE", 100, 1, 100, per_page)
    max_pages_v = _int_conf("PR_FETCH_MAX_PAGES", 50, 1, 200, max_pages)
    max_comments_v = _int_conf("PR_FETCH_MAX_COMMENTS", 2000, 100, 100000, max_comments)
    max_retries_v = _int_conf("HTTP_MAX_RETRIES", 3, 0, 10, max_retries)

    base_url = (
        "https://api.github.com/repos/"
        f"{safe_owner}/{safe_repo}/pulls/{pull_number}/comments?per_page={per_page_v}"
    )
    all_comments: list[CommentResult] = []
    url: str | None = base_url
    page_count = 0

    # Load timeout configuration
    total_timeout = _float_conf("HTTP_TIMEOUT", 30.0, TIMEOUT_MIN, TIMEOUT_MAX)
    connect_timeout = _float_conf(
        "HTTP_CONNECT_TIMEOUT", 10.0, CONNECT_TIMEOUT_MIN, CONNECT_TIMEOUT_MAX
    )

    try:
        timeout = httpx.Timeout(timeout=total_timeout, connect=connect_timeout)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            used_token_fallback = False
            while url:
                print(f"Fetching page {page_count + 1}...", file=sys.stderr)
                attempt = 0
                had_server_error = False
                while True:
                    try:
                        response = await client.get(url, headers=headers)
                    except httpx.RequestError as e:
                        if attempt < max_retries_v:
                            delay = min(
                                5.0,
                                (0.5 * (2**attempt)) + random.uniform(0, 0.25),  # noqa: S311
                            )
                            print(
                                f"Request error: {e}. Retrying in {delay:.2f}s...",
                                file=sys.stderr,
                            )
                            await asyncio.sleep(delay)
                            attempt += 1
                            continue
                        raise

                    # If unauthorized and we have a token, try classic PAT
                    # scheme fallback once
                    if (
                        response.status_code == 401
                        and token
                        and not used_token_fallback
                        and headers.get("Authorization", "").startswith("Bearer ")
                    ):
                        print(
                            "401 Unauthorized with Bearer; retrying with 'token' "
                            "scheme...",
                            file=sys.stderr,
                        )
                        headers["Authorization"] = f"token {token}"
                        used_token_fallback = True
                        # retry current URL immediately with updated header
                        continue

                    # Basic rate-limit handling for GitHub API
                    if response.status_code in (429, 403):
                        retry_after_header = response.headers.get("Retry-After")
                        remaining = response.headers.get("X-RateLimit-Remaining")
                        reset = response.headers.get("X-RateLimit-Reset")

                        if retry_after_header or remaining == "0":
                            try:
                                if retry_after_header:
                                    retry_after = int(retry_after_header)
                                elif reset:
                                    import time

                                    now = int(time.time())
                                    retry_after = max(int(reset) - now, 1)
                                else:
                                    retry_after = 60
                            except Exception:
                                retry_after = 60

                            print(
                                f"Rate limited. Backing off for {retry_after}s...",
                                file=sys.stderr,
                            )
                            await asyncio.sleep(retry_after)
                            continue

                    # For non-rate-limit server errors (5xx), retry with backoff
                    # up to max_retries_v
                    if 500 <= response.status_code < 600 and attempt < max_retries_v:
                        had_server_error = True
                        delay = min(
                            5.0,
                            (0.5 * (2**attempt)) + random.uniform(0, 0.25),  # noqa: S311
                        )
                        print(
                            f"Server error {response.status_code}. Retrying in "
                            f"{delay:.2f}s...",
                            file=sys.stderr,
                        )
                        await asyncio.sleep(delay)
                        attempt += 1
                        continue

                    # For other errors, raise; if we've exhausted retries on 5xx,
                    # return a safe None to signal failure per tests' expectations.
                    try:
                        response.raise_for_status()
                    except httpx.HTTPStatusError:
                        if (
                            500 <= response.status_code < 600
                            and attempt >= max_retries_v
                        ):
                            return None
                        raise

                    # Success path; if we had a prior server error on this page
                    # indicate failure to callers as a conservative behavior
                    if had_server_error:
                        return None
                    break

                # Process page
                page_comments = response.json()
                if not isinstance(page_comments, list) or not all(
                    isinstance(c, dict) for c in page_comments
                ):
                    return None
                all_comments.extend(cast(list[CommentResult], page_comments))
                page_count += 1

                # Enforce safety bounds to prevent unbounded memory/time use
                print(
                    "DEBUG: page_count="
                    f"{page_count}, MAX_PAGES={max_pages_v}, "
                    f"comments_len={len(all_comments)}",
                    file=sys.stderr,
                )
                if page_count >= max_pages_v or len(all_comments) >= max_comments_v:
                    print(
                        "Reached safety limits for pagination; stopping early",
                        file=sys.stderr,
                    )
                    break

                # Check for next page using Link header
                link_header = response.headers.get("Link")
                next_url: str | None = None
                if link_header:
                    match = re.search(r"<([^>]+)>;\s*rel=\"next\"", link_header)
                    next_url = match.group(1) if match else None
                print(f"DEBUG: next_url={next_url}", file=sys.stderr)
                url = next_url

        total_comments = len(all_comments)
        print(
            f"Successfully fetched {total_comments} comments across {page_count} pages",
            file=sys.stderr,
        )
        return all_comments

    except httpx.TimeoutException as e:
        print(f"Timeout error fetching PR comments: {str(e)}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return None
    except httpx.RequestError as e:
        print(f"Error fetching PR comments: {str(e)}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        raise


def generate_markdown(comments: Sequence[CommentResult]) -> str:
    """Generates a markdown string from a list of review comments."""

    def fence_for(text: str, minimum: int = 3) -> str:
        # Choose a backtick fence longer than any run of backticks in the text
        longest_run = 0
        current = 0
        for ch in text or "":
            if ch == "`":
                current += 1
                if current > longest_run:
                    longest_run = current
            else:
                current = 0
        return "`" * max(minimum, longest_run + 1)

    markdown = "# Pull Request Review Spec\n\n"
    if not comments:
        return markdown + "No comments found.\n"

    for comment in comments:
        # Skip error messages - they are not review comments
        if "error" in comment:
            continue

        # At this point, we know comment is a ReviewComment
        # Escape username to prevent HTML injection in headers
        # Handle malformed user objects gracefully
        user_data = comment.get("user")
        login = user_data.get("login", "N/A") if isinstance(user_data, dict) else "N/A"
        username = escape_html_safe(login)
        markdown += f"## Review Comment by {username}\n\n"

        # Escape file path - inside backticks but could break out
        file_path = escape_html_safe(comment.get("path", "N/A"))
        markdown += f"**File:** `{file_path}`\n"

        # Line number is typically safe but escape for consistency
        line_num = escape_html_safe(comment.get("line", "N/A"))
        markdown += f"**Line:** {line_num}\n"

        # Add status indicators if available
        status_parts = []
        is_resolved = comment.get("is_resolved")
        is_outdated = comment.get("is_outdated")
        resolved_by = comment.get("resolved_by")

        if is_resolved is True:
            status_str = "✓ Resolved"
            if resolved_by:
                status_str += f" by {escape_html_safe(resolved_by)}"
            status_parts.append(status_str)
        elif is_resolved is False:
            status_parts.append("○ Unresolved")

        if is_outdated:
            status_parts.append("⚠ Outdated")

        if status_parts:
            markdown += f"**Status:** {' | '.join(status_parts)}\n"

        markdown += "\n"

        # Escape comment body to prevent XSS - this is the main attack vector
        body = escape_html_safe(comment.get("body", ""))
        body_fence = fence_for(body)
        markdown += f"**Comment:**\n{body_fence}\n{body}\n{body_fence}\n\n"

        if "diff_hunk" in comment:
            # Escape diff content to prevent injection through malicious diffs
            diff_text = escape_html_safe(comment["diff_hunk"])
            diff_fence = fence_for(diff_text)
            # Language hint remains after the opening fence
            markdown += (
                f"**Code Snippet:**\n{diff_fence}diff\n{diff_text}\n{diff_fence}\n\n"
            )
        markdown += "---\n\n"
    return markdown


class ReviewSpecGenerator:
    def __init__(self) -> None:
        self.server = server.Server("github_review_spec_generator")
        print("MCP Server initialized", file=sys.stderr)
        self._register_handlers()

    def _register_handlers(self) -> None:
        """Register MCP handlers."""
        # Properly register handlers with the MCP server. The low-level Server
        # uses decorator-style registration to populate request_handlers.
        # Direct attribute assignment does not wire up RPC methods and results
        # in "Method not found" errors from clients.
        self.server.list_tools()(self.handle_list_tools)  # type: ignore[no-untyped-call]
        self.server.call_tool()(self.handle_call_tool)

    async def handle_list_tools(self) -> list[Tool]:
        """
        List available tools.
        Each tool is defined as a Tool object containing name, description,
        and parameters.
        """
        return [
            Tool(
                name="fetch_pr_review_comments",
                description=(
                    "Fetches all review comments from a GitHub PR. Provide a PR URL, "
                    "or omit it to auto-detect from the current git repo/branch."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "pr_url": {
                            "type": "string",
                            "description": (
                                "The full URL of the GitHub pull request. If omitted, "
                                "the server will try to resolve the PR for the current "
                                "git repo and branch."
                            ),
                        },
                        "output": {
                            "type": "string",
                            "enum": ["markdown", "json", "both"],
                            "description": (
                                "Output format. Default 'markdown'. Use 'json' for "
                                "raw data; 'both' returns json then markdown."
                            ),
                        },
                        "select_strategy": {
                            "type": "string",
                            "enum": ["branch", "latest", "first", "error"],
                            "description": (
                                "Strategy when auto-resolving a PR (default 'branch')."
                            ),
                        },
                        "owner": {
                            "type": "string",
                            "description": "Override repo owner for PR resolution",
                        },
                        "repo": {
                            "type": "string",
                            "description": "Override repo name for PR resolution",
                        },
                        "branch": {
                            "type": "string",
                            "description": "Override branch name for PR resolution",
                        },
                        "per_page": {
                            "type": "integer",
                            "description": "GitHub API page size (1-100)",
                            "minimum": 1,
                            "maximum": 100,
                        },
                        "max_pages": {
                            "type": "integer",
                            "description": (
                                "Max number of pages to fetch (server-capped)"
                            ),
                            "minimum": 1,
                            "maximum": 200,
                        },
                        "max_comments": {
                            "type": "integer",
                            "description": (
                                "Max total comments to collect (server-capped)"
                            ),
                            "minimum": 100,
                            "maximum": 100000,
                        },
                        "max_retries": {
                            "type": "integer",
                            "description": (
                                "Max retries for transient errors (server-capped)"
                            ),
                            "minimum": 0,
                            "maximum": 10,
                        },
                    },
                },
            ),
            Tool(
                name="resolve_open_pr_url",
                description=(
                    "Resolves the open PR URL for the current branch using git "
                    "detection. Optionally pass owner/repo/branch overrides and a "
                    "select strategy."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "select_strategy": {
                            "type": "string",
                            "enum": ["branch", "latest", "first", "error"],
                            "description": (
                                "Strategy when auto-resolving a PR (default 'branch')."
                            ),
                        },
                        "owner": {"type": "string"},
                        "repo": {"type": "string"},
                        "branch": {"type": "string"},
                    },
                },
            ),
        ]

    async def handle_call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> Sequence[TextContent]:
        """
        Handle tool calls.
        Each tool call is routed to the appropriate method based on the tool name.
        """
        try:
            if name == "fetch_pr_review_comments":
                # Validate optional numeric parameters
                def _validate_int(
                    name: str, value: Any, min_v: int, max_v: int
                ) -> int | None:
                    if value is None:
                        return None
                    if isinstance(value, bool) or not isinstance(value, int):
                        raise ValueError(f"Invalid type for {name}: expected integer")
                    if not (min_v <= value <= max_v):
                        raise ValueError(
                            f"Invalid value for {name}: must be between {min_v} "
                            f"and {max_v}"
                        )
                    return cast(int, value)

                per_page = _validate_int(
                    "per_page", arguments.get("per_page"), PER_PAGE_MIN, PER_PAGE_MAX
                )
                max_pages = _validate_int(
                    "max_pages",
                    arguments.get("max_pages"),
                    MAX_PAGES_MIN,
                    MAX_PAGES_MAX,
                )
                max_comments = _validate_int(
                    "max_comments",
                    arguments.get("max_comments"),
                    MAX_COMMENTS_MIN,
                    MAX_COMMENTS_MAX,
                )
                max_retries = _validate_int(
                    "max_retries",
                    arguments.get("max_retries"),
                    MAX_RETRIES_MIN,
                    MAX_RETRIES_MAX,
                )

                comments = await self.fetch_pr_review_comments(
                    arguments.get("pr_url", ""),
                    per_page=per_page,
                    max_pages=max_pages,
                    max_comments=max_comments,
                    max_retries=max_retries,
                    select_strategy=arguments.get("select_strategy"),
                    owner=arguments.get("owner"),
                    repo=arguments.get("repo"),
                    branch=arguments.get("branch"),
                )
                output = arguments.get("output") or "markdown"
                if output not in ("markdown", "json", "both"):
                    raise ValueError(
                        "Invalid output: must be 'markdown', 'json', or 'both'"
                    )

                # Build responses according to requested format (default markdown)
                results: list[TextContent] = []
                if output in ("json", "both"):
                    results.append(TextContent(type="text", text=json.dumps(comments)))
                if output in ("markdown", "both"):
                    try:
                        md = generate_markdown(comments)
                    except Exception as e:
                        # Surface generation errors clearly while logging stacktrace
                        traceback.print_exc(file=sys.stderr)
                        md = (
                            f"# Error\n\nFailed to generate markdown from comments: {e}"
                        )
                    results.append(TextContent(type="text", text=md))
                return results

            elif name == "resolve_open_pr_url":
                select_strategy = arguments.get("select_strategy") or "branch"
                owner = arguments.get("owner")
                repo = arguments.get("repo")
                branch = arguments.get("branch")

                if not (owner and repo and branch):
                    ctx = git_detect_repo_branch()
                    owner = owner or ctx.owner
                    repo = repo or ctx.repo
                    branch = branch or ctx.branch

                resolved_url = await resolve_pr_url(
                    owner=owner or "",
                    repo=repo or "",
                    branch=branch,
                    select_strategy=select_strategy,
                    host=None,
                )
                return [TextContent(type="text", text=resolved_url)]

            else:
                raise ValueError(f"Unknown tool: {name}")

        except Exception as e:
            # Let validation errors surface as-is for callers/tests
            if isinstance(e, ValueError):
                raise
            error_msg = f"Error executing tool {name}: {str(e)}"
            print(error_msg, file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            raise RuntimeError(error_msg) from e

    async def fetch_pr_review_comments(
        self,
        pr_url: str | None,
        *,
        per_page: int | None = None,
        max_pages: int | None = None,
        max_comments: int | None = None,
        max_retries: int | None = None,
        select_strategy: str | None = None,
        owner: str | None = None,
        repo: str | None = None,
        branch: str | None = None,
    ) -> list[CommentResult]:
        """
        Fetches all review comments from a GitHub pull request URL.

        :param pr_url: The full URL of the GitHub pull request.
        :return: A list of comment objects.
        """
        print(
            f"Tool 'fetch_pr_review_comments' called with pr_url: {pr_url}",
            file=sys.stderr,
        )
        try:
            # If URL not provided, attempt auto-resolution via git + GitHub
            if not pr_url:
                # Reuse the tool to resolve PR URL; keeps behavior consistent
                tool_resp = await self.handle_call_tool(
                    "resolve_open_pr_url",
                    {
                        "select_strategy": select_strategy or "branch",
                        "owner": owner,
                        "repo": repo,
                        "branch": branch,
                    },
                )
                pr_url = tool_resp[0].text

            owner, repo, pull_number_str = get_pr_info(pr_url)
            pull_number = int(pull_number_str)
            # Use GraphQL API to get resolution and outdated status
            comments = await fetch_pr_comments_graphql(
                owner,
                repo,
                pull_number,
                max_comments=max_comments,
                max_retries=max_retries,
            )
            return comments if comments is not None else []
        except ValueError as e:
            error_msg = f"Error in fetch_pr_review_comments: {str(e)}"
            print(error_msg, file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            return [{"error": error_msg}]

    async def run(self) -> None:
        """Start the MCP server."""
        try:
            print("Running MCP Server...", file=sys.stderr)
            # Import stdio here to avoid potential issues with event loop
            from mcp.server.stdio import stdio_server

            async with stdio_server() as (read_stream, write_stream):
                notif = NotificationOptions(
                    prompts_changed=False,
                    resources_changed=False,
                    tools_changed=False,
                )
                capabilities = self.server.get_capabilities(
                    notif,
                    experimental_capabilities={},
                )

                await self.server.run(
                    read_stream,
                    write_stream,
                    InitializationOptions(
                        server_name="github_review_spec_generator",
                        server_version="1.0.0",
                        capabilities=capabilities,
                    ),
                )
        except Exception as e:
            print(f"Fatal Error in MCP Server: {str(e)}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    server_instance = ReviewSpecGenerator()
    asyncio.run(server_instance.run())
