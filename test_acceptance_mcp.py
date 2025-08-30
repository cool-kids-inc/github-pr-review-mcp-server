"""
Acceptance tests for MCP server functionality.

These tests verify that the MCP server can initialize properly, expose tools
with valid schemas, and execute tools without validation errors.
"""

import json
from unittest.mock import patch

import pytest
from mcp.types import TextContent

from mcp_server import ReviewSpecGenerator


@pytest.fixture
def server():
    """Provides a ReviewSpecGenerator instance for tests."""
    return ReviewSpecGenerator()


@pytest.mark.asyncio
async def test_server_initialization(server):
    """Test that the MCP server initializes without errors."""
    assert server is not None
    assert server.server is not None
    assert server.server.name == "github_review_spec_generator"


@pytest.mark.asyncio
async def test_list_tools(server):
    """Test that tools are listed with valid schemas (no oneOf/allOf/anyOf)."""
    tools = await server.handle_list_tools()

    assert len(tools) == 3
    tool_names = [tool.name for tool in tools]
    assert "fetch_pr_review_comments" in tool_names
    assert "resolve_open_pr_url" in tool_names
    assert "create_review_spec_file" in tool_names

    # Verify schemas don't use problematic top-level constructs
    for tool in tools:
        schema = tool.inputSchema
        assert "oneOf" not in schema
        assert "allOf" not in schema
        assert "anyOf" not in schema
        assert schema["type"] == "object"
        assert "properties" in schema

        # Verify fetch_pr_review_comments doesn't require pr_url
        if tool.name == "fetch_pr_review_comments":
            assert "required" not in schema or "pr_url" not in schema.get(
                "required", []
            )

        # Verify create_review_spec_file doesn't have oneOf constraint
        if tool.name == "create_review_spec_file":
            assert "oneOf" not in schema
            props = schema["properties"]
            assert "markdown" in props
            assert "comments" in props
            assert "filename" in props


@pytest.mark.asyncio
@patch("mcp_server.fetch_pr_comments")
async def test_fetch_pr_review_comments_with_pr_url(mock_fetch_comments, server):
    """Test fetch_pr_review_comments tool with explicit PR URL."""
    mock_comments = [
        {
            "id": 1,
            "body": "Test comment",
            "user": {"login": "testuser"},
            "path": "test.py",
            "line": 10,
        }
    ]
    mock_fetch_comments.return_value = mock_comments

    result = await server.handle_call_tool(
        "fetch_pr_review_comments", {"pr_url": "https://github.com/owner/repo/pull/123"}
    )

    assert len(result) == 1
    assert isinstance(result[0], TextContent)
    content = result[0].text
    assert "# Pull Request Review Spec" in content
    assert "Test comment" in content
    assert "testuser" in content


@pytest.mark.asyncio
@patch("mcp_server.resolve_pr_url")
@patch("mcp_server.fetch_pr_comments")
async def test_fetch_pr_review_comments_without_pr_url(
    mock_fetch_comments, mock_resolve_pr, server
):
    """Test fetch_pr_review_comments tool without PR URL (auto-detection)."""
    mock_resolve_pr.return_value = "https://github.com/owner/repo/pull/456"
    mock_comments = [
        {
            "id": 2,
            "body": "Auto-detected comment",
            "user": {"login": "autouser"},
            "path": "auto.py",
            "line": 20,
        }
    ]
    mock_fetch_comments.return_value = mock_comments

    # This should work without pr_url since it's no longer required
    result = await server.handle_call_tool("fetch_pr_review_comments", {})

    assert len(result) == 1
    assert isinstance(result[0], TextContent)
    content = result[0].text
    assert "# Pull Request Review Spec" in content
    assert "Auto-detected comment" in content


@pytest.mark.asyncio
@patch("mcp_server.resolve_pr_url")
async def test_resolve_open_pr_url(mock_resolve_pr, server):
    """Test resolve_open_pr_url tool."""
    mock_resolve_pr.return_value = "https://github.com/owner/repo/pull/789"

    result = await server.handle_call_tool(
        "resolve_open_pr_url", {"select_strategy": "branch"}
    )

    assert len(result) == 1
    assert isinstance(result[0], TextContent)
    assert result[0].text == "https://github.com/owner/repo/pull/789"


@pytest.mark.asyncio
async def test_create_review_spec_file_with_markdown(server, tmp_path):
    """Test create_review_spec_file tool with markdown input."""
    markdown_content = "# Test Spec\n\nThis is a test markdown file."

    with patch("mcp_server.Path.cwd", return_value=tmp_path):
        result = await server.handle_call_tool(
            "create_review_spec_file",
            {"markdown": markdown_content, "filename": "test-spec.md"},
        )

    assert len(result) == 1
    assert isinstance(result[0], TextContent)
    assert "Successfully created spec file" in result[0].text

    # Verify file was created
    spec_dir = tmp_path / "review_specs"
    spec_file = spec_dir / "test-spec.md"
    assert spec_file.exists()
    assert spec_file.read_text() == markdown_content


@pytest.mark.asyncio
async def test_create_review_spec_file_with_comments(server, tmp_path):
    """Test create_review_spec_file tool with comments input."""
    comments = [
        {
            "id": 1,
            "body": "Test comment",
            "user": {"login": "testuser"},
            "path": "test.py",
            "line": 10,
        }
    ]

    with patch("mcp_server.Path.cwd", return_value=tmp_path):
        result = await server.handle_call_tool(
            "create_review_spec_file",
            {"comments": comments, "filename": "comments-spec.md"},
        )

    assert len(result) == 1
    assert isinstance(result[0], TextContent)
    assert "Successfully created spec file" in result[0].text

    # Verify file was created and contains expected content
    spec_dir = tmp_path / "review_specs"
    spec_file = spec_dir / "comments-spec.md"
    assert spec_file.exists()
    content = spec_file.read_text()
    assert "# Pull Request Review Spec" in content
    assert "Test comment" in content


@pytest.mark.asyncio
async def test_create_review_spec_file_validation_error(server):
    """Test create_review_spec_file validation with missing inputs."""
    # This should raise a ValueError since validation happens in the handler
    with pytest.raises(
        ValueError, match="Missing input: provide 'markdown' or 'comments'"
    ):
        await server.handle_call_tool(
            "create_review_spec_file", {"filename": "empty-spec.md"}
        )


@pytest.mark.asyncio
async def test_fetch_pr_comments_output_formats(server):
    """Test fetch_pr_review_comments with different output formats."""
    mock_comments = [{"id": 1, "body": "Test"}]

    with patch("mcp_server.fetch_pr_comments", return_value=mock_comments):
        # Test markdown output (default)
        result = await server.handle_call_tool(
            "fetch_pr_review_comments",
            {"pr_url": "https://github.com/owner/repo/pull/123"},
        )
        assert len(result) == 1
        assert "# Pull Request Review Spec" in result[0].text

        # Test json output
        result = await server.handle_call_tool(
            "fetch_pr_review_comments",
            {"pr_url": "https://github.com/owner/repo/pull/123", "output": "json"},
        )
        assert len(result) == 1
        json.loads(result[0].text)  # Should parse as valid JSON

        # Test both output
        result = await server.handle_call_tool(
            "fetch_pr_review_comments",
            {"pr_url": "https://github.com/owner/repo/pull/123", "output": "both"},
        )
        assert len(result) == 2
        assert "# Pull Request Review Spec" in result[0].text
        json.loads(result[1].text)  # Second should be valid JSON
