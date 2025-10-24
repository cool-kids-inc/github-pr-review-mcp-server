import asyncio
import html
import json
import os
import random
import re
import sys
import traceback
from collections.abc import Awaitable, Callable, Sequence
from importlib.metadata import version
from typing import Any, TypeVar
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
from pydantic import ValidationError

from .git_pr_resolver import (
    api_base_for_host,
    git_detect_repo_branch,
    graphql_url_for_host,
    resolve_pr_url,
)
from .github_api_constants import (
    GITHUB_ACCEPT_HEADER,
    GITHUB_API_VERSION,
    GITHUB_USER_AGENT,
)
from .models import (
    FetchPRReviewCommentsArgs,
    ResolveOpenPrUrlArgs,
    ReviewCommentModel,
)

# Load environment variables
load_dotenv()

# Get package version from metadata
try:
    __version__ = version("mcp-github-pr-review")
except Exception:  # noqa: BLE001
    __version__ = "0.1.0"  # Fallback version


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
            override_int = int(override)
        except (TypeError, ValueError):
            return default
        return max(min_v, min(max_v, override_int))

    env_value = os.getenv(name)
    if env_value is None:
        env_value = str(default)

    try:
        env_int = int(env_value)
    except (TypeError, ValueError):
        return default
    return max(min_v, min(max_v, env_int))


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
    env_value = os.getenv(name)
    if env_value is None:
        env_value = str(default)

    try:
        env_float = float(env_value)
    except (TypeError, ValueError):
        return default
    return max(min_v, min(max_v, env_float))


# Type alias for comment results (dict format for backwards compatibility)
CommentResult = dict[str, Any]


def _calculate_backoff_delay(attempt: int) -> float:
    """Calculate exponential backoff delay with jitter.

    Args:
        attempt: Current retry attempt number (0-indexed)

    Returns:
        Delay in seconds, capped at 5.0 seconds
    """
    jitter: float = random.uniform(0, 0.25)  # noqa: S311
    delay: float = (0.5 * (2**attempt)) + jitter
    return min(5.0, delay)


async def _retry_http_request(
    request_fn: Callable[[], Awaitable[httpx.Response]],
    max_retries: int,
    *,
    status_handler: Callable[[httpx.Response, int], Awaitable[str | None]]
    | None = None,
) -> httpx.Response:
    """Execute HTTP request with retry logic for transient errors.

    Handles httpx.RequestError and 5xx server errors with exponential backoff.
    Allows custom status code handling via optional callback.

    Args:
        request_fn: Async callable that performs the HTTP request
        max_retries: Maximum number of retry attempts
        status_handler: Optional async callback for custom status code handling.
            Should return "retry" to retry immediately without incrementing
            attempt counter, or None to continue with default handling.

    Returns:
        httpx.Response on success

    Raises:
        httpx.RequestError: If request errors exceed max_retries
        httpx.HTTPStatusError: If non-retryable HTTP errors occur
    """
    attempt = 0
    while True:
        try:
            response = await request_fn()
        except httpx.RequestError as e:
            if attempt < max_retries:
                delay = _calculate_backoff_delay(attempt)
                print(
                    f"Request error: {e}. Retrying in {delay:.2f}s...",
                    file=sys.stderr,
                )
                await asyncio.sleep(delay)
                attempt += 1
                continue
            raise

        # Allow custom status handling (rate limiting, auth fallback, etc.)
        if status_handler:
            action = await status_handler(response, attempt)
            if action == "retry":
                continue  # Retry without incrementing attempt counter

        # Handle 5xx server errors with retry
        if 500 <= response.status_code < 600 and attempt < max_retries:
            delay = _calculate_backoff_delay(attempt)
            print(
                f"Server error {response.status_code}. Retrying in {delay:.2f}s...",
                file=sys.stderr,
            )
            await asyncio.sleep(delay)
            attempt += 1
            continue

        # For other errors or success, let caller handle
        response.raise_for_status()
        return response


# Helper functions can remain at the module level as they are pure functions.
def get_pr_info(pr_url: str) -> tuple[str, str, str, str]:
    """
    Parses a GitHub pull request URL and returns its host, owner,
    repository, and pull number.

    Accepts URLs of the form https://<host>/<owner>/<repo>/pull/<number>
    with optional trailing path segments, query strings, or fragments
    (for example, ?diff=split or /files).

    Parameters:
        pr_url: The full pull request URL to parse.

    Returns:
        A tuple (host, owner, repo, pull_number) where each element
        is a string.

    Raises:
        ValueError: If the URL does not match the expected pull
            request format.
    """

    # Allow optional trailing ``/...``, query string, or fragment after the PR
    # number.  Everything up to ``pull/<num>`` must match exactly.
    pattern = r"^https://([^/]+)/([^/]+)/([^/]+)/pull/(\d+)(?:[/?#].*)?$"
    match = re.match(pattern, pr_url)
    if not match:
        raise ValueError(
            "Invalid PR URL format. Expected format: https://{host}/owner/repo/pull/123"
        )
    groups = match.groups()
    assert len(groups) == 4
    host, owner, repo, num = groups[0], groups[1], groups[2], groups[3]
    return host, owner, repo, num


async def fetch_pr_comments_graphql(
    owner: str,
    repo: str,
    pull_number: int,
    *,
    host: str = "github.com",
    max_comments: int | None = None,
    max_retries: int | None = None,
) -> list[CommentResult] | None:
    """
    Fetch review comments for a pull request via the GitHub GraphQL API,
    including resolution and outdated status.

    Requires the environment variable GITHUB_TOKEN to be set. The returned
    items are dictionaries matching the ReviewComment TypedDict with
    additional fields: `is_resolved`, `is_outdated`, and `resolved_by`.

    Parameters:
        host (str): GitHub host to target (e.g., "github.com").
            Defaults to "github.com".
        max_comments (int | None): Maximum number of comments to fetch;
            if None, the configured/default limit is used.
        max_retries (int | None): Maximum retry attempts for transient
            HTTP errors; if None, the configured/default is used.

    Returns:
        list[CommentResult] | None: A list of review comment objects on
            success, or `None` if the operation failed or timed out.

    Raises:
        httpx.RequestError: If a network/request error occurs after
            exhausting retries.
    """
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
        "Accept": GITHUB_ACCEPT_HEADER,
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
        "Content-Type": "application/json",
        "User-Agent": GITHUB_USER_AGENT,
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

                graphql_url = graphql_url_for_host(host)

                # Use retry helper for GraphQL request (capture loop variables)
                async def make_graphql_request(
                    url: str = graphql_url, gql_vars: dict[str, Any] = variables
                ) -> httpx.Response:
                    return await client.post(
                        url,
                        headers=headers,
                        json={"query": query, "variables": gql_vars},
                    )

                response = await _retry_http_request(
                    make_graphql_request, max_retries_v
                )

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

                    comments = thread.get("comments", {}).get("nodes", [])
                    for comment in comments:
                        # Build a complete node dict with thread-level metadata
                        node = {
                            **comment,
                            "isResolved": is_resolved,
                            "isOutdated": is_outdated,
                            "resolvedBy": resolved_by_data,
                        }
                        # Convert GraphQL format using Pydantic model
                        review_comment_model = ReviewCommentModel.from_graphql(node)
                        all_comments.append(
                            review_comment_model.model_dump(exclude_none=True)
                        )

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
    host: str = "github.com",
    per_page: int | None = None,
    max_pages: int | None = None,
    max_comments: int | None = None,
    max_retries: int | None = None,
) -> list[CommentResult] | None:
    """
    Fetch and combine review comments for a pull request by iterating
    the repository REST API pagination.

    Parameters:
        per_page (int | None): Override for number of comments to
            request per page.
        max_pages (int | None): Override for maximum number of pages
            to fetch.
        max_comments (int | None): Override for a hard limit on total
            comments to collect.
        max_retries (int | None): Override for maximum retry attempts
            on transient errors.

    Returns:
        list[CommentResult] with comments combined from all fetched
            pages, or `None` when fetching fails due to timeouts or
            unrecoverable server errors.
    """
    print(f"Fetching comments for {owner}/{repo}#{pull_number}", file=sys.stderr)
    token = os.getenv("GITHUB_TOKEN")
    headers: dict[str, str] = {
        "Accept": GITHUB_ACCEPT_HEADER,
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
        "User-Agent": GITHUB_USER_AGENT,
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

    api_base = api_base_for_host(host)
    base_url = (
        f"{api_base}/repos/"
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
            had_server_error = False
            while url:
                print(f"Fetching page {page_count + 1}...", file=sys.stderr)

                # Status handler for REST-specific logic (rate limiting, auth fallback)
                async def handle_rest_status(
                    resp: httpx.Response, attempt: int
                ) -> str | None:
                    nonlocal used_token_fallback, had_server_error

                    # Track 5xx errors for conservative failure behavior
                    if 500 <= resp.status_code < 600:
                        had_server_error = True

                    # 401 Bearer token fallback
                    if (
                        resp.status_code == 401
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
                        return "retry"

                    # Rate limiting
                    if resp.status_code in (429, 403):
                        retry_after_header = resp.headers.get("Retry-After")
                        remaining = resp.headers.get("X-RateLimit-Remaining")
                        reset = resp.headers.get("X-RateLimit-Reset")

                        if retry_after_header or remaining == "0":
                            retry_after = 60
                            try:
                                if retry_after_header:
                                    retry_after = int(retry_after_header)
                                elif reset:
                                    import time

                                    now = int(time.time())
                                    retry_after = max(int(reset) - now, 1)
                            except (ValueError, TypeError):
                                retry_after = 60

                            print(
                                f"Rate limited. Backing off for {retry_after}s...",
                                file=sys.stderr,
                            )
                            await asyncio.sleep(retry_after)
                            return "retry"

                    return None

                # Use retry helper with custom status handler (capture loop variable)
                current_page_url = url  # Captured by while loop type narrowing

                async def make_rest_request(
                    page_url: str = current_page_url,
                ) -> httpx.Response:
                    return await client.get(page_url, headers=headers)

                try:
                    response = await _retry_http_request(
                        make_rest_request,
                        max_retries_v,
                        status_handler=handle_rest_status,
                    )
                except httpx.HTTPStatusError as e:
                    # On exhausted 5xx retries, return None per test expectations
                    if 500 <= e.response.status_code < 600:
                        return None
                    raise

                # Conservative behavior: return None if any server error occurred,
                # even if retry succeeded
                if had_server_error:
                    return None

                # Process page
                page_comments = response.json()
                if not isinstance(page_comments, list) or not all(
                    isinstance(c, dict) for c in page_comments
                ):
                    return None
                # Convert REST comments using Pydantic model
                for comment in page_comments:
                    review_comment_model = ReviewCommentModel.from_rest(comment)
                    all_comments.append(
                        review_comment_model.model_dump(exclude_none=True)
                    )
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
                if next_url:
                    url = next_url
                else:
                    break

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

    markdown = "# Pull Request Review Comments\n\n"
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


T = TypeVar("T")


class PRReviewServer:
    def __init__(self) -> None:
        self.server = server.Server("github_pr_review")
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
                    "Fetches all review comments from a GitHub PR, including "
                    "resolution status, outdated flags, and diff context. Returns "
                    "formatted Markdown by default (optimized for LLM consumption), "
                    "or JSON for programmatic use. Automatically detects PR from "
                    "current git branch if URL omitted."
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
                    "Finds and returns the URL of an open pull request that "
                    "matches the current git branch. Uses git metadata to detect "
                    "repo owner, name, and branch, then queries GitHub to find "
                    "the associated PR. Supports GitHub Enterprise via host "
                    "parameter. Optionally override detection with explicit "
                    "parameters."
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
                        "host": {
                            "type": "string",
                            "description": (
                                "GitHub host (e.g., 'github.com' or "
                                "'github.enterprise.com'). If not provided, "
                                "detected from git context or defaults to github.com"
                            ),
                        },
                    },
                },
            ),
        ]

    async def handle_call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> Sequence[TextContent]:
        """
        Dispatch a tool invocation by name and return its textual outputs.

        Parameters:
            name (str): The tool identifier to invoke (e.g.,
                "fetch_pr_review_comments", "resolve_open_pr_url").
            arguments (dict[str, Any]): Tool-specific arguments; expected keys
                depend on `name` (for example, "pr_url", "per_page",
                "max_pages", "max_comments", "max_retries",
                "select_strategy", "owner", "repo", "branch", and "output" for
                "fetch_pr_review_comments").

        Returns:
            Sequence[TextContent]: One or more text outputs produced by the
            invoked tool (e.g., markdown and/or JSON).

        Raises:
            ValueError: If `name` is unknown or if provided arguments fail
                validation.
            RuntimeError: If an underlying HTTP or OS error occurs while
                executing the requested tool.
        """

        async def _run_with_handling(operation: Callable[[], Awaitable[T]]) -> T:
            try:
                return await operation()
            except ValueError:
                raise
            except (httpx.HTTPError, OSError, RuntimeError, TypeError) as exc:
                error_msg = f"Error executing tool {name}: {exc}"
                print(error_msg, file=sys.stderr)
                traceback.print_exc(file=sys.stderr)
                raise RuntimeError(error_msg) from exc

        if name == "fetch_pr_review_comments":
            # Validate arguments using Pydantic model
            try:
                validated_args = FetchPRReviewCommentsArgs.model_validate(arguments)
            except ValidationError as e:
                # Transform Pydantic validation errors to ValueError
                errors = e.errors()
                if errors:
                    first_error = errors[0]
                    field = first_error["loc"][0] if first_error["loc"] else "unknown"
                    msg = first_error["msg"]
                    error_type = first_error["type"]

                    # Handle different error types
                    if error_type == "value_error":
                        # This is from our custom model_validator
                        # Check if it's our bool/float rejection
                        if "Invalid type: expected integer" in msg:
                            # Determine which field by checking the arguments
                            for field_name in [
                                "per_page",
                                "max_pages",
                                "max_comments",
                                "max_retries",
                            ]:
                                value = arguments.get(field_name)
                                if value is not None and (
                                    isinstance(value, bool) or isinstance(value, float)
                                ):
                                    err = f"Invalid type for {field_name}"
                                    raise ValueError(
                                        f"{err}: expected integer"
                                    ) from None
                        raise ValueError(msg) from None
                    if error_type == "literal_error":
                        # Output field validation - use custom message
                        raise ValueError(
                            f"Invalid {field}: must be 'markdown', 'json', or 'both'"
                        ) from None
                    if "int_parsing" in error_type or "int_type" in error_type:
                        raise ValueError(
                            f"Invalid type for {field}: expected integer"
                        ) from None
                    if (
                        "greater_than_equal" in error_type
                        or "less_than_equal" in error_type
                    ):
                        # Range validation error
                        raise ValueError(
                            f"Invalid value for {field}: must be between 1 and 100"
                        ) from None
                    raise ValueError(f"Invalid value for {field}: {msg}") from None
                raise ValueError("Invalid arguments") from None

            # Extract validated arguments
            args_dict = validated_args.model_dump(exclude_none=True)

            comments = await _run_with_handling(
                lambda: self.fetch_pr_review_comments(
                    pr_url=args_dict.get("pr_url"),
                    per_page=args_dict.get("per_page"),
                    max_pages=args_dict.get("max_pages"),
                    max_comments=args_dict.get("max_comments"),
                    max_retries=args_dict.get("max_retries"),
                    select_strategy=args_dict.get("select_strategy"),
                    owner=args_dict.get("owner"),
                    repo=args_dict.get("repo"),
                    branch=args_dict.get("branch"),
                )
            )

            output = args_dict.get("output", "markdown")

            # Build responses according to requested format (default markdown)
            results: list[TextContent] = []
            if output in ("json", "both"):
                results.append(TextContent(type="text", text=json.dumps(comments)))
            if output in ("markdown", "both"):
                try:
                    md = generate_markdown(comments)
                except (AttributeError, KeyError, TypeError, IndexError) as exc:
                    traceback.print_exc(file=sys.stderr)
                    md = f"# Error\n\nFailed to generate markdown from comments: {exc}"
                results.append(TextContent(type="text", text=md))
            return results

        if name == "resolve_open_pr_url":
            # Validate arguments using Pydantic model
            try:
                validated_args_resolve = ResolveOpenPrUrlArgs.model_validate(arguments)
            except ValidationError as e:
                # Transform Pydantic validation errors to ValueError
                errors = e.errors()
                if errors:
                    first_error = errors[0]
                    field = first_error["loc"][0] if first_error["loc"] else "unknown"
                    msg = first_error["msg"]
                    raise ValueError(f"Invalid value for {field}: {msg}") from e
                raise ValueError("Invalid arguments") from e

            # Extract validated arguments
            args_dict_resolve = validated_args_resolve.model_dump(exclude_none=True)

            owner = args_dict_resolve.get("owner")
            repo = args_dict_resolve.get("repo")
            branch = args_dict_resolve.get("branch")
            host = args_dict_resolve.get("host")
            select_strategy = args_dict_resolve.get("select_strategy", "branch")

            if not (owner and repo and branch):
                ctx = git_detect_repo_branch()
                owner = owner or ctx.owner
                repo = repo or ctx.repo
                branch = branch or ctx.branch
                host = host or ctx.host

            resolved_url = await _run_with_handling(
                lambda: resolve_pr_url(
                    owner=owner or "",
                    repo=repo or "",
                    branch=branch,
                    select_strategy=select_strategy,
                    host=host,
                )
            )
            return [TextContent(type="text", text=resolved_url)]

        raise ValueError(f"Unknown tool: {name}")

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
        Fetch all review comments for a pull request, resolving the PR
        URL if not provided.

        If pr_url is None, the function attempts to resolve the open PR
        URL using the provided select_strategy, owner, repo, and branch.
        The function parses the PR URL to determine host/owner/repo/pull
        number, queries the repository's GraphQL API to retrieve review
        comments (including resolution/outdated metadata), and returns
        the collected comments. On parse errors or other ValueError
        conditions, returns a single error object.

        Parameters:
            pr_url (str | None): Full GitHub pull request URL to fetch
                comments from. If None, the function will attempt to
                resolve the current PR URL.
            per_page (int | None): (Accepted but not used by this
                implementation) Page size hint for REST pagination.
            max_pages (int | None): (Accepted but not used by this
                implementation) Maximum pages to request when using
                REST.
            max_comments (int | None): Maximum number of comments to
                fetch; honored by the underlying fetcher.
            max_retries (int | None): Maximum retry attempts for
                network/HTTP errors; forwarded to the fetcher.
            select_strategy (str | None): Strategy used when resolving
                an open PR URL (e.g., "branch"); used only if pr_url
                is None.
            owner (str | None): Repository owner to use when resolving
                the PR URL if pr_url is None.
            repo (str | None): Repository name to use when resolving
                the PR URL if pr_url is None.
            branch (str | None): Branch name to use when resolving the
                PR URL if pr_url is None.

        Returns:
            list[CommentResult]: A list of review comment objects or
                error objects. If the fetch succeeds, each item is a
                ReviewComment; if a ValueError occurs while resolving
                or parsing the PR URL, returns a single ErrorMessage
                dict with an "error" key describing the problem.
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

            host, owner, repo, pull_number_str = get_pr_info(pr_url)
            pull_number = int(pull_number_str)
            # Use GraphQL API to get resolution and outdated status
            comments = await fetch_pr_comments_graphql(
                owner,
                repo,
                pull_number,
                host=host,
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
                    server_name="github_pr_review",
                    server_version=__version__,
                    capabilities=capabilities,
                ),
            )


def create_server() -> PRReviewServer:
    """Factory for a PRReviewServer instance."""

    return PRReviewServer()


if __name__ == "__main__":
    server_instance = create_server()
    asyncio.run(server_instance.run())
