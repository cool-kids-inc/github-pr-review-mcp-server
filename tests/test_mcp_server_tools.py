from pathlib import Path
from typing import Any

import pytest
from conftest import create_mock_response

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
        "create_review_spec_file",
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
async def test_handle_call_tool_create_spec_missing_input(
    mcp_server: ReviewSpecGenerator,
) -> None:
    with pytest.raises(ValueError, match="Missing input"):
        await mcp_server.handle_call_tool("create_review_spec_file", {})


@pytest.mark.asyncio
async def test_fetch_pr_review_comments_success(
    monkeypatch: pytest.MonkeyPatch,
    mcp_server: ReviewSpecGenerator,
) -> None:
    async def mock_fetch(*args: Any, **kwargs: Any) -> list[dict]:
        return [{"id": 1}]

    monkeypatch.setattr("mcp_server.fetch_pr_comments", mock_fetch)
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
async def test_create_review_spec_file_creates_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mcp_server: ReviewSpecGenerator
) -> None:
    monkeypatch.chdir(tmp_path)
    comments = [
        {
            "body": "test comment",
            "path": "file.py",
            "line": 1,
            "user": {"login": "tester"},
        }
    ]
    result = await mcp_server.create_review_spec_file(comments, "out.md")
    spec_path = tmp_path / "review_specs" / "out.md"
    assert spec_path.exists()
    assert "Successfully created" in result


@pytest.mark.asyncio
async def test_create_review_spec_file_invalid_filename(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mcp_server: ReviewSpecGenerator
) -> None:
    monkeypatch.chdir(tmp_path)
    result = await mcp_server.create_review_spec_file([], "../bad.md")
    assert "Invalid filename" in result


@pytest.mark.asyncio
async def test_fetch_pr_comments_uses_auth_header(
    mock_http_client, github_token: str
) -> None:
    """fetch_pr_comments should send Authorization header when token is set."""
    mock_http_client.add_get_response(create_mock_response([]))

    await fetch_pr_comments("owner", "repo", 1)

    assert len(mock_http_client.get_calls) == 1
    headers = mock_http_client.get_calls[0][1]["headers"]
    assert headers.get("Authorization") == f"Bearer {github_token}"
