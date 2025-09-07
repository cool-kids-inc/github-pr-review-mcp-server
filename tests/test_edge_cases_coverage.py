"""Additional edge case tests to push coverage to 90%."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch, Mock

import pytest

import git_pr_resolver
import mcp_server
from tests.test_utils import create_mock_response, mock_httpx_client


class TestEdgeCasesCoverage:
    """Edge case tests to improve coverage."""

    def test_git_detect_repo_branch_no_env_vars(self, monkeypatch) -> None:
        """Test git_detect_repo_branch when no env vars are set."""
        # Clear all environment variables
        monkeypatch.delenv("MCP_PR_OWNER", raising=False)
        monkeypatch.delenv("MCP_PR_REPO", raising=False)
        monkeypatch.delenv("MCP_PR_BRANCH", raising=False)
        
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("git_pr_resolver._get_repo") as mock_get_repo:
                mock_repo = Mock()
                mock_config = Mock()
                mock_config.get.return_value = b"https://github.com/owner/repo.git"
                mock_repo.get_config.return_value = mock_config
                mock_repo.refs.read_ref.return_value = b"refs/heads/main"
                mock_get_repo.return_value = mock_repo
                
                result = git_pr_resolver.git_detect_repo_branch(temp_dir)
                assert result.host == "github.com"
                assert result.owner == "owner"
                assert result.repo == "repo"
                assert result.branch == "main"

    def test_git_detect_repo_branch_detached_head(self, monkeypatch) -> None:
        """Test git_detect_repo_branch with detached HEAD."""
        monkeypatch.delenv("MCP_PR_OWNER", raising=False)
        monkeypatch.delenv("MCP_PR_REPO", raising=False)
        monkeypatch.delenv("MCP_PR_BRANCH", raising=False)
        
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("git_pr_resolver._get_repo") as mock_get_repo:
                mock_repo = Mock()
                mock_config = Mock()
                mock_config.get.return_value = b"https://github.com/owner/repo.git"
                mock_repo.get_config.return_value = mock_config
                mock_repo.refs.read_ref.return_value = b"abc123"  # Detached HEAD
                
                # Mock porcelain.active_branch to return a branch name
                with patch("git_pr_resolver.porcelain.active_branch", return_value=b"detached-branch"):
                    mock_get_repo.return_value = mock_repo
                    
                    result = git_pr_resolver.git_detect_repo_branch(temp_dir)
                    assert result.branch == "detached-branch"

    def test_git_detect_repo_branch_no_remote_origin(self, monkeypatch) -> None:
        """Test git_detect_repo_branch when origin remote is not configured."""
        monkeypatch.delenv("MCP_PR_OWNER", raising=False)
        monkeypatch.delenv("MCP_PR_REPO", raising=False)
        monkeypatch.delenv("MCP_PR_BRANCH", raising=False)
        
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("git_pr_resolver._get_repo") as mock_get_repo:
                mock_repo = Mock()
                mock_config = Mock()
                # First call (origin) raises KeyError, second call (first remote) succeeds
                mock_config.get.side_effect = [KeyError(), b"https://github.com/owner/repo.git"]
                mock_config.sections.return_value = [(b"remote", b"upstream")]
                mock_repo.get_config.return_value = mock_config
                mock_repo.refs.read_ref.return_value = b"refs/heads/main"
                mock_get_repo.return_value = mock_repo
                
                result = git_pr_resolver.git_detect_repo_branch(temp_dir)
                assert result.host == "github.com"
                assert result.owner == "owner"
                assert result.repo == "repo"

    def test_api_base_for_host_enterprise(self) -> None:
        """Test api_base_for_host with enterprise host."""
        result = git_pr_resolver.api_base_for_host("enterprise.example.com")
        assert result == "https://enterprise.example.com/api/v3"

    def test_api_base_for_host_explicit_override(self, monkeypatch) -> None:
        """Test api_base_for_host with explicit GITHUB_API_URL override."""
        monkeypatch.setenv("GITHUB_API_URL", "https://custom.api.com/v3")
        result = git_pr_resolver.api_base_for_host("any-host")
        assert result == "https://custom.api.com/v3"

    def test_graphql_url_for_host_enterprise_patterns(self, monkeypatch) -> None:
        """Test _graphql_url_for_host with different enterprise patterns."""
        # Test with /api/v3 pattern
        monkeypatch.setenv("GITHUB_API_URL", "https://ghe.example/api/v3")
        result = git_pr_resolver._graphql_url_for_host("ghe.example")
        assert result == "https://ghe.example/api/graphql"
        
        # Test with /api pattern
        monkeypatch.setenv("GITHUB_API_URL", "https://ghe.example/api")
        result = git_pr_resolver._graphql_url_for_host("ghe.example")
        assert result == "https://ghe.example/api/graphql"
        
        # Test with base pattern
        monkeypatch.setenv("GITHUB_API_URL", "https://ghe.example")
        result = git_pr_resolver._graphql_url_for_host("ghe.example")
        assert result == "https://ghe.example/graphql"

    def test_graphql_url_for_host_mismatched_explicit(self, monkeypatch) -> None:
        """Test _graphql_url_for_host with mismatched explicit URL."""
        # Set explicit URL for github.com but test with different host
        monkeypatch.setenv("GITHUB_GRAPHQL_URL", "https://api.github.com/graphql")
        result = git_pr_resolver._graphql_url_for_host("enterprise.example.com")
        # Should use default enterprise pattern, not the explicit github.com URL
        assert result == "https://enterprise.example.com/api/graphql"

    @pytest.mark.asyncio
    async def test_fetch_pr_comments_retry_logic(self, mock_httpx_client) -> None:
        """Test fetch_pr_comments retry logic with server errors."""
        # Mock server error response that will trigger retry
        error_response = create_mock_response(
            status_code=500,
            raise_for_status_side_effect=Exception("Server error")
        )
        
        # Mock successful response after retry
        success_response = create_mock_response(
            json_data=[{"id": 1, "body": "Test comment"}]
        )
        
        mock_httpx_client.add_get_response(error_response)
        mock_httpx_client.add_get_response(success_response)
        
        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            result = await mcp_server.fetch_pr_comments("owner", "repo", 123, max_retries=1)
            # Should return the successful result after retry
            assert result is not None

    @pytest.mark.asyncio
    async def test_fetch_pr_comments_rate_limit_handling(self, mock_httpx_client) -> None:
        """Test fetch_pr_comments rate limit handling."""
        # Mock rate limit response
        rate_limit_response = create_mock_response(
            status_code=429,
            headers={"Retry-After": "2"}
        )
        
        # Mock successful response after rate limit
        success_response = create_mock_response(
            json_data=[{"id": 1, "body": "Test comment"}]
        )
        
        mock_httpx_client.add_get_response(rate_limit_response)
        mock_httpx_client.add_get_response(success_response)
        
        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            result = await mcp_server.fetch_pr_comments("owner", "repo", 123)
            # Should return the successful result after rate limit handling
            assert result is not None

    def test_generate_markdown_with_diff_hunk(self) -> None:
        """Test generate_markdown with diff_hunk field."""
        comments = [{
            "id": 1,
            "body": "Test comment",
            "path": "test.py",
            "line": 10,
            "user": {"login": "testuser"},
            "diff_hunk": "@@ -1,1 +1,1 @@\n-old\n+new"
        }]
        
        result = mcp_server.generate_markdown(comments)
        assert "**Code Snippet:**" in result
        assert "```diff" in result
        assert "old" in result
        assert "new" in result

    def test_generate_markdown_fence_calculation(self) -> None:
        """Test generate_markdown fence calculation with many backticks."""
        comments = [{
            "id": 1,
            "body": "Code with ```````nested` backticks",  # 7 backticks
            "path": "test.py",
            "line": 10,
            "user": {"login": "testuser"}
        }]
        
        result = mcp_server.generate_markdown(comments)
        # Should use 8 backticks to escape the 7 backticks
        assert "````````" in result
