"""Tests for mcp_server error cases and edge paths."""

import json
import os
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest

from mcp_server import ReviewSpecGenerator, get_pr_info
from tests.test_utils import create_mock_response, mock_httpx_client


class TestGetPrInfo:
    """Test get_pr_info function edge cases."""

    def test_get_pr_info_invalid_url(self) -> None:
        """Test get_pr_info with invalid URL format."""
        with pytest.raises(ValueError, match="Invalid PR URL format"):
            get_pr_info("https://example.com/not/a/github/url")

    def test_get_pr_info_missing_pull(self) -> None:
        """Test get_pr_info with missing pull in URL."""
        with pytest.raises(ValueError, match="Invalid PR URL format"):
            get_pr_info("https://github.com/owner/repo/issues/123")


class TestReviewSpecGeneratorErrorCases:
    """Test ReviewSpecGenerator error handling."""

    @pytest.fixture
    def server(self) -> ReviewSpecGenerator:
        """Create server instance for testing."""
        return ReviewSpecGenerator()

    @pytest.mark.asyncio
    async def test_fetch_pr_comments_invalid_bool_per_page(self, server: ReviewSpecGenerator) -> None:
        """Test fetch_pr_comments with boolean per_page parameter."""
        with pytest.raises(ValueError, match="Invalid type for per_page"):
            await server.handle_call_tool(
                "fetch_pr_review_comments",
                {
                    "pr_url": "https://github.com/owner/repo/pull/123",
                    "per_page": True,  # Invalid: boolean instead of int
                },
            )

    @pytest.mark.asyncio
    async def test_fetch_pr_comments_invalid_out_of_range_per_page(self, server: ReviewSpecGenerator) -> None:
        """Test fetch_pr_comments with out of range per_page parameter."""
        with pytest.raises(ValueError, match="Invalid value for per_page"):
            await server.handle_call_tool(
                "fetch_pr_review_comments",
                {
                    "pr_url": "https://github.com/owner/repo/pull/123",
                    "per_page": 200,  # Out of range
                },
            )

    @pytest.mark.asyncio
    async def test_fetch_pr_comments_invalid_output_format(self, server: ReviewSpecGenerator) -> None:
        """Test fetch_pr_comments with invalid output format."""
        mock_comments = [{"id": 1, "body": "Test"}]
        
        with patch("mcp_server.fetch_pr_comments", return_value=mock_comments):
            with pytest.raises(ValueError, match="Invalid output: must be 'markdown', 'json', or 'both'"):
                await server.handle_call_tool(
                    "fetch_pr_review_comments",
                    {
                        "pr_url": "https://github.com/owner/repo/pull/123",
                        "output": "invalid",
                    },
                )

    @pytest.mark.asyncio
    async def test_fetch_pr_comments_markdown_generation_error(self, server: ReviewSpecGenerator) -> None:
        """Test fetch_pr_comments when markdown generation fails."""
        mock_comments = [{"id": 1, "body": "Test"}]
        
        with patch("mcp_server.fetch_pr_comments", return_value=mock_comments), \
             patch("mcp_server.generate_markdown", side_effect=Exception("Markdown generation failed")):
            result = await server.handle_call_tool(
                "fetch_pr_review_comments",
                {
                    "pr_url": "https://github.com/owner/repo/pull/123",
                    "output": "markdown",
                },
            )
            assert len(result) == 1
            assert "Failed to generate markdown" in result[0].text

    @pytest.mark.asyncio
    async def test_create_spec_missing_input(self, server: ReviewSpecGenerator) -> None:
        """Test create_review_spec_file with missing input."""
        with pytest.raises(ValueError, match="Missing input: provide 'markdown' or 'comments'"):
            await server.handle_call_tool(
                "create_review_spec_file",
                {},  # Missing both markdown and comments
            )

    @pytest.mark.asyncio
    async def test_create_spec_invalid_comments_type(self, server: ReviewSpecGenerator) -> None:
        """Test create_review_spec_file with invalid comments type."""
        result = await server.handle_call_tool(
            "create_review_spec_file",
            {"comments": "not a list"},  # Should be a list
        )
        assert len(result) == 1
        assert "Error in create_review_spec_file" in result[0].text

    @pytest.mark.asyncio
    async def test_create_spec_invalid_comments_items(self, server: ReviewSpecGenerator) -> None:
        """Test create_review_spec_file with invalid comment items."""
        result = await server.handle_call_tool(
            "create_review_spec_file",
            {"comments": ["not a dict", {"valid": "item"}]},  # Mixed types
        )
        assert len(result) == 1
        assert "Error in create_review_spec_file" in result[0].text

    @pytest.mark.asyncio
    async def test_create_spec_file_permission_error(self, server: ReviewSpecGenerator) -> None:
        """Test create_review_spec_file with file permission error."""
        with patch("os.open", side_effect=PermissionError("Permission denied")):
            result = await server.handle_call_tool(
                "create_review_spec_file",
                {
                    "markdown": "# Test",
                    "filename": "test.md",
                },
            )
            assert len(result) == 1
            assert "Error in create_review_spec_file" in result[0].text

    @pytest.mark.asyncio
    async def test_fetch_pr_comments_with_git_context_error(self, server: ReviewSpecGenerator) -> None:
        """Test fetch_pr_comments when git context detection fails."""
        with patch("mcp_server.git_detect_repo_branch", side_effect=ValueError("Not a git repo")), \
             patch("mcp_server.resolve_pr_url", side_effect=ValueError("Resolution failed")):
            result = await server.handle_call_tool(
                "fetch_pr_review_comments",
                {},  # No pr_url provided, should trigger git detection
            )
            assert len(result) == 1
            assert "Error in fetch_pr_review_comments" in result[0].text

    @pytest.mark.asyncio
    async def test_unknown_tool_call(self, server: ReviewSpecGenerator) -> None:
        """Test handle_call_tool with unknown tool name."""
        with pytest.raises(ValueError, match="Unknown tool: unknown_tool"):
            await server.handle_call_tool(
                "unknown_tool",
                {"param": "value"},
            )

    @pytest.mark.asyncio
    async def test_server_run_keyboard_interrupt(self) -> None:
        """Test server run method with KeyboardInterrupt."""
        server = ReviewSpecGenerator()
        
        with patch("mcp.server.stdio.stdio_server") as mock_stdio_server:
            mock_stdio_server.side_effect = KeyboardInterrupt()
            
            with pytest.raises(SystemExit) as exc_info:
                await server.run()
            
            assert exc_info.value.code == 0

    @pytest.mark.asyncio  
    async def test_server_run_exception(self) -> None:
        """Test server run method with unexpected exception."""
        server = ReviewSpecGenerator()
        
        with patch("mcp.server.stdio.stdio_server") as mock_stdio_server:
            mock_stdio_server.side_effect = Exception("Unexpected error")
            
            with pytest.raises(SystemExit) as exc_info:
                await server.run()
            
            assert exc_info.value.code == 1


class TestFetchPrCommentsEdgeCases:
    """Test fetch_pr_comments function edge cases."""

    @pytest.fixture
    def server(self) -> ReviewSpecGenerator:
        """Create server instance for testing."""
        return ReviewSpecGenerator()

    @pytest.mark.asyncio
    async def test_fetch_pr_comments_http_error(self, server: ReviewSpecGenerator) -> None:
        """Test fetch_pr_comments with HTTP error."""
        with patch("mcp_server.fetch_pr_comments", side_effect=Exception("HTTP 404 Not Found")):
            with pytest.raises(RuntimeError, match="Error executing tool fetch_pr_review_comments"):
                await server.handle_call_tool(
                    "fetch_pr_review_comments",
                    {"pr_url": "https://github.com/owner/repo/pull/999"},
                )

    @pytest.mark.asyncio
    async def test_fetch_pr_comments_resolve_pr_url_fallback(self, server: ReviewSpecGenerator) -> None:
        """Test fetch_pr_comments with resolve_pr_url fallback when no pr_url."""
        mock_comments = [{"id": 1, "body": "Test"}]
        
        with patch("mcp_server.git_detect_repo_branch") as mock_git, \
             patch("mcp_server.resolve_pr_url", return_value="https://github.com/owner/repo/pull/42") as mock_resolve, \
             patch("mcp_server.fetch_pr_comments", return_value=mock_comments):
            
            mock_git.return_value = Mock(host="github.com", owner="owner", repo="repo", branch="main")
            
            result = await server.handle_call_tool(
                "fetch_pr_review_comments",
                {"use_git_context": True},  # No pr_url, will use git context
            )
            
            assert len(result) == 1
            mock_resolve.assert_called_once()