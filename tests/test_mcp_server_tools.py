from pathlib import Path
from typing import Any

import pytest

from mcp_server import ReviewSpecGenerator, generate_markdown


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
async def test_fetch_pr_review_comments_mime_types(
    monkeypatch: pytest.MonkeyPatch, mcp_server: ReviewSpecGenerator
) -> None:
    async def mock_fetch(*args: Any, **kwargs: Any) -> list[dict]:
        return []

    monkeypatch.setattr("mcp_server.fetch_pr_comments", mock_fetch)
    # Default output should be markdown with correct mimeType
    markdown_resp = await mcp_server.handle_call_tool(
        "fetch_pr_review_comments",
        {"pr_url": "https://github.com/o/r/pull/1"},
    )
    assert markdown_resp[0].meta == {"mimeType": "text/markdown"}

    # JSON output should include application/json mimeType
    json_resp = await mcp_server.handle_call_tool(
        "fetch_pr_review_comments",
        {"pr_url": "https://github.com/o/r/pull/1", "output": "json"},
    )
    assert json_resp[0].meta == {"mimeType": "application/json"}

    # Both should return markdown then json
    both_resp = await mcp_server.handle_call_tool(
        "fetch_pr_review_comments",
        {"pr_url": "https://github.com/o/r/pull/1", "output": "both"},
    )
    assert both_resp[0].meta == {"mimeType": "text/markdown"}
    assert both_resp[1].meta == {"mimeType": "application/json"}


@pytest.mark.asyncio
async def test_resolve_open_pr_url_mime_type(
    monkeypatch: pytest.MonkeyPatch, mcp_server: ReviewSpecGenerator
) -> None:
    async def mock_resolve(**kwargs: Any) -> str:
        return "https://github.com/o/r/pull/1"

    monkeypatch.setattr("mcp_server.resolve_pr_url", mock_resolve)
    resp = await mcp_server.handle_call_tool(
        "resolve_open_pr_url", {"owner": "o", "repo": "r", "branch": "b"}
    )
    assert resp[0].meta == {"mimeType": "text/uri-list"}


@pytest.mark.asyncio
async def test_create_review_spec_file_mime_type(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mcp_server: ReviewSpecGenerator
) -> None:
    monkeypatch.chdir(tmp_path)
    resp = await mcp_server.handle_call_tool(
        "create_review_spec_file",
        {"markdown": "hi", "filename": "out.md"},
    )
    assert resp[0].meta == {"mimeType": "text/plain"}
