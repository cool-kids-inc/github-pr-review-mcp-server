from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from conftest import assert_auth_header_present, create_mock_response

from mcp_server import (
    ReviewSpecGenerator,
    fetch_pr_comments,
    generate_markdown,
)


def test_generate_markdown_no_comments() -> None:
    """Should handle empty comment list."""
    result = generate_markdown([])
    assert result == "# Pull Request Review Spec\n\nNo comments found.\n"


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
async def test_fetch_pr_review_comments_invalid_url(
    mcp_server: ReviewSpecGenerator,
) -> None:
    comments = await mcp_server.fetch_pr_review_comments(
        "https://github.com/owner/repo/issues/1"
    )
    assert comments and "error" in comments[0]


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
