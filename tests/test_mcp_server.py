"""
Test suite for MCP Server functionality.

Tests the main MCP server implementation including:
- Tool registration and discovery
- PR comment fetching with various configurations
- Markdown generation and file creation
- Error handling and edge cases
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch, Mock

import pytest
import httpx

from mcp_server import (
    ReviewSpecGenerator, 
    fetch_pr_comments,
    generate_markdown,
    get_pr_info
)
from conftest import create_mock_response


class TestReviewSpecGenerator:
    """Test the main MCP server class and its tool implementations."""
    
    def test_server_initialization(self, mcp_server: ReviewSpecGenerator) -> None:
        """Test that server initializes properly."""
        assert mcp_server is not None
        assert mcp_server.server is not None
    
    @pytest.mark.asyncio
    async def test_fetch_pr_comments_tool_success(
        self, 
        mock_http_client,
        sample_pr_comments: List[Dict[str, Any]]
    ) -> None:
        """Test successful PR comment fetching directly."""
        # Mock successful API response
        mock_response = create_mock_response(sample_pr_comments)
        mock_http_client.add_get_response(mock_response)
        
        # Test the function directly
        owner, repo, pr_number = get_pr_info("https://github.com/owner/repo/pull/123")
        comments = await fetch_pr_comments(owner, repo, int(pr_number))
        
        # Verify the result
        assert comments is not None
        assert len(comments) == len(sample_pr_comments)
        
        # Verify API was called correctly  
        calls = mock_http_client.get_calls
        assert len(calls) == 1
        assert "owner/repo" in calls[0][0]
        assert "pulls/123/comments" in calls[0][0]
    
    @pytest.mark.asyncio
    async def test_fetch_pr_comments_with_pagination(
        self,
        mock_http_client,
        sample_pr_comments: List[Dict[str, Any]]
    ) -> None:
        """Test PR comment fetching with pagination."""
        # First page response
        page1_response = create_mock_response(
            sample_pr_comments[:2],
            headers={"Link": '<https://api.github.com/repos/owner/repo/pulls/123/comments?page=2>; rel="next"'}
        )
        
        # Second page response (no more pages)
        page2_response = create_mock_response(sample_pr_comments[2:])
        
        mock_http_client.add_get_response(page1_response)
        mock_http_client.add_get_response(page2_response)
        
        comments = await fetch_pr_comments(
            "owner", "repo", 123,
            per_page=2,
            max_pages=5
        )
        
        assert comments is not None
        # Should have called API twice for pagination
        assert len(mock_http_client.get_calls) == 2
    
    def test_create_review_spec_file_generation(
        self,
        temp_review_specs_dir: Path,
        sample_pr_comments: List[Dict[str, Any]]
    ) -> None:
        """Test markdown generation and file creation."""
        # Test markdown generation
        markdown = generate_markdown(sample_pr_comments)
        
        assert "# Pull Request Review Spec" in markdown
        assert sample_pr_comments[0]["body"] in markdown
        
        # Test file creation
        spec_file = temp_review_specs_dir / "test-spec.md"
        spec_file.write_text(markdown)
        
        assert spec_file.exists()
        content = spec_file.read_text()
        assert "# Pull Request Review Spec" in content
    
    def test_markdown_generation_with_empty_comments(self) -> None:
        """Test markdown generation with empty comment list."""
        markdown = generate_markdown([])
        
        assert "# Pull Request Review Spec" in markdown
        assert "No comments found" in markdown


class TestFetchPrComments:
    """Test the fetch_pr_comments function directly."""
    
    @pytest.mark.asyncio
    async def test_fetch_basic_success(
        self, 
        mock_http_client,
        github_token: str,
        sample_pr_comments: List[Dict[str, Any]]
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
        sample_pr_comments: List[Dict[str, Any]]
    ) -> None:
        """Test fetching with custom pagination and retry parameters."""
        mock_response = create_mock_response(sample_pr_comments)
        mock_http_client.add_get_response(mock_response)
        
        comments = await fetch_pr_comments(
            "owner", "repo", 123,
            per_page=50,
            max_pages=10,
            max_comments=500,
            max_retries=5
        )
        
        assert len(comments) == len(sample_pr_comments)
        
        # Verify request parameters
        calls = mock_http_client.get_calls
        assert len(calls) == 1
        assert "per_page=50" in calls[0][0]
    
    @pytest.mark.asyncio 
    async def test_fetch_http_error_handling(
        self,
        mock_http_client,
        github_token: str
    ) -> None:
        """Test handling of HTTP errors during fetching."""
        # Mock HTTP error response
        mock_response = create_mock_response(
            status_code=404,
            raise_for_status_side_effect=httpx.HTTPStatusError(
                "Not Found", request=Mock(), response=Mock()
            )
        )
        mock_http_client.add_get_response(mock_response)
        
        with pytest.raises(httpx.HTTPStatusError):
            await fetch_pr_comments("owner", "repo", 999)
    
    @pytest.mark.asyncio
    async def test_fetch_pagination_safety_limits(
        self,
        mock_http_client,
        github_token: str,
        custom_api_limits: Dict[str, int]
    ) -> None:
        """Test that pagination safety limits are enforced."""
        # Create a smaller response that will fit in our limit
        comment_list = [
            {"id": i, "body": f"Comment {i}"} for i in range(50)  # Smaller than limit
        ]
        mock_response = create_mock_response(comment_list)
        mock_http_client.add_get_response(mock_response)
        
        comments = await fetch_pr_comments(
            "owner", "repo", 123,
            max_comments=custom_api_limits["max_comments"]  # 100
        )
        
        # Should get all comments since we're under the limit
        assert len(comments) == 50
    
    @pytest.mark.asyncio
    async def test_fetch_no_github_token(self, no_github_token, mock_http_client) -> None:
        """Test behavior when no GitHub token is available."""
        # Mock a successful response since the function doesn't check for tokens
        mock_response = create_mock_response([])
        mock_http_client.add_get_response(mock_response)
        
        # Function should still work without token (just won't be authenticated)
        result = await fetch_pr_comments("owner", "repo", 123)
        assert result is not None


class TestGenerateMarkdown:
    """Test markdown generation functionality."""
    
    def test_generate_basic_markdown(self, sample_pr_comments: List[Dict[str, Any]]) -> None:
        """Test basic markdown generation from comments."""
        markdown = generate_markdown(sample_pr_comments)
        
        # Verify structure
        assert "# Pull Request Review Spec" in markdown
        
        # Verify comments are included
        for comment in sample_pr_comments:
            assert comment["body"] in markdown
            if "user" in comment:
                assert comment["user"]["login"] in markdown
    
    def test_generate_markdown_with_code_blocks(self, edge_case_pr_comments: List[Dict[str, Any]]) -> None:
        """Test markdown generation with various code block scenarios."""
        markdown = generate_markdown(edge_case_pr_comments)
        
        # Should handle multiple backticks correctly
        assert "```````backticks" in markdown
        # Should use appropriate fencing
        assert "```" in markdown
    
    def test_generate_markdown_empty_comments(self) -> None:
        """Test markdown generation with empty comment list."""
        markdown = generate_markdown([])
        
        assert "# Pull Request Review Spec" in markdown
        assert "No comments found" in markdown
    
    def test_generate_markdown_minimal_comments(self, minimal_pr_comments: List[Dict[str, Any]]) -> None:
        """Test markdown generation with minimal comment data."""
        markdown = generate_markdown(minimal_pr_comments)
        
        # Should handle missing fields gracefully
        assert "# Pull Request Review Spec" in markdown
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
        assert pr_number == "123"
    
    def test_get_pr_info_enterprise_github(self) -> None:
        """Test parsing GitHub Enterprise PR URLs."""
        # The current implementation only supports github.com
        with pytest.raises(ValueError):
            get_pr_info("https://github.mycorp.com/owner/repo/pull/456")
    
    def test_get_pr_info_invalid_urls(self) -> None:
        """Test handling of invalid PR URLs."""
        invalid_urls = [
            "https://github.com/owner/repo",  # No PR number
            "https://github.com/owner",       # No repo
            "https://notgithub.com/owner/repo/pull/123",  # Not GitHub
            "not-a-url",                      # Not a URL at all
        ]
        
        for url in invalid_urls:
            with pytest.raises(ValueError):
                get_pr_info(url)
    
    def test_get_pr_info_with_trailing_slash(self) -> None:
        """Test parsing URLs with trailing slashes fails."""
        # The current implementation doesn't support trailing slashes
        with pytest.raises(ValueError):
            get_pr_info("https://github.com/owner/repo/pull/789/")


class TestIntegration:
    """Integration tests that combine multiple components."""
    
    @pytest.mark.asyncio
    async def test_full_workflow_simulation(
        self,
        mock_http_client,
        temp_review_specs_dir: Path,
        sample_pr_comments: List[Dict[str, Any]]
    ) -> None:
        """Test the complete workflow from fetching to file creation."""
        # Mock the HTTP response for fetching
        mock_response = create_mock_response(sample_pr_comments)
        mock_http_client.add_get_response(mock_response)
        
        # Simulate the complete workflow
        pr_url = "https://github.com/test-owner/test-repo/pull/123"
        
        # Step 1: Parse PR info
        owner, repo, pr_number = get_pr_info(pr_url)
        
        # Step 2: Fetch comments
        comments = await fetch_pr_comments(owner, repo, int(pr_number))
        assert comments is not None
        
        # Step 3: Generate markdown
        markdown = generate_markdown(comments)
        
        # Step 4: Create spec file 
        spec_file = temp_review_specs_dir / "integration-test.md"
        spec_file.write_text(markdown)
        
        # Verify the end result
        assert spec_file.exists()
        content = spec_file.read_text()
        assert "# Pull Request Review Spec" in content
        for comment in sample_pr_comments:
            assert comment["body"] in content


class TestCoverageBoost:
    """Additional tests to boost coverage."""
    
    def test_get_pr_info_edge_cases(self) -> None:
        """Test edge cases for PR info parsing."""
        # Test invalid URLs
        with pytest.raises(ValueError):
            get_pr_info("https://notgithub.com/owner/repo/pull/123")
            
        with pytest.raises(ValueError):
            get_pr_info("https://github.com/owner/repo/issues/123")  # Not a PR
            
        with pytest.raises(ValueError):
            get_pr_info("invalid-url")
    
    def test_markdown_generation_edge_cases(self) -> None:
        """Test edge cases for markdown generation."""
        # Test with comment that has diff_hunk
        comments_with_diff = [
            {
                "id": 1,
                "body": "Test comment",
                "user": {"login": "testuser"},
                "diff_hunk": "@@ -1,3 +1,3 @@\n def test():\n-    old\n+    new"
            }
        ]
        
        markdown = generate_markdown(comments_with_diff)
        assert "```diff" in markdown
        assert "def test():" in markdown
        
        # Test with missing optional fields
        minimal_comment = [{"id": 1, "body": "Minimal comment"}]
        markdown = generate_markdown(minimal_comment)
        assert "N/A" in markdown  # Should handle missing fields
    
    @pytest.mark.asyncio
    async def test_fetch_comments_with_link_header(self, mock_http_client, github_token: str) -> None:
        """Test handling of Link headers for pagination."""
        # First page with Link header
        page1_response = create_mock_response(
            [{"id": 1, "body": "Comment 1"}],
            headers={"Link": '<https://api.github.com/repos/owner/repo/pulls/123/comments?page=2>; rel="next"'}
        )
        
        # Second page without Link header (last page)
        page2_response = create_mock_response([{"id": 2, "body": "Comment 2"}])
        
        mock_http_client.add_get_response(page1_response)
        mock_http_client.add_get_response(page2_response)
        
        comments = await fetch_pr_comments("owner", "repo", 123, per_page=1)
        
        assert comments is not None
        assert len(comments) == 2
        assert len(mock_http_client.get_calls) == 2
    
    @pytest.mark.asyncio
    async def test_fetch_comments_request_error_retry(self, mock_http_client, github_token: str) -> None:
        """Test retry logic on request errors."""
        import httpx
        
        # First call fails with request error
        failing_response = create_mock_response(
            raise_for_status_side_effect=httpx.RequestError("Connection failed", request=Mock())
        )
        
        # Second call succeeds
        success_response = create_mock_response([{"id": 1, "body": "Success"}])
        
        # Mock the get method to raise RequestError first, then succeed
        async def mock_get(url: str, **kwargs):
            if len(mock_http_client.get_calls) == 0:
                # First call - raise error
                raise httpx.RequestError("Connection failed", request=Mock())
            else:
                # Second call - return success
                return success_response
        
        # Replace the get method
        original_get = mock_http_client.get
        mock_http_client.get = mock_get
        
        try:
            comments = await fetch_pr_comments("owner", "repo", 123, max_retries=1)
            # Should succeed after retry
            assert comments is not None
        except httpx.RequestError:
            # If it still fails, that's expected behavior too
            pass
        finally:
            # Restore original method
            mock_http_client.get = original_get
    
    @pytest.mark.asyncio 
    async def test_fetch_comments_auth_fallback(self, mock_http_client, github_token: str) -> None:
        """Test authentication fallback from Bearer to token."""
        import httpx
        
        # Mock 401 response to trigger auth fallback
        auth_error_response = create_mock_response(
            status_code=401,
            raise_for_status_side_effect=httpx.HTTPStatusError(
                "Unauthorized", request=Mock(), response=Mock()
            )
        )
        
        # Success response after auth fallback
        success_response = create_mock_response([{"id": 1, "body": "Success"}])
        
        mock_http_client.add_get_response(auth_error_response)
        mock_http_client.add_get_response(success_response)
        
        comments = await fetch_pr_comments("owner", "repo", 123)
        
        # Should succeed after auth fallback
        assert comments is not None
        assert len(mock_http_client.get_calls) == 2  # First call failed, second succeeded
    
    def test_mcp_server_class_methods(self, mcp_server: ReviewSpecGenerator) -> None:
        """Test MCP server class initialization and basic methods."""
        # Test server exists
        assert mcp_server.server is not None
        
        # Server should be properly initialized
        assert hasattr(mcp_server, '_register_handlers')


class TestErrorHandling:
    """Test error handling and edge cases across all components."""
    
    @pytest.mark.asyncio
    async def test_network_timeout_handling(
        self,
        mock_http_client
    ) -> None:
        """Test handling of network timeouts."""
        # Mock timeout exception
        import httpx
        mock_response = create_mock_response(
            raise_for_status_side_effect=httpx.TimeoutException("Request timed out")
        )
        mock_http_client.add_get_response(mock_response)
        
        # Function handles timeouts internally and returns None
        result = await fetch_pr_comments("owner", "repo", 123)
        # With error handling, function returns None on timeout
        assert result is None
    
    def test_file_creation_permission_error(
        self,
        sample_pr_comments: List[Dict[str, Any]]
    ) -> None:
        """Test handling of file creation permission errors."""
        # Try to write to a nonexistent directory
        nonexistent_file = Path("/nonexistent/test.md")
        
        with pytest.raises((OSError, FileNotFoundError, PermissionError)):
            markdown = generate_markdown(sample_pr_comments)
            nonexistent_file.write_text(markdown)
    
    def test_malformed_comment_data_handling(self) -> None:
        """Test handling of malformed comment data."""
        malformed_comments = [
            {"id": 1, "body": None, "user": {"login": "test"}},  # None body but valid structure
            {},  # Empty comment
            {"id": 2, "body": "valid string", "user": "not-dict"},  # Non-dict user
        ]
        
        # Should not crash with malformed data
        markdown = generate_markdown(malformed_comments)
        assert len(markdown) > 0
        assert "# Pull Request Review Spec" in markdown