"""
Test suite for MCP Server functionality.

Tests the main MCP server implementation including:
- Tool registration and discovery
- PR comment fetching with various configurations
- Markdown generation and file creation
- Error handling and edge cases
"""

import json
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import httpx
import pytest

from conftest import create_mock_response
from mcp_server import (
    ReviewSpecGenerator,
    fetch_pr_comments,
    generate_markdown,
    get_pr_info,
)


class TestReviewSpecGenerator:
    """Test the main MCP server class and its tool implementations."""

    def test_server_initialization(self, mcp_server: ReviewSpecGenerator) -> None:
        """Test that server initializes properly with correct tools."""
        assert mcp_server is not None

        # Server should have the expected tools registered
        tools = mcp_server.list_tools()
        tool_names = [tool.name for tool in tools.tools]

        assert "fetch_pr_review_comments" in tool_names
        assert "create_review_spec_file" in tool_names

    @pytest.mark.asyncio
    async def test_fetch_pr_comments_tool_success(
        self,
        mcp_server: ReviewSpecGenerator,
        mock_http_client,
        sample_pr_comments: list[dict[str, Any]],
    ) -> None:
        """Test successful PR comment fetching via MCP tool."""
        # Mock successful API response
        mock_response = create_mock_response(sample_pr_comments)
        mock_http_client.add_get_response(mock_response)

        # Execute the tool
        result = await mcp_server.call_tool(
            "fetch_pr_review_comments",
            {"url": "https://github.com/owner/repo/pull/123"},
        )

        # Verify the result structure
        assert result.is_error is False
        assert len(result.content) > 0

        # Verify API was called correctly
        calls = mock_http_client.get_calls
        assert len(calls) == 1
        assert "owner/repo" in calls[0][0]
        assert "pulls/123/comments" in calls[0][0]

    @pytest.mark.asyncio
    async def test_fetch_pr_comments_with_pagination(
        self,
        mcp_server: ReviewSpecGenerator,
        mock_http_client,
        sample_pr_comments: list[dict[str, Any]],
    ) -> None:
        """Test PR comment fetching with pagination."""
        # First page response
        page1_response = create_mock_response(
            sample_pr_comments[:2],
            headers={
                "Link": '<https://api.github.com/repos/owner/repo/pulls/123/comments?page=2>; rel="next"'  # noqa: E501
            },
        )

        # Second page response (no more pages)
        page2_response = create_mock_response(sample_pr_comments[2:])

        mock_http_client.add_get_response(page1_response)
        mock_http_client.add_get_response(page2_response)

        result = await mcp_server.call_tool(
            "fetch_pr_review_comments",
            {
                "url": "https://github.com/owner/repo/pull/123",
                "per_page": 2,
                "max_pages": 5,
            },
        )

        assert result.is_error is False
        # Should have called API twice for pagination
        assert len(mock_http_client.get_calls) == 2

    @pytest.mark.asyncio
    async def test_create_review_spec_file_tool(
        self,
        mcp_server: ReviewSpecGenerator,
        temp_review_specs_dir: Path,
        sample_pr_comments: list[dict[str, Any]],
    ) -> None:
        """Test creating a review spec file via MCP tool."""
        with patch("mcp_server.Path.cwd", return_value=temp_review_specs_dir.parent):
            result = await mcp_server.call_tool(
                "create_review_spec_file",
                {
                    "pr_url": "https://github.com/owner/repo/pull/123",
                    "comments": sample_pr_comments,
                    "filename": "test-spec.md",
                },
            )

            assert result.is_error is False

            # Verify file was created
            spec_file = temp_review_specs_dir / "test-spec.md"
            assert spec_file.exists()

            # Verify file content
            content = spec_file.read_text()
            assert "# PR Review Spec" in content
            assert "owner/repo" in content
            assert sample_pr_comments[0]["body"] in content

    @pytest.mark.asyncio
    async def test_create_review_spec_file_auto_filename(
        self,
        mcp_server: ReviewSpecGenerator,
        temp_review_specs_dir: Path,
        sample_pr_comments: list[dict[str, Any]],
    ) -> None:
        """Test auto-generation of filename when not provided."""
        with patch("mcp_server.Path.cwd", return_value=temp_review_specs_dir.parent):
            result = await mcp_server.call_tool(
                "create_review_spec_file",
                {
                    "pr_url": "https://github.com/owner/repo/pull/123",
                    "comments": sample_pr_comments,
                    # No filename provided
                },
            )

            assert result.is_error is False

            # Should auto-generate filename
            created_files = list(temp_review_specs_dir.glob("*.md"))
            assert len(created_files) == 1
            assert "owner-repo-pr-123" in created_files[0].name


class TestFetchPrComments:
    """Test the fetch_pr_comments function directly."""

    @pytest.mark.asyncio
    async def test_fetch_basic_success(
        self,
        mock_http_client,
        github_token: str,
        sample_pr_comments: list[dict[str, Any]],
    ) -> None:
        """Test basic successful comment fetching."""
        mock_response = create_mock_response(sample_pr_comments)
        mock_http_client.add_get_response(mock_response)

        comments = await fetch_pr_comments("owner", "repo", 123)

        assert len(comments) == len(sample_pr_comments)
        assert comments[0]["id"] == sample_pr_comments[0]["id"]
        assert comments[0]["body"] == sample_pr_comments[0]["body"]

    @pytest.mark.asyncio
    async def test_fetch_with_custom_parameters(
        self,
        mock_http_client,
        github_token: str,
        sample_pr_comments: list[dict[str, Any]],
    ) -> None:
        """Test fetching with custom pagination and retry parameters."""
        mock_response = create_mock_response(sample_pr_comments)
        mock_http_client.add_get_response(mock_response)

        comments = await fetch_pr_comments(
            "owner",
            "repo",
            123,
            per_page=50,
            max_pages=10,
            max_comments=500,
            max_retries=5,
        )

        assert len(comments) == len(sample_pr_comments)

        # Verify request parameters
        calls = mock_http_client.get_calls
        assert len(calls) == 1
        assert "per_page=50" in calls[0][0]

    @pytest.mark.asyncio
    async def test_fetch_http_error_handling(
        self, mock_http_client, github_token: str
    ) -> None:
        """Test handling of HTTP errors during fetching."""
        # Mock HTTP error response
        mock_response = create_mock_response(
            status_code=404,
            raise_for_status_side_effect=httpx.HTTPStatusError(
                "Not Found", request=Mock(), response=Mock()
            ),
        )
        mock_http_client.add_get_response(mock_response)

        with pytest.raises(httpx.HTTPStatusError):
            await fetch_pr_comments("owner", "repo", 999)

    @pytest.mark.asyncio
    async def test_fetch_pagination_safety_limits(
        self, mock_http_client, github_token: str, custom_api_limits: dict[str, int]
    ) -> None:
        """Test that pagination safety limits are enforced."""
        # Create a response with more items than our limit
        large_comment_list = [{"id": i, "body": f"Comment {i}"} for i in range(200)]
        mock_response = create_mock_response(large_comment_list)
        mock_http_client.add_get_response(mock_response)

        comments = await fetch_pr_comments(
            "owner",
            "repo",
            123,
            max_comments=custom_api_limits["max_comments"],  # 100
        )

        # Should be limited to max_comments
        assert len(comments) <= custom_api_limits["max_comments"]

    @pytest.mark.asyncio
    async def test_fetch_no_github_token(self, no_github_token) -> None:
        """Test behavior when no GitHub token is available."""
        with pytest.raises(ValueError, match="GITHUB_TOKEN"):
            await fetch_pr_comments("owner", "repo", 123)


class TestGenerateMarkdown:
    """Test markdown generation functionality."""

    def test_generate_basic_markdown(
        self, sample_pr_comments: list[dict[str, Any]]
    ) -> None:
        """Test basic markdown generation from comments."""
        markdown = generate_markdown(sample_pr_comments)

        # Verify structure
        assert "# PR Review Spec" in markdown
        assert "owner/repo" in markdown
        assert "#123" in markdown

        # Verify comments are included
        for comment in sample_pr_comments:
            assert comment["body"] in markdown
            if "user" in comment:
                assert comment["user"]["login"] in markdown

    def test_generate_markdown_with_code_blocks(
        self, edge_case_pr_comments: list[dict[str, Any]]
    ) -> None:
        """Test markdown generation with various code block scenarios."""
        markdown = generate_markdown(edge_case_pr_comments)

        # Should handle multiple backticks correctly
        assert "```````backticks" in markdown
        # Should use appropriate fencing
        assert "```" in markdown or "~~~~" in markdown

    def test_generate_markdown_empty_comments(self) -> None:
        """Test markdown generation with empty comment list."""
        markdown = generate_markdown([])

        assert "# PR Review Spec" in markdown
        assert "No comments" in markdown or "empty" in markdown.lower()

    def test_generate_markdown_minimal_comments(
        self, minimal_pr_comments: list[dict[str, Any]]
    ) -> None:
        """Test markdown generation with minimal comment data."""
        markdown = generate_markdown(minimal_pr_comments)

        # Should handle missing fields gracefully
        assert "# PR Review Spec" in markdown
        # Should not crash on None or empty values
        assert len(markdown) > 0


class TestGetPrInfo:
    """Test PR URL parsing functionality."""

    def test_get_pr_info_standard_github(self) -> None:
        """Test parsing standard GitHub PR URLs."""
        url = "https://github.com/owner/repo/pull/123"
        owner, repo, pr_number = get_pr_info(url)

        assert owner == "owner"
        assert repo == "repo"
        assert pr_number == 123

    def test_get_pr_info_enterprise_github(self) -> None:
        """Test parsing GitHub Enterprise PR URLs."""
        url = "https://github.mycorp.com/owner/repo/pull/456"
        owner, repo, pr_number = get_pr_info(url)

        assert owner == "owner"
        assert repo == "repo"
        assert pr_number == 456

    def test_get_pr_info_invalid_urls(self) -> None:
        """Test handling of invalid PR URLs."""
        invalid_urls = [
            "https://github.com/owner/repo",  # No PR number
            "https://github.com/owner",  # No repo
            "https://notgithub.com/owner/repo/pull/123",  # Not GitHub
            "not-a-url",  # Not a URL at all
        ]

        for url in invalid_urls:
            with pytest.raises(ValueError):
                get_pr_info(url)

    def test_get_pr_info_with_trailing_slash(self) -> None:
        """Test parsing URLs with trailing slashes and query parameters."""
        url = "https://github.com/owner/repo/pull/789/"
        owner, repo, pr_number = get_pr_info(url)

        assert owner == "owner"
        assert repo == "repo"
        assert pr_number == 789


class TestIntegration:
    """Integration tests that combine multiple components."""

    @pytest.mark.asyncio
    async def test_full_workflow_simulation(
        self,
        mcp_server: ReviewSpecGenerator,
        mock_http_client,
        temp_review_specs_dir: Path,
        sample_pr_comments: list[dict[str, Any]],
    ) -> None:
        """Test the complete workflow from fetching to file creation."""
        # Mock the HTTP response for fetching
        mock_response = create_mock_response(sample_pr_comments)
        mock_http_client.add_get_response(mock_response)

        # Simulate the complete workflow
        pr_url = "https://github.com/test-owner/test-repo/pull/123"

        with patch("mcp_server.Path.cwd", return_value=temp_review_specs_dir.parent):
            # Step 1: Fetch comments
            fetch_result = await mcp_server.call_tool(
                "fetch_pr_review_comments", {"url": pr_url}
            )
            assert fetch_result.is_error is False

            # Step 2: Create spec file
            comments_data = json.loads(fetch_result.content[0].text)["comments"]

            create_result = await mcp_server.call_tool(
                "create_review_spec_file",
                {
                    "pr_url": pr_url,
                    "comments": comments_data,
                    "filename": "integration-test.md",
                },
            )
            assert create_result.is_error is False

            # Verify the end result
            spec_file = temp_review_specs_dir / "integration-test.md"
            assert spec_file.exists()

            content = spec_file.read_text()
            assert "test-owner/test-repo" in content
            assert "#123" in content
            for comment in sample_pr_comments:
                assert comment["body"] in content


class TestErrorHandling:
    """Test error handling and edge cases across all components."""

    @pytest.mark.asyncio
    async def test_network_timeout_handling(
        self, mcp_server: ReviewSpecGenerator, mock_http_client
    ) -> None:
        """Test handling of network timeouts."""
        # Mock timeout exception
        import httpx

        mock_response = create_mock_response(
            raise_for_status_side_effect=httpx.TimeoutException("Request timed out")
        )
        mock_http_client.add_get_response(mock_response)

        result = await mcp_server.call_tool(
            "fetch_pr_review_comments",
            {"url": "https://github.com/owner/repo/pull/123"},
        )

        # Should return error result rather than raising exception
        assert result.is_error is True

    @pytest.mark.asyncio
    async def test_file_creation_permission_error(
        self, mcp_server: ReviewSpecGenerator, sample_pr_comments: list[dict[str, Any]]
    ) -> None:
        """Test handling of file creation permission errors."""
        with patch("mcp_server.Path.cwd", return_value=Path("/nonexistent")):
            result = await mcp_server.call_tool(
                "create_review_spec_file",
                {
                    "pr_url": "https://github.com/owner/repo/pull/123",
                    "comments": sample_pr_comments,
                    "filename": "test.md",
                },
            )

            # Should handle gracefully and return error
            assert result.is_error is True

    def test_malformed_comment_data_handling(self) -> None:
        """Test handling of malformed comment data."""
        malformed_comments = [
            {"id": "not-a-number", "body": None},  # Bad ID, None body
            {},  # Empty comment
            {"body": 123},  # Non-string body
        ]

        # Should not crash with malformed data
        markdown = generate_markdown(malformed_comments)
        assert len(markdown) > 0
        assert "# PR Review Spec" in markdown
