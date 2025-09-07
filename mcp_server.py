import asyncio
import json
import os
import random
import re
import sys
import traceback
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast
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

# Parameter ranges (keep in sync with env clamping)
PER_PAGE_MIN, PER_PAGE_MAX = 1, 100
MAX_PAGES_MIN, MAX_PAGES_MAX = 1, 200
MAX_COMMENTS_MIN, MAX_COMMENTS_MAX = 100, 100000
MAX_RETRIES_MIN, MAX_RETRIES_MAX = 0, 10


# Helper functions can remain at the module level as they are pure functions.
def get_pr_info(pr_url: str) -> tuple[str, str, str]:
    """Parses a GitHub PR URL to extract owner, repo, and pull number."""
    pattern = r"https://github\.com/([^/]+)/([^/]+)/pull/(\d+)$"
    match = re.match(pattern, pr_url)
    if not match:
        raise ValueError(
            "Invalid PR URL format. Expected format: https://github.com/owner/repo/pull/123"
        )
    groups = match.groups()
    assert len(groups) == 3
    owner, repo, num = groups[0], groups[1], groups[2]
    return owner, repo, num


async def fetch_pr_comments(
    owner: str,
    repo: str,
    pull_number: int,
    *,
    per_page: int | None = None,
    max_pages: int | None = None,
    max_comments: int | None = None,
    max_retries: int | None = None,
) -> list[dict[str, Any]] | None:
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
    def _int_conf(
        name: str, default: int, min_v: int, max_v: int, override: int | None
    ) -> int:
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

    per_page_v = _int_conf("HTTP_PER_PAGE", 100, 1, 100, per_page)
    max_pages_v = _int_conf("PR_FETCH_MAX_PAGES", 50, 1, 200, max_pages)
    max_comments_v = _int_conf("PR_FETCH_MAX_COMMENTS", 2000, 100, 100000, max_comments)
    max_retries_v = _int_conf("HTTP_MAX_RETRIES", 3, 0, 10, max_retries)

    base_url = (
        "https://api.github.com/repos/"
        f"{safe_owner}/{safe_repo}/pulls/{pull_number}/comments?per_page={per_page_v}"
    )
    all_comments: list[dict[str, Any]] = []
    url: str | None = base_url
    page_count = 0

    try:
        timeout = httpx.Timeout(timeout=30.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            used_token_fallback = False
            while url:
                print(f"Fetching page {page_count + 1}...", file=sys.stderr)
                attempt = 0
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

                    # Success path
                    break

                # Process page
                page_comments = response.json()
                all_comments.extend(page_comments)
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
        return None


def generate_markdown(comments: list[dict[str, Any]]) -> str:
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
        user = comment.get("user")
        user_login = user.get("login", "N/A") if isinstance(user, dict) else "N/A"
        markdown += f"## Review Comment by {user_login}\n\n"
        markdown += f"**File:** `{comment.get('path', 'N/A')}`\n"
        markdown += f"**Line:** {comment.get('line', 'N/A')}\n\n"
        body = comment.get("body", "")
        body_fence = fence_for(body)
        markdown += f"**Comment:**\n{body_fence}\n{body}\n{body_fence}\n\n"
        if "diff_hunk" in comment:
            diff_text = comment["diff_hunk"]
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
                                "Output format. Default 'json'. Use 'markdown' for "
                                "formatted output; 'both' returns json then markdown."
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
            Tool(
                name="create_review_spec_file",
                description=(
                    "Create a markdown file from comments or pre-rendered markdown. "
                    "Provide 'markdown' (preferred) or 'comments'."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "comments": {
                            "type": "array",
                            "description": (
                                "Raw comments from fetch_pr_review_comments (legacy). "
                                "If 'markdown' is provided, it takes precedence."
                            ),
                        },
                        "markdown": {
                            "type": "string",
                            "description": (
                                "Pre-rendered markdown to write (e.g., from "
                                "fetch_pr_review_comments with output='markdown')."
                            ),
                        },
                        "filename": {
                            "type": "string",
                            "description": (
                                "Basename for the markdown file (optional). "
                                "If omitted, a unique name like "
                                "spec-YYYYmmdd-HHMMSS-xxxx.md is used."
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
                output = arguments.get("output") or "json"
                if output not in ("markdown", "json", "both"):
                    raise ValueError(
                        "Invalid output: must be 'markdown', 'json', or 'both'"
                    )

                # Build responses according to requested format (default json)
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

            elif name == "create_review_spec_file":
                if "markdown" not in arguments and "comments" not in arguments:
                    raise ValueError("Missing input: provide 'markdown' or 'comments'")

                filename = arguments.get("filename", "spec.md")
                if "markdown" in arguments and arguments["markdown"]:
                    # Write provided markdown directly
                    result = await self.create_review_spec_file(
                        arguments["markdown"],
                        filename,
                    )
                else:
                    result = await self.create_review_spec_file(
                        arguments["comments"], filename
                    )
                return [TextContent(type="text", text=result)]

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
    ) -> list[dict[str, Any]]:
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
            comments = await fetch_pr_comments(
                owner,
                repo,
                pull_number,
                per_page=per_page,
                max_pages=max_pages,
                max_comments=max_comments,
                max_retries=max_retries,
            )
            return comments if comments is not None else []
        except ValueError as e:
            error_msg = f"Error in fetch_pr_review_comments: {str(e)}"
            print(error_msg, file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            return [{"error": error_msg}]

    async def create_review_spec_file(
        self,
        comments_or_markdown: list[dict[str, Any]] | str,
        filename: str | None = None,
    ) -> str:
        """
        Creates a markdown file from a list of review comments.

        :param comments: A list of comment objects from fetch_pr_review_comments,
                         or a JSON/Python-literal string representing that list.
        :param filename: The name of the markdown file to create.
        :return: A success or error message.
        """
        print(
            f"Tool 'create_review_spec_file' called for filename: {filename}",
            file=sys.stderr,
        )
        try:
            # Constrain output to a safe directory and validate/generate filename
            output_dir = Path.cwd() / "review_specs"
            output_dir.mkdir(parents=True, exist_ok=True)

            # Generate a unique default filename if not provided
            if not filename:
                import secrets
                from datetime import datetime

                ts = datetime.now().strftime("%Y%m%d-%H%M%S")
                suffix = secrets.token_hex(2)  # 4 hex chars
                filename = f"spec-{ts}-{suffix}.md"

            # Enforce a conservative filename policy: basename only, .md extension
            if os.path.isabs(filename) or any(sep in filename for sep in ("/", "\\")):
                raise ValueError("Invalid filename: path separators are not allowed")
            if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}\.md", filename):
                raise ValueError(
                    "Invalid filename: must match [A-Za-z0-9._-]{1,80} and end with .md"
                )

            output_path = (output_dir / filename).resolve()
            # Ensure the resolved path is within the output directory
            try:
                output_path.relative_to(output_dir.resolve())
            except ValueError as err:
                raise ValueError(
                    "Invalid filename: path escapes output directory"
                ) from err

            # Accept either pre-rendered markdown (preferred) or raw comments
            if isinstance(comments_or_markdown, str):
                markdown_content = comments_or_markdown
            else:
                # Validate element types
                if not all(isinstance(c, dict) for c in comments_or_markdown):
                    raise ValueError("Invalid comments payload: items must be objects")
                markdown_content = generate_markdown(comments_or_markdown)

            # Perform an exclusive, no-follow create to avoid clobbering and symlinks
            async def _write_safely(path: Path, content: str) -> None:
                def _write_blocking() -> None:
                    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                    if hasattr(os, "O_NOFOLLOW"):
                        flags |= os.O_NOFOLLOW
                    fd = os.open(path, flags, 0o600)
                    with os.fdopen(fd, "w", encoding="utf-8") as fh:
                        fh.write(content)

                return await asyncio.to_thread(_write_blocking)

            await _write_safely(output_path, markdown_content)

            success_msg = f"Successfully created spec file: {output_path}"
            print(success_msg, file=sys.stderr)
            return success_msg
        except OSError as e:
            error_msg = f"Error in create_review_spec_file: {str(e)}"
            print(error_msg, file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            return error_msg
        except ValueError as e:
            error_msg = f"Error in create_review_spec_file: {str(e)}"
            print(error_msg, file=sys.stderr)
            return error_msg

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
