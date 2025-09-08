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


@pytest.mark.parametrize(
    "output_args, expected_mimetypes",
    [
        ({}, ["text/markdown"]),  # Default
        ({"output": "markdown"}, ["text/markdown"]),
        ({"output": "json"}, ["application/json"]),
        ({"output": "both"}, ["text/markdown", "application/json"]),
    ],
)
@pytest.mark.asyncio
async def test_fetch_pr_review_comments_mime_types(
    monkeypatch: pytest.MonkeyPatch,
    mcp_server: ReviewSpecGenerator,
    output_args: dict[str, str],
    expected_mimetypes: list[str],
) -> None:
    async def mock_fetch(*args: Any, **kwargs: Any) -> list[dict]:
        return []

    monkeypatch.setattr("mcp_server.fetch_pr_comments", mock_fetch)

    tool_args = {"pr_url": "https://github.com/o/r/pull/1", **output_args}
    resp = await mcp_server.handle_call_tool("fetch_pr_review_comments", tool_args)

    assert len(resp) == len(expected_mimetypes)
    for i, mime_type in enumerate(expected_mimetypes):
        assert resp[i].meta == {"mimeType": mime_type}


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
async def test_list_and_read_resources(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mcp_server: ReviewSpecGenerator
) -> None:
    """Spec files should be exposed via MCP resources."""
    monkeypatch.chdir(tmp_path)
    comments = [
        {
            "body": "test comment",
            "path": "file.py",
            "line": 1,
            "user": {"login": "tester"},
        }
    ]
    await mcp_server.create_review_spec_file(comments, "out.md")
    resources = await mcp_server.handle_list_resources()
    assert resources and resources[0].name == "out.md"
    contents = await mcp_server.handle_read_resource(resources[0].uri)
    assert contents[0].content.startswith("# Pull Request Review Spec")
