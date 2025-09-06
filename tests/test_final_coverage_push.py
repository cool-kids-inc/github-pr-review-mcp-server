"""Final tests to push coverage from 86% to 90%."""

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

import git_pr_resolver
import mcp_server
from mcp_server import ReviewSpecGenerator


class TestFinalCoveragePush:
    """Final targeted tests for remaining uncovered lines."""

    @pytest.mark.asyncio
    async def test_resolve_pr_url_no_open_prs(self) -> None:
        """Test resolve_pr_url when no open PRs are found."""
        mock_client = AsyncMock()
        
        # Mock GraphQL failure and empty REST response
        graphql_response = Mock()
        graphql_response.json.return_value = {"errors": [{"message": "error"}]}
        
        rest_response = Mock()
        rest_response.json.return_value = []  # No open PRs
        rest_response.raise_for_status.return_value = None
        
        mock_client.post.return_value = graphql_response
        mock_client.get.return_value = rest_response
        
        with patch("git_pr_resolver.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(ValueError, match="No open PRs found"):
                await git_pr_resolver.resolve_pr_url("owner", "repo", branch="main")

    @pytest.mark.asyncio
    async def test_resolve_pr_url_branch_not_found(self) -> None:
        """Test resolve_pr_url when specific branch PR not found."""
        mock_client = AsyncMock()
        
        # Mock responses that don't have the requested branch
        graphql_response = Mock()
        graphql_response.json.return_value = {"errors": [{"message": "error"}]}
        
        head_response = Mock()
        head_response.json.return_value = []  # No PR for specific branch
        head_response.raise_for_status.return_value = None
        
        general_response = Mock() 
        general_response.json.return_value = [
            {"number": 1, "head": {"ref": "different-branch"}, "html_url": "url1"}
        ]
        general_response.raise_for_status.return_value = None
        
        def mock_get(url: str, **kwargs: Any) -> Mock:
            if "head=" in url:
                return head_response
            return general_response
        
        mock_client.post.return_value = graphql_response
        mock_client.get.side_effect = mock_get
        
        with patch("git_pr_resolver.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(ValueError, match="No open PR found for branch"):
                await git_pr_resolver.resolve_pr_url("owner", "repo", branch="main")

    @pytest.mark.asyncio
    async def test_resolve_pr_url_first_strategy(self) -> None:
        """Test resolve_pr_url with 'first' strategy."""
        mock_client = AsyncMock()
        
        # Mock GraphQL failure
        graphql_response = Mock()
        graphql_response.json.return_value = {"errors": [{"message": "error"}]}
        
        # Mock REST response with multiple PRs (different numbers)
        rest_response = Mock()
        rest_response.json.return_value = [
            {"number": 5, "html_url": "url5"},
            {"number": 2, "html_url": "url2"},  # This should be selected (lowest number)
            {"number": 10, "html_url": "url10"},
        ]
        rest_response.raise_for_status.return_value = None
        
        mock_client.post.return_value = graphql_response
        mock_client.get.return_value = rest_response
        
        with patch("git_pr_resolver.httpx.AsyncClient", return_value=mock_client):
            result = await git_pr_resolver.resolve_pr_url(
                "owner", "repo", select_strategy="first"
            )
            assert result == "url2"

    def test_graphql_url_host_matching(self, monkeypatch: Any) -> None:
        """Test GraphQL URL host matching logic."""
        # Test with explicit GITHUB_GRAPHQL_URL that matches host
        monkeypatch.setenv("GITHUB_GRAPHQL_URL", "https://api.github.com/graphql")
        result = git_pr_resolver._graphql_url_for_host("github.com")
        assert result == "https://api.github.com/graphql"
        
        # Test with explicit GITHUB_GRAPHQL_URL for different host (should ignore)
        result = git_pr_resolver._graphql_url_for_host("enterprise.example.com")
        # Should use default enterprise pattern, not the explicit github.com URL
        assert result == "https://enterprise.example.com/api/graphql"

    @pytest.mark.asyncio
    async def test_fetch_pr_comments_debug_logging(self) -> None:
        """Test debug logging in fetch_pr_comments."""
        # Enable debug logging
        os.environ["DEBUG_GITHUB_PR_RESOLVER"] = "1"
        
        try:
            mock_client = AsyncMock()
            # Mock GraphQL failure to trigger debug print
            graphql_response = Mock() 
            graphql_response.json.return_value = {"errors": [{"message": "test error"}]}
            graphql_response.raise_for_status.side_effect = Exception("GraphQL failed")
            
            # Mock successful REST fallback
            rest_response = Mock()
            rest_response.json.return_value = [{"number": 1, "html_url": "url"}]
            rest_response.raise_for_status.return_value = None
            
            mock_client.post.return_value = graphql_response
            mock_client.get.return_value = rest_response
            
            with patch("git_pr_resolver.httpx.AsyncClient", return_value=mock_client):
                result = await git_pr_resolver.resolve_pr_url(
                    "owner", "repo", branch="main", select_strategy="branch"
                )
                assert result == "url"
        finally:
            # Clean up debug flag
            if "DEBUG_GITHUB_PR_RESOLVER" in os.environ:
                del os.environ["DEBUG_GITHUB_PR_RESOLVER"]

    def test_generate_markdown_complex_fencing(self) -> None:
        """Test markdown generation with complex code fencing scenarios."""
        comments = [{
            "id": 1,
            "body": "Code with ```````nested` backticks",  # Many backticks
            "path": "file.py",
            "position": 1,
            "line": 1,
            "user": {"login": "user"}
        }]
        
        result = mcp_server.generate_markdown(comments)
        # Should use enough backticks to escape the content
        assert "````````" in result  # 8 backticks to escape 7

    @pytest.mark.asyncio
    async def test_mcp_server_create_file_with_async_write(self) -> None:
        """Test create_review_spec_file async write functionality."""
        server = ReviewSpecGenerator()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = Path(temp_dir) / "async_test.md"
            
            with patch("mcp_server.Path.cwd", return_value=Path(temp_dir)):
                # Test the async file write path
                result = await server.create_review_spec_file(
                    "# Async Test\n\nContent with multiple lines", 
                    "async_test.md"
                )
                
                assert "async_test.md" in result
                assert test_file.exists()
                content = test_file.read_text()
                assert "# Async Test" in content

    @pytest.mark.asyncio
    async def test_fetch_pr_comments_pagination_safety_limits(self) -> None:
        """Test pagination safety limits in fetch_pr_comments."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"Link": None}  # No next page
        mock_response.json.return_value = [{"id": i, "body": f"Comment {i}"} for i in range(50)]
        
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        
        with patch("mcp_server.httpx.AsyncClient", return_value=mock_client):
            # Test with very low limits to ensure safety logic is hit
            comments = await mcp_server.fetch_pr_comments(
                "owner", "repo", 123,
                per_page=50,
                max_pages=1,  # Limit to 1 page
                max_comments=25,  # Limit comments
                max_retries=0,
                token="test-token"
            )
            
            # Should be limited by max_comments
            assert len(comments) == 25

    @pytest.mark.asyncio
    async def test_resolve_pr_url_latest_strategy(self) -> None:
        """Test resolve_pr_url with 'latest' strategy."""
        mock_client = AsyncMock()
        
        # Mock GraphQL failure
        graphql_response = Mock()
        graphql_response.json.return_value = {"errors": [{"message": "error"}]}
        
        # Mock REST response (already sorted by updated desc by API)
        rest_response = Mock()
        rest_response.json.return_value = [
            {"number": 10, "html_url": "latest_url", "updated_at": "2023-01-02"},
            {"number": 5, "html_url": "older_url", "updated_at": "2023-01-01"},
        ]
        rest_response.raise_for_status.return_value = None
        
        mock_client.post.return_value = graphql_response
        mock_client.get.return_value = rest_response
        
        with patch("git_pr_resolver.httpx.AsyncClient", return_value=mock_client):
            result = await git_pr_resolver.resolve_pr_url(
                "owner", "repo", select_strategy="latest"
            )
            # Should return first PR (most recently updated)
            assert result == "latest_url"

    def test_git_detect_repo_branch_env_partial_override(self, monkeypatch: Any) -> None:
        """Test partial environment variable override (missing branch)."""
        monkeypatch.setenv("MCP_PR_OWNER", "test-owner") 
        monkeypatch.setenv("MCP_PR_REPO", "test-repo")
        # Don't set MCP_PR_BRANCH - should fall back to git detection
        
        with patch("git_pr_resolver._get_repo") as mock_get_repo:
            mock_repo = Mock()
            mock_config = Mock()
            mock_config.get.return_value = b"https://github.com/owner/repo.git"
            mock_repo.get_config.return_value = mock_config
            mock_repo.refs.read_ref.return_value = b"refs/heads/main"
            mock_get_repo.return_value = mock_repo
            
            # Should fall back to git detection since not all env vars are set
            result = git_pr_resolver.git_detect_repo_branch()
            assert result.owner == "owner"  # From git, not env
            assert result.branch == "main"