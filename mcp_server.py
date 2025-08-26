import asyncio
import os
import re
import sys
import traceback
import random
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import quote

import httpx
from dotenv import load_dotenv
from mcp import server
from mcp.server.models import InitializationOptions
from mcp.types import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    JSONRPCError,
    TextContent,
    Tool,
)

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
    return match.groups()


async def fetch_pr_comments(
    owner: str,
    repo: str,
    pull_number: int,
    *,
    per_page: int | None = None,
    max_pages: int | None = None,
    max_comments: int | None = None,
    max_retries: int | None = None,
) -> list[dict] | None:
    """Fetches all review comments for a given pull request with pagination support."""
    print(f"Fetching comments for {owner}/{repo}#{pull_number}", file=sys.stderr)
    token = os.getenv("GITHUB_TOKEN")
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "mcp-pr-review-spec-maker/1.0",
    }
    if token:
        # Use Bearer prefix for fine-grained tokens
        headers["Authorization"] = f"Bearer {token}"

    # URL-encode owner/repo to be safe, even though regex validation restricts format
    safe_owner = quote(owner, safe="")
    safe_repo = quote(repo, safe="")
    # Load configurable limits from environment with safe defaults; allow per-call overrides
    def _int_conf(name: str, default: int, min_v: int, max_v: int, override: int | None) -> int:
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

    # Request page size according to config
    base_url = (
        f"https://api.github.com/repos/{safe_owner}/{safe_repo}/pulls/{pull_number}/comments?per_page={per_page_v}"
    )
    all_comments = []
    url = base_url
    page_count = 0
    MAX_PAGES = max_pages_v
    MAX_COMMENTS = max_comments_v

    try:
        # Set timeout for HTTP requests (30 seconds total, 10 seconds for connection)
        timeout = httpx.Timeout(timeout=30.0, connect=10.0)

        async with httpx.AsyncClient(timeout=timeout) as client:
            used_token_fallback = False
            while url:
                print(f"Fetching page {page_count + 1}...", file=sys.stderr)
                # Bounded retries with jitter for transient errors
                MAX_RETRIES = max_retries_v
                attempt = 0
                while True:
                    try:
                        response = await client.get(url, headers=headers)
                    except httpx.RequestError as e:
                        if attempt < MAX_RETRIES:
                            delay = min(5.0, (0.5 * (2**attempt)) + random.uniform(0, 0.25))
                            print(
                                f"Request error: {e}. Retrying in {delay:.2f}s...",
                                file=sys.stderr,
                            )
                            await asyncio.sleep(delay)
                            attempt += 1
                            continue
                        raise

                    # If unauthorized and we have a token, try classic PAT scheme fallback once
                    if (
                        response.status_code == 401
                        and token
                        and not used_token_fallback
                        and headers.get("Authorization", "").startswith("Bearer ")
                    ):
                        print(
                            "401 Unauthorized with Bearer; retrying with 'token' scheme...",
                            file=sys.stderr,
                        )
                        headers["Authorization"] = f"token {token}"
                        used_token_fallback = True
                        # retry current URL immediately
                        continue

                # Basic rate-limit handling for GitHub API
                if response.status_code in (429, 403):
                    retry_after_header = response.headers.get("Retry-After")
                    remaining = response.headers.get("X-RateLimit-Remaining")
                    reset = response.headers.get("X-RateLimit-Reset")

                    # If explicitly told to wait, or if remaining is 0, back off
                    if retry_after_header or remaining == "0":
                        try:
                            if retry_after_header:
                                retry_after = int(retry_after_header)
                            elif reset:
                                # Sleep until reset epoch if provided
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

                # For non-rate-limit server errors (5xx), retry with backoff up to MAX_RETRIES
                if 500 <= response.status_code < 600 and attempt < MAX_RETRIES:
                    delay = min(5.0, (0.5 * (2**attempt)) + random.uniform(0, 0.25))
                    print(
                        f"Server error {response.status_code}. Retrying in {delay:.2f}s...",
                        file=sys.stderr,
                    )
                    await asyncio.sleep(delay)
                    attempt += 1
                    continue

                # For other errors, raise
                response.raise_for_status()

                page_comments = response.json()
                all_comments.extend(page_comments)
                page_count += 1
                # reset attempt counter after a successful page
                attempt = 0

                # Enforce safety bounds to prevent unbounded memory/time use
                if page_count >= MAX_PAGES or len(all_comments) >= MAX_COMMENTS:
                    print(
                        "Reached safety limits for pagination; stopping early",
                        file=sys.stderr,
                    )
                    break

                # Check for next page using Link header
                link_header = response.headers.get("Link")
                next_url: str | None = None

                if link_header:
                    # Safer Link header parsing
                    match = re.search(r'<([^>]+)>;\s*rel=\"next\"', link_header)
                    next_url = match.group(1) if match else None

                url = next_url

            total_comments = len(all_comments)
            print(
                f"Successfully fetched {total_comments} comments "
                f"across {page_count} pages",
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


def generate_markdown(comments: list[dict]) -> str:
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
        markdown += (
            f"## Review Comment by {comment.get('user', {}).get('login', 'N/A')}\n\n"
        )
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
    def __init__(self):
        self.server = server.Server("github_review_spec_generator")
        print("MCP Server initialized", file=sys.stderr)
        self._register_handlers()

    def _register_handlers(self):
        """Register MCP handlers."""
        self.server.list_tools = self.handle_list_tools
        self.server.call_tool = self.handle_call_tool

    async def handle_list_tools(self) -> list[Tool]:
        """
        List available tools.
        Each tool is defined as a Tool object containing name, description,
        and parameters.
        """
        return [
            Tool(
                name="fetch_pr_review_comments",
                description="Fetches all review comments from a GitHub PR URL",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "pr_url": {
                            "type": "string",
                            "description": "The full URL of the GitHub pull request",
                        },
                        "per_page": {
                            "type": "integer",
                            "description": "GitHub API page size (1-100)",
                            "minimum": 1,
                            "maximum": 100,
                        },
                        "max_pages": {
                            "type": "integer",
                            "description": "Max number of pages to fetch (server-capped)",
                            "minimum": 1,
                            "maximum": 200,
                        },
                        "max_comments": {
                            "type": "integer",
                            "description": "Max total comments to collect (server-capped)",
                            "minimum": 100,
                            "maximum": 100000,
                        },
                        "max_retries": {
                            "type": "integer",
                            "description": "Max retries for transient errors (server-capped)",
                            "minimum": 0,
                            "maximum": 10,
                        },
                    },
                    "required": ["pr_url"],
                },
            ),
            Tool(
                name="create_review_spec_file",
                description="Creates a markdown file from a list of review comments",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "comments": {
                            "type": "array",
                            "description": "Comments from fetch_pr_review_comments",
                        },
                        "filename": {
                            "type": "string",
                            "description": "Basename for the markdown file (optional). If omitted, a unique name like spec-YYYYmmdd-HHMMSS-xxxx.md is used.",
                        },
                    },
                    "required": ["comments"],
                },
            ),
        ]

    async def handle_call_tool(
        self, name: str, arguments: dict
    ) -> Sequence[TextContent]:
        """
        Handle tool calls.
        Each tool call is routed to the appropriate method based on the tool name.
        """
        try:
            if name == "fetch_pr_review_comments":
                if "pr_url" not in arguments:
                    raise JSONRPCError(
                        INVALID_PARAMS, "Missing pr_url parameter", data=None
                    )

                # Validate optional numeric parameters
                def _validate_int(name: str, value, min_v: int, max_v: int) -> int:
                    if value is None:
                        return None  # type: ignore[return-value]
                    if isinstance(value, bool) or not isinstance(value, int):
                        raise JSONRPCError(
                            INVALID_PARAMS,
                            f"Invalid type for {name}: expected integer",
                            data=None,
                        )
                    if not (min_v <= value <= max_v):
                        raise JSONRPCError(
                            INVALID_PARAMS,
                            f"Invalid value for {name}: must be between {min_v} and {max_v}",
                            data=None,
                        )
                    return value

                per_page = _validate_int(
                    "per_page", arguments.get("per_page"), PER_PAGE_MIN, PER_PAGE_MAX
                )
                max_pages = _validate_int(
                    "max_pages", arguments.get("max_pages"), MAX_PAGES_MIN, MAX_PAGES_MAX
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
                    arguments["pr_url"],
                    per_page=per_page,
                    max_pages=max_pages,
                    max_comments=max_comments,
                    max_retries=max_retries,
                )
                return [TextContent(type="text", text=str(comments))]

            elif name == "create_review_spec_file":
                if "comments" not in arguments:
                    raise JSONRPCError(
                        INVALID_PARAMS, "Missing comments parameter", data=None
                    )

                filename = arguments.get("filename", "spec.md")
                result = await self.create_review_spec_file(
                    arguments["comments"], filename
                )
                return [TextContent(type="text", text=result)]

            else:
                raise JSONRPCError(INVALID_PARAMS, f"Unknown tool: {name}", data=None)

        except JSONRPCError:
            raise
        except Exception as e:
            error_msg = f"Error executing tool {name}: {str(e)}"
            print(error_msg, file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            raise JSONRPCError(INTERNAL_ERROR, error_msg, data=None) from e

    async def fetch_pr_review_comments(
        self,
        pr_url: str,
        *,
        per_page: int | None = None,
        max_pages: int | None = None,
        max_comments: int | None = None,
        max_retries: int | None = None,
    ) -> list:
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
        self, comments: list, filename: str | None = None
    ) -> str:
        """
        Creates a markdown file from a list of review comments.

        :param comments: A list of comment objects from fetch_pr_review_comments.
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
                from datetime import datetime
                import secrets

                ts = datetime.now().strftime("%Y%m%d-%H%M%S")
                suffix = secrets.token_hex(2)  # 4 hex chars
                filename = f"spec-{ts}-{suffix}.md"

            # Enforce a conservative filename policy: basename only, .md extension
            if os.path.isabs(filename) or any(sep in filename for sep in ("/", "\\")):
                raise ValueError("Invalid filename: path separators are not allowed")
            if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}\.md", filename):
                raise ValueError("Invalid filename: must match [A-Za-z0-9._-]{1,80} and end with .md")

            output_path = (output_dir / filename).resolve()
            # Ensure the resolved path is within the output directory
            try:
                output_path.relative_to(output_dir.resolve())
            except ValueError:
                raise ValueError("Invalid filename: path escapes output directory")

            markdown_content = generate_markdown(comments)

            # Perform an exclusive, no-follow create to avoid clobbering and symlinks
            async def _write_safely(path: Path, content: str) -> None:
                def _write_blocking() -> None:
                    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                    if hasattr(os, "O_NOFOLLOW"):
                        flags |= os.O_NOFOLLOW
                    fd = os.open(path, flags, 0o600)
                    with os.fdopen(fd, "w", encoding="utf-8") as fh:
                        fh.write(content)

                return asyncio.to_thread(_write_blocking)

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

    async def run(self):
        """Start the MCP server."""
        try:
            print("Running MCP Server...", file=sys.stderr)
            # Import stdio here to avoid potential issues with event loop
            from mcp.server.stdio import stdio_server

            async with stdio_server() as (read_stream, write_stream):
                await self.server.run(
                    read_stream,
                    write_stream,
                    InitializationOptions(
                        server_name="github_review_spec_generator",
                        server_version="1.0.0",
                        capabilities=self.server.get_capabilities(),
                    ),
                )
        except Exception as e:
            print(f"Fatal Error in MCP Server: {str(e)}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    server_instance = ReviewSpecGenerator()
    asyncio.run(server_instance.run())
