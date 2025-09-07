"""Additional tests to increase overall test coverage to 90%."""

import os
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest

import git_pr_resolver
import mcp_server
from mcp_server import ReviewSpecGenerator
from tests.test_utils import create_mock_response, mock_httpx_client


class TestCoverageBoost:
    """Tests specifically designed to boost coverage."""

    def test_parse_remote_url_edge_cases(self) -> None:
        """Test edge cases for parse_remote_url."""
        # Test SSH format without .git
        host, owner, repo = git_pr_resolver.parse_remote_url("git@github.com:owner/repo")
        assert host == "github.com"
        assert owner == "owner"
        assert repo == "repo"
        
        # Test HTTPS with trailing slash
        host, owner, repo = git_pr_resolver.parse_remote_url("https://github.com/owner/repo/")
        assert host == "github.com"
        
        # Test unsupported URL
        with pytest.raises(ValueError, match="Unsupported remote URL"):
            git_pr_resolver.parse_remote_url("ftp://invalid.com/repo")

    def test_get_repo_error_cases(self) -> None:
        """Test _get_repo error cases."""
        with tempfile.TemporaryDirectory() as temp_dir:
            with pytest.raises(ValueError, match="Not a git repository"):
                git_pr_resolver._get_repo(temp_dir)

    def test_api_base_variations(self, monkeypatch: Any) -> None:
        """Test api_base_for_host with different configurations."""
        # Test explicit override
        monkeypatch.setenv("GITHUB_API_URL", "https://custom.api.com/v3")
        result = git_pr_resolver.api_base_for_host("any-host")
        assert result == "https://custom.api.com/v3"
        
        # Test GitHub.com default
        monkeypatch.delenv("GITHUB_API_URL", raising=False)
        result = git_pr_resolver.api_base_for_host("github.com")
        assert result == "https://api.github.com"
        
        # Test Enterprise default
        result = git_pr_resolver.api_base_for_host("enterprise.example.com")
        assert result == "https://enterprise.example.com/api/v3"

    @pytest.mark.asyncio
    async def test_resolve_pr_url_invalid_strategy(self) -> None:
        """Test resolve_pr_url with invalid strategy."""
        with pytest.raises(ValueError, match="Invalid select_strategy"):
            await git_pr_resolver.resolve_pr_url("owner", "repo", select_strategy="invalid")

    def test_graphql_url_inference(self, monkeypatch: Any) -> None:
        """Test GraphQL URL inference logic."""
        # Test explicit GraphQL URL override
        monkeypatch.setenv("GITHUB_GRAPHQL_URL", "https://api.github.com/graphql")
        result = git_pr_resolver._graphql_url_for_host("github.com")
        assert result == "https://api.github.com/graphql"
        
        # Test REST API URL inference
        monkeypatch.delenv("GITHUB_GRAPHQL_URL", raising=False)
        monkeypatch.setenv("GITHUB_API_URL", "https://ghe.example.com/api/v3")
        result = git_pr_resolver._graphql_url_for_host("ghe.example.com")
        assert result == "https://ghe.example.com/api/graphql"
        
        # Test /api endpoint inference
        monkeypatch.setenv("GITHUB_API_URL", "https://ghe.example.com/api")
        result = git_pr_resolver._graphql_url_for_host("ghe.example.com")
        assert result == "https://ghe.example.com/api/graphql"
        
        # Test default GitHub.com
        monkeypatch.delenv("GITHUB_API_URL", raising=False)
        result = git_pr_resolver._graphql_url_for_host("github.com")
        assert result == "https://api.github.com/graphql"

    def test_html_pr_url_generation(self) -> None:
        """Test HTML PR URL generation."""
        url = git_pr_resolver._html_pr_url("github.com", "owner", "repo", 123)
        assert url == "https://github.com/owner/repo/pull/123"

    @pytest.mark.asyncio  
    async def test_graphql_find_pr_number_edge_cases(self, mock_httpx_client) -> None:
        """Test _graphql_find_pr_number edge cases."""
        # Test with invalid response data
        mock_response = create_mock_response(json_data="invalid")
        mock_httpx_client.add_post_response(mock_response)
        
        result = await git_pr_resolver._graphql_find_pr_number(
            mock_httpx_client, "github.com", {"Authorization": "token"}, "owner", "repo", "branch"
        )
        assert result is None
        
        # Test with errors in response
        mock_response = create_mock_response(json_data={"errors": [{"message": "error"}]})
        mock_httpx_client.add_post_response(mock_response)
        
        result = await git_pr_resolver._graphql_find_pr_number(
            mock_httpx_client, "github.com", {"Authorization": "token"}, "owner", "repo", "branch"
        )
        assert result is None
        
        # Test with empty nodes
        mock_response = create_mock_response(json_data={
            "data": {"repository": {"pullRequests": {"nodes": []}}}
        })
        mock_httpx_client.add_post_response(mock_response)
        
        result = await git_pr_resolver._graphql_find_pr_number(
            mock_httpx_client, "github.com", {"Authorization": "token"}, "owner", "repo", "branch"
        )
        assert result is None

    def test_generate_markdown_edge_cases(self) -> None:
        """Test generate_markdown with edge cases."""
        # Test with empty comments
        result = mcp_server.generate_markdown([])
        assert "# Pull Request Review Spec" in result
        assert "No comments found" in result
        
        # Test with comment containing nested backticks
        comments = [{
            "id": 1,
            "body": "Here's code with ```nested``` backticks",
            "path": "test.py",
            "position": 10,
            "line": 5,
            "user": {"login": "reviewer"}
        }]
        result = mcp_server.generate_markdown(comments)
        assert "````" in result  # Should use 4 backticks to escape the nested ones

    def test_server_init_coverage(self) -> None:
        """Test server initialization for coverage."""
        server = ReviewSpecGenerator()
        assert server.server is not None

    @pytest.mark.asyncio
    async def test_create_spec_filename_collision_handling(self) -> None:
        """Test filename collision handling in create_review_spec_file."""
        server = ReviewSpecGenerator()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create a file that will cause collision
            base_file = Path(temp_dir) / "review_specs" / "test.md"
            base_file.parent.mkdir()
            base_file.write_text("existing")
            
            # This should fail with FileExistsError since O_EXCL is used
            with patch("mcp_server.Path.cwd", return_value=Path(temp_dir)):
                result = await server.create_review_spec_file("# Test", "test.md")
                assert "Error in create_review_spec_file" in result

    @pytest.mark.asyncio
    async def test_fetch_pr_comments_with_branch_resolution(self) -> None:
        """Test fetch_pr_comments using branch resolution."""
        server = ReviewSpecGenerator()
        mock_comments = [{"id": 1, "body": "Test comment"}]
        
        with patch("mcp_server.git_detect_repo_branch") as mock_git, \
             patch("mcp_server.resolve_pr_url") as mock_resolve, \
             patch("mcp_server.fetch_pr_comments", return_value=mock_comments):
            
            mock_git.return_value = Mock(
                host="github.com", owner="test-owner", repo="test-repo", branch="main"
            )
            mock_resolve.return_value = "https://github.com/test-owner/test-repo/pull/42"
            
            result = await server.handle_call_tool(
                "fetch_pr_review_comments",
                {"use_git_context": True}
            )
            
            assert len(result) == 1
            mock_resolve.assert_called_once()

    def test_env_clamping_logic(self, monkeypatch: Any) -> None:
        """Test environment variable clamping in the module."""
        # The module defines constants that are used for validation
        assert mcp_server.PER_PAGE_MIN == 1
        assert mcp_server.PER_PAGE_MAX == 100
        assert mcp_server.MAX_PAGES_MIN == 1
        assert mcp_server.MAX_PAGES_MAX == 200

    @patch("git_pr_resolver._get_repo")
    def test_git_detect_no_remotes(self, mock_get_repo: Mock) -> None:
        """Test git detection when no remotes configured."""
        mock_repo = Mock()
        mock_config = Mock()
        mock_config.get.side_effect = KeyError("not found")
        mock_config.sections.return_value = []
        mock_repo.get_config.return_value = mock_config
        mock_get_repo.return_value = mock_repo
        
        with pytest.raises(ValueError, match="No git remote configured"):
            git_pr_resolver.git_detect_repo_branch()

    @patch("git_pr_resolver._get_repo")
    def test_git_detect_branch_fallback(self, mock_get_repo: Mock) -> None:
        """Test branch detection fallback logic."""
        mock_repo = Mock()
        mock_config = Mock()
        mock_config.get.return_value = b"https://github.com/owner/repo.git"
        mock_repo.get_config.return_value = mock_config
        
        # Mock detached HEAD scenario
        mock_repo.refs.read_ref.return_value = b"commit-hash"  # Not refs/heads/
        
        with patch("git_pr_resolver.porcelain.active_branch") as mock_active:
            mock_active.side_effect = Exception("Failed")
            mock_get_repo.return_value = mock_repo
            
            with pytest.raises(ValueError, match="Unable to determine current branch"):
                git_pr_resolver.git_detect_repo_branch()