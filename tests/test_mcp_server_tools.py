import json
from types import SimpleNamespace, TracebackType
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from conftest import assert_auth_header_present, create_mock_response
from mcp.types import TextContent

from mcp_server import (
    ReviewSpecGenerator,
    fetch_pr_comments,
    generate_markdown,
)


def test_generate_markdown_no_comments() -> None:
    """Should handle empty comment list."""
    result = generate_markdown([])
    assert result == "# Pull Request Review Spec\n\nNo comments found.\n"


def test_generate_markdown_skips_error_entries() -> None:
    """Should skip error entries when generating markdown."""
    result = generate_markdown(
        [
            {"error": "API failure"},
            {
                "user": {"login": "dev"},
                "path": "file.py",
                "line": 1,
                "body": "Looks good",
                "diff_hunk": "@@\n+code\n",
            },
        ]
    )
    assert "API failure" not in result
    assert "Review Comment by dev" in result


@pytest.mark.asyncio
async def test_handle_list_tools(mcp_server: ReviewSpecGenerator) -> None:
    tools = await mcp_server.handle_list_tools()
    names = {tool.name for tool in tools}
    assert {
        "fetch_pr_review_comments",
        "resolve_open_pr_url",
    } <= names


@pytest.mark.asyncio
async def test_handle_call_tool_unknown(mcp_server: ReviewSpecGenerator) -> None:
    with pytest.raises(ValueError, match="Unknown tool"):
        await mcp_server.handle_call_tool("nonexistent_tool", {})


@pytest.mark.asyncio
async def test_handle_call_tool_invalid_type(mcp_server: ReviewSpecGenerator) -> None:
    with pytest.raises(ValueError, match="Invalid type for per_page"):
        await mcp_server.handle_call_tool(
            "fetch_pr_review_comments",
            {"pr_url": "https://github.com/o/r/pull/1", "per_page": "ten"},
        )


@pytest.mark.asyncio
async def test_handle_call_tool_rejects_bool(mcp_server: ReviewSpecGenerator) -> None:
    """Test that boolean values are rejected for integer parameters."""
    with pytest.raises(ValueError, match="Invalid type for per_page: expected integer"):
        await mcp_server.handle_call_tool(
            "fetch_pr_review_comments",
            {"pr_url": "https://github.com/o/r/pull/1", "per_page": True},
        )


@pytest.mark.asyncio
async def test_handle_call_tool_rejects_float(mcp_server: ReviewSpecGenerator) -> None:
    """Test that float values are rejected to prevent silent truncation."""
    with pytest.raises(ValueError, match="Invalid type for per_page: expected integer"):
        await mcp_server.handle_call_tool(
            "fetch_pr_review_comments",
            {"pr_url": "https://github.com/o/r/pull/1", "per_page": 50.7},
        )


@pytest.mark.asyncio
async def test_handle_call_tool_invalid_output(mcp_server: ReviewSpecGenerator) -> None:
    """
    Validates that handle_call_tool rejects unsupported output formats.

    Asserts that calling handle_call_tool with an invalid `output` value
    raises a ValueError whose message contains "Invalid output".
    """
    with pytest.raises(ValueError, match="Invalid output"):
        await mcp_server.handle_call_tool(
            "fetch_pr_review_comments",
            {"pr_url": "https://github.com/o/r/pull/1", "output": "text"},
        )


@pytest.mark.asyncio
async def test_handle_call_tool_invalid_range(mcp_server: ReviewSpecGenerator) -> None:
    with pytest.raises(ValueError, match="Invalid value for per_page"):
        await mcp_server.handle_call_tool(
            "fetch_pr_review_comments",
            {"pr_url": "https://github.com/o/r/pull/1", "per_page": 0},
        )


@pytest.mark.asyncio
async def test_fetch_pr_review_comments_success(
    monkeypatch: pytest.MonkeyPatch,
    mcp_server: ReviewSpecGenerator,
) -> None:
    async def mock_fetch(*args: Any, **kwargs: Any) -> list[dict]:
        return [{"id": 1}]

    monkeypatch.setattr("mcp_server.fetch_pr_comments_graphql", mock_fetch)
    comments = await mcp_server.fetch_pr_review_comments(
        "https://github.com/a/b/pull/1", per_page=10
    )
    assert comments == [{"id": 1}]


@pytest.mark.asyncio
async def test_handle_call_tool_fetch_output_both(
    monkeypatch: pytest.MonkeyPatch,
    mcp_server: ReviewSpecGenerator,
) -> None:
    async def mock_fetch(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return [
            {
                "user": {"login": "alice"},
                "path": "file.py",
                "line": 12,
                "body": "Note",
                "diff_hunk": "@@\n+code\n",
            }
        ]

    monkeypatch.setattr(mcp_server, "fetch_pr_review_comments", mock_fetch)

    result = await mcp_server.handle_call_tool(
        "fetch_pr_review_comments",
        {"pr_url": "https://github.com/a/b/pull/1", "output": "both"},
    )

    assert len(result) == 2
    json_text = result[0].text
    markdown_text = result[1].text
    assert json.loads(json_text)[0]["path"] == "file.py"
    assert "Review Comment by alice" in markdown_text


@pytest.mark.asyncio
async def test_fetch_pr_review_comments_invalid_url(
    mcp_server: ReviewSpecGenerator,
) -> None:
    comments = await mcp_server.fetch_pr_review_comments(
        "https://github.com/owner/repo/issues/1"
    )
    assert comments and "error" in comments[0]


@pytest.mark.asyncio
async def test_handle_call_tool_passes_numeric_overrides(
    monkeypatch: pytest.MonkeyPatch,
    mcp_server: ReviewSpecGenerator,
) -> None:
    captured: dict[str, Any] = {}

    async def mock_fetch(
        pr_url: str,
        *,
        per_page: int | None,
        max_pages: int | None,
        max_comments: int | None,
        max_retries: int | None,
        select_strategy: str | None,
        owner: str | None,
        repo: str | None,
        branch: str | None,
    ) -> list[dict[str, Any]]:
        captured.update(
            {
                "pr_url": pr_url,
                "per_page": per_page,
                "max_pages": max_pages,
                "max_comments": max_comments,
                "max_retries": max_retries,
            }
        )
        return []

    monkeypatch.setattr(mcp_server, "fetch_pr_review_comments", mock_fetch)

    result = await mcp_server.handle_call_tool(
        "fetch_pr_review_comments",
        {
            "pr_url": "https://github.com/o/r/pull/1",
            "per_page": 5,
            "max_pages": 10,
            "max_comments": 200,
            "max_retries": 2,
            "output": "json",
        },
    )

    assert captured == {
        "pr_url": "https://github.com/o/r/pull/1",
        "per_page": 5,
        "max_pages": 10,
        "max_comments": 200,
        "max_retries": 2,
    }
    assert result[0].text == "[]"


@pytest.mark.asyncio
async def test_fetch_pr_review_comments_auto_resolve(
    monkeypatch: pytest.MonkeyPatch,
    mcp_server: ReviewSpecGenerator,
) -> None:
    resolver_response = [TextContent(type="text", text="https://github.com/o/r/pull/3")]
    resolve_mock = AsyncMock(return_value=resolver_response)
    monkeypatch.setattr(mcp_server, "handle_call_tool", resolve_mock)

    async def mock_fetch(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:  # noqa: ARG001
        return [{"id": 1}]

    monkeypatch.setattr("mcp_server.fetch_pr_comments_graphql", mock_fetch)

    comments = await mcp_server.fetch_pr_review_comments(None)

    assert resolve_mock.await_count == 1
    assert comments == [{"id": 1}]


@pytest.mark.asyncio
async def test_fetch_pr_review_comments_auto_resolve_uses_git_host(
    monkeypatch: pytest.MonkeyPatch,
    mcp_server: ReviewSpecGenerator,
) -> None:
    context = SimpleNamespace(
        host="enterprise.example.com",
        owner="ctx-owner",
        repo="ctx-repo",
        branch="ctx-branch",
    )
    monkeypatch.setattr("mcp_server.git_detect_repo_branch", lambda: context)

    async def fake_resolve_pr_url(
        owner: str,
        repo: str,
        branch: str | None = None,
        *,
        select_strategy: str = "branch",
        host: str | None = None,
        token: str | None = None,
    ) -> str:
        assert host == context.host
        assert owner == context.owner
        assert repo == context.repo
        assert branch == context.branch
        return f"https://{host}/{owner}/{repo}/pull/3"

    async def fake_fetch_pr_comments_graphql(
        owner: str,
        repo: str,
        pull_number: int,
        *,
        host: str,
        max_comments: int | None = None,
        max_retries: int | None = None,
    ) -> list[dict[str, Any]]:
        assert host == context.host
        assert owner == context.owner
        assert repo == context.repo
        assert pull_number == 3
        return [{"id": 1}]

    monkeypatch.setattr("mcp_server.resolve_pr_url", fake_resolve_pr_url)
    monkeypatch.setattr(
        "mcp_server.fetch_pr_comments_graphql", fake_fetch_pr_comments_graphql
    )

    comments = await mcp_server.fetch_pr_review_comments(
        None,
        select_strategy="branch",
    )

    assert comments == [{"id": 1}]


@pytest.mark.asyncio
async def test_handle_call_tool_handles_markdown_generation_errors(
    monkeypatch: pytest.MonkeyPatch,
    mcp_server: ReviewSpecGenerator,
) -> None:
    async def mock_fetch(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:  # noqa: ARG001
        return []

    def explode(comments: Any) -> str:  # noqa: ARG001
        raise TypeError("boom")

    monkeypatch.setattr(mcp_server, "fetch_pr_review_comments", mock_fetch)
    monkeypatch.setattr("mcp_server.generate_markdown", explode)

    result = await mcp_server.handle_call_tool(
        "fetch_pr_review_comments",
        {"pr_url": "https://github.com/o/r/pull/2"},
    )

    assert len(result) == 1
    assert result[0].text.startswith("# Error\n\nFailed to generate markdown")


@pytest.mark.asyncio
async def test_handle_call_tool_wraps_http_errors(
    monkeypatch: pytest.MonkeyPatch,
    mcp_server: ReviewSpecGenerator,
) -> None:
    async def failing_fetch(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:  # noqa: ARG001
        raise httpx.HTTPError("boom")

    monkeypatch.setattr(mcp_server, "fetch_pr_review_comments", failing_fetch)

    with pytest.raises(
        RuntimeError, match="Error executing tool fetch_pr_review_comments"
    ):
        await mcp_server.handle_call_tool(
            "fetch_pr_review_comments",
            {"pr_url": "https://github.com/o/r/pull/1"},
        )


@pytest.mark.asyncio
async def test_handle_call_tool_propagates_value_error(
    monkeypatch: pytest.MonkeyPatch,
    mcp_server: ReviewSpecGenerator,
) -> None:
    async def failing_fetch(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:  # noqa: ARG001
        raise ValueError("bad data")

    monkeypatch.setattr(mcp_server, "fetch_pr_review_comments", failing_fetch)

    with pytest.raises(ValueError, match="bad data"):
        await mcp_server.handle_call_tool(
            "fetch_pr_review_comments",
            {"pr_url": "https://github.com/o/r/pull/1"},
        )


@pytest.mark.asyncio
async def test_fetch_pr_comments_uses_auth_header(
    mock_http_client, github_token: str
) -> None:
    """fetch_pr_comments should send Authorization header when token is set."""
    mock_http_client.add_get_response(create_mock_response([]))

    await fetch_pr_comments("owner", "repo", 1)

    assert_auth_header_present(mock_http_client, github_token)


@pytest.mark.asyncio
async def test_fetch_pr_comments_propagates_request_error() -> None:
    """fetch_pr_comments should re-raise httpx.RequestError for network failures."""
    # Create a request error that would occur during network issues
    request_error = httpx.RequestError("Network connection failed")

    # Mock httpx.AsyncClient to raise RequestError on get()
    with patch("mcp_server.httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.get.side_effect = request_error
        mock_client_class.return_value.__aenter__.return_value = mock_client

        # The function should re-raise the RequestError
        with pytest.raises(httpx.RequestError, match="Network connection failed"):
            await fetch_pr_comments("owner", "repo", 1)


@pytest.mark.asyncio
async def test_handle_call_tool_resolve_pr(
    monkeypatch: pytest.MonkeyPatch,
    mcp_server: ReviewSpecGenerator,
) -> None:
    resolve_mock = AsyncMock(return_value="https://github.com/o/r/pull/7")
    monkeypatch.setattr("mcp_server.resolve_pr_url", resolve_mock)

    result = await mcp_server.handle_call_tool(
        "resolve_open_pr_url",
        {"owner": "o", "repo": "r", "branch": "feature"},
    )

    assert resolve_mock.await_count == 1
    assert result[0].text == "https://github.com/o/r/pull/7"


@pytest.mark.asyncio
async def test_handle_call_tool_resolve_pr_uses_git_context(
    monkeypatch: pytest.MonkeyPatch,
    mcp_server: ReviewSpecGenerator,
) -> None:
    context = SimpleNamespace(
        host="enterprise.example.com",
        owner="ctx-owner",
        repo="ctx-repo",
        branch="ctx-branch",
    )
    monkeypatch.setattr("mcp_server.git_detect_repo_branch", lambda: context)
    resolve_mock = AsyncMock(
        return_value="https://github.com/ctx-owner/ctx-repo/pull/9"
    )
    monkeypatch.setattr("mcp_server.resolve_pr_url", resolve_mock)

    result = await mcp_server.handle_call_tool("resolve_open_pr_url", {})

    assert resolve_mock.await_count == 1
    assert result[0].text.endswith("/pull/9")
    await_kwargs = resolve_mock.await_args.kwargs
    assert await_kwargs["host"] == "enterprise.example.com"


@pytest.mark.asyncio
async def test_review_server_run(monkeypatch: pytest.MonkeyPatch) -> None:
    server_instance = ReviewSpecGenerator()

    class DummyContext:
        async def __aenter__(self) -> tuple[str, str]:
            return ("read", "write")

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            tb: TracebackType | None,
        ) -> None:
            return None

    monkeypatch.setattr("mcp.server.stdio.stdio_server", lambda: DummyContext())

    run_mock = AsyncMock()
    monkeypatch.setattr(server_instance.server, "run", run_mock)
    monkeypatch.setattr(server_instance.server, "get_capabilities", lambda *a, **k: {})

    await server_instance.run()

    run_mock.assert_awaited_once()
