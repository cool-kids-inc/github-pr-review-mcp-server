"""
Tests for git_pr_resolver module.

This module tests all functionality related to:
- Git repository detection and parsing
- GitHub API URL resolution
- PR URL resolution strategies
- Remote URL parsing
- GraphQL query handling
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

import git_pr_resolver
from tests.conftest import create_mock_response, mock_httpx_client


class TestParseRemoteUrl:
    """Test remote URL parsing functionality."""

    def test_parse_remote_url_https_variants(self) -> None:
        """Test parsing HTTPS remote URLs with various formats."""
        # Standard HTTPS URLs
        assert git_pr_resolver.parse_remote_url("https://github.com/a/b") == ("github.com", "a", "b")
        assert git_pr_resolver.parse_remote_url("https://github.com/a/b.git") == ("github.com", "a", "b")
        
        # Enterprise GitHub URLs
        assert git_pr_resolver.parse_remote_url("https://github.mycorp.com/owner/repo") == ("github.mycorp.com", "owner", "repo")
        assert git_pr_resolver.parse_remote_url("https://ghe.example.com/user/project.git") == ("ghe.example.com", "user", "project")

    def test_parse_remote_url_ssh_variants(self) -> None:
        """Test parsing SSH remote URLs with various formats."""
        # Standard SSH URLs
        assert git_pr_resolver.parse_remote_url("git@github.com:a/b.git") == ("github.com", "a", "b")
        assert git_pr_resolver.parse_remote_url("git@github.com:a/b") == ("github.com", "a", "b")
        
        # Enterprise SSH URLs
        assert git_pr_resolver.parse_remote_url("git@github.mycorp.com:owner/repo.git") == ("github.mycorp.com", "owner", "repo")
        assert git_pr_resolver.parse_remote_url("git@ghe.example.com:user/project") == ("ghe.example.com", "user", "project")

    def test_parse_remote_url_invalid_formats(self) -> None:
        """Test parsing invalid remote URL formats."""
        with pytest.raises(ValueError, match="Invalid remote URL format"):
            git_pr_resolver.parse_remote_url("not-a-url")
        
        with pytest.raises(ValueError, match="Invalid remote URL format"):
            git_pr_resolver.parse_remote_url("https://github.com/invalid")
        
        with pytest.raises(ValueError, match="Invalid remote URL format"):
            git_pr_resolver.parse_remote_url("git@github.com:invalid")


class TestApiBaseForHost:
    """Test API base URL resolution for different hosts."""

    def test_api_base_for_host_github_com(self) -> None:
        """Test API base URL for github.com."""
        result = git_pr_resolver.api_base_for_host("github.com")
        assert result == "https://api.github.com"

    def test_api_base_for_host_enterprise(self) -> None:
        """Test API base URL for enterprise GitHub instances."""
        result = git_pr_resolver.api_base_for_host("enterprise.example.com")
        assert result == "https://enterprise.example.com/api/v3"

    def test_api_base_for_host_explicit_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test API base URL with explicit GITHUB_API_URL override."""
        monkeypatch.setenv("GITHUB_API_URL", "https://custom.api.com/v3")
        result = git_pr_resolver.api_base_for_host("any-host")
        assert result == "https://custom.api.com/v3"

    def test_api_base_for_host_override_normalization(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that API URL override is properly normalized."""
        monkeypatch.setenv("GITHUB_API_URL", "https://ghe.example/api/v3/")
        result = git_pr_resolver.api_base_for_host("anything")
        assert result == "https://ghe.example/api/v3"


class TestGraphqlUrlForHost:
    """Test GraphQL URL resolution for different hosts."""

    def test_graphql_url_for_host_github_com(self) -> None:
        """Test GraphQL URL for github.com."""
        result = git_pr_resolver._graphql_url_for_host("github.com")
        assert result == "https://api.github.com/graphql"

    def test_graphql_url_for_host_enterprise_patterns(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test GraphQL URL for enterprise instances with different patterns."""
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

    def test_graphql_url_for_host_explicit_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test GraphQL URL with explicit GITHUB_GRAPHQL_URL override."""
        monkeypatch.setenv("GITHUB_GRAPHQL_URL", "https://custom.graphql.com/graphql")
        result = git_pr_resolver._graphql_url_for_host("github.com")
        assert result == "https://custom.graphql.com/graphql"

    def test_graphql_url_for_host_mismatched_explicit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test GraphQL URL with mismatched explicit URL for different host."""
        # Set explicit URL for github.com but test with different host
        monkeypatch.setenv("GITHUB_GRAPHQL_URL", "https://api.github.com/graphql")
        result = git_pr_resolver._graphql_url_for_host("enterprise.example.com")
        # Should use default enterprise pattern, not the explicit github.com URL
        assert result == "https://enterprise.example.com/api/graphql"


class TestGitDetectRepoBranch:
    """Test git repository detection and branch resolution."""

    def test_git_detect_repo_branch_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test git detection with environment variable overrides."""
        monkeypatch.setenv("MCP_PR_OWNER", "test-owner")
        monkeypatch.setenv("MCP_PR_REPO", "test-repo")
        monkeypatch.setenv("MCP_PR_BRANCH", "test-branch")
        
        result = git_pr_resolver.git_detect_repo_branch("/some/path")
        assert result.owner == "test-owner"
        assert result.repo == "test-repo"
        assert result.branch == "test-branch"

    def test_git_detect_repo_branch_no_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test git detection when no environment variables are set."""
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

    def test_git_detect_repo_branch_detached_head_with_branch(self) -> None:
        """Test git detection with detached HEAD but active branch."""
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

    def test_git_detect_repo_branch_no_origin_fallback(self) -> None:
        """Test git detection when origin remote is not configured."""
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

    def test_git_detect_repo_branch_no_remote_configured(self) -> None:
        """Test git detection when no remote is configured."""
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("git_pr_resolver._get_repo") as mock_get_repo:
                mock_repo = Mock()
                mock_config = Mock()
                # No remotes configured
                mock_config.get.side_effect = KeyError()
                mock_config.sections.return_value = []
                mock_repo.get_config.return_value = mock_config
                mock_get_repo.return_value = mock_repo
                
                with pytest.raises(ValueError, match="No git remote configured"):
                    git_pr_resolver.git_detect_repo_branch(temp_dir)

    def test_git_detect_repo_branch_no_branch_detected(self) -> None:
        """Test git detection when no branch can be detected."""
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("git_pr_resolver._get_repo") as mock_get_repo:
                mock_repo = Mock()
                mock_config = Mock()
                mock_config.get.return_value = b"https://github.com/owner/repo.git"
                mock_repo.get_config.return_value = mock_config
                mock_repo.refs.read_ref.return_value = b"abc123"  # Detached HEAD
                
                # Mock porcelain.active_branch to also fail
                with patch("git_pr_resolver.porcelain.active_branch", side_effect=Exception("No branch")):
                    mock_get_repo.return_value = mock_repo
                    
                    with pytest.raises(ValueError, match="Unable to determine current branch"):
                        git_pr_resolver.git_detect_repo_branch(temp_dir)


class TestResolvePrUrl:
    """Test PR URL resolution with different strategies."""

    @pytest.mark.asyncio
    async def test_resolve_pr_url_first_strategy(self, mock_httpx_client) -> None:
        """Test PR URL resolution using first strategy."""
        # Mock successful REST API response
        mock_response = create_mock_response(json_data=[
            {"number": 123, "head": {"ref": "feature-branch"}}
        ])
        mock_httpx_client.add_get_response(mock_response)
        
        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            result = await git_pr_resolver.resolve_pr_url("owner", "repo", "feature-branch")
            assert result == "https://github.com/owner/repo/pull/123"

    @pytest.mark.asyncio
    async def test_resolve_pr_url_latest_strategy(self, mock_httpx_client) -> None:
        """Test PR URL resolution using latest strategy."""
        # Mock REST API response with multiple PRs
        mock_response = create_mock_response(json_data=[
            {"number": 100, "head": {"ref": "feature-branch"}, "created_at": "2023-01-01T00:00:00Z"},
            {"number": 123, "head": {"ref": "feature-branch"}, "created_at": "2023-01-02T00:00:00Z"}
        ])
        mock_httpx_client.add_get_response(mock_response)
        
        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            result = await git_pr_resolver.resolve_pr_url("owner", "repo", "feature-branch", select_strategy="latest")
            assert result == "https://github.com/owner/repo/pull/123"

    @pytest.mark.asyncio
    async def test_resolve_pr_url_graphql_fallback(self, mock_httpx_client) -> None:
        """Test PR URL resolution with GraphQL fallback."""
        # Mock empty REST API response
        empty_response = create_mock_response(json_data=[])
        mock_httpx_client.add_get_response(empty_response)
        
        # Mock successful GraphQL response
        graphql_response = create_mock_response(json_data={
            "data": {
                "repository": {
                    "pullRequests": {
                        "nodes": [{"number": 456, "headRefName": "feature-branch"}]
                    }
                }
            }
        })
        mock_httpx_client.add_post_response(graphql_response)
        
        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            result = await git_pr_resolver.resolve_pr_url("owner", "repo", "feature-branch")
            assert result == "https://github.com/owner/repo/pull/456"

    @pytest.mark.asyncio
    async def test_resolve_pr_url_no_branch_info(self, mock_httpx_client) -> None:
        """Test PR URL resolution with no branch info provided."""
        # Mock empty response
        empty_response = create_mock_response(json_data=[])
        mock_httpx_client.add_get_response(empty_response)
        
        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            with pytest.raises(ValueError, match="No open PRs found"):
                await git_pr_resolver.resolve_pr_url("owner", "repo")

    @pytest.mark.asyncio
    async def test_resolve_pr_url_invalid_strategy(self) -> None:
        """Test PR URL resolution with invalid strategy."""
        with pytest.raises(ValueError, match="Invalid select_strategy"):
            await git_pr_resolver.resolve_pr_url("owner", "repo", select_strategy="invalid")


class TestGraphqlFindPrNumber:
    """Test GraphQL PR number finding functionality."""

    @pytest.mark.asyncio
    async def test_graphql_find_pr_number_success(self, mock_httpx_client) -> None:
        """Test successful GraphQL PR number finding."""
        mock_response = create_mock_response(json_data={
            "data": {
                "repository": {
                    "pullRequests": {
                        "nodes": [{"number": 789, "headRefName": "feature-branch"}]
                    }
                }
            }
        })
        mock_httpx_client.add_post_response(mock_response)
        
        result = await git_pr_resolver._graphql_find_pr_number(
            mock_httpx_client, "github.com", {"Authorization": "token"}, "owner", "repo", "feature-branch"
        )
        assert result == 789

    @pytest.mark.asyncio
    async def test_graphql_find_pr_number_no_matches(self, mock_httpx_client) -> None:
        """Test GraphQL PR number finding with no matches."""
        mock_response = create_mock_response(json_data={
            "data": {"repository": {"pullRequests": {"nodes": []}}}
        })
        mock_httpx_client.add_post_response(mock_response)
        
        result = await git_pr_resolver._graphql_find_pr_number(
            mock_httpx_client, "github.com", {"Authorization": "token"}, "owner", "repo", "feature-branch"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_graphql_find_pr_number_errors(self, mock_httpx_client) -> None:
        """Test GraphQL PR number finding with GraphQL errors."""
        mock_response = create_mock_response(json_data={
            "errors": [{"message": "GraphQL error occurred"}]
        })
        mock_httpx_client.add_post_response(mock_response)
        
        result = await git_pr_resolver._graphql_find_pr_number(
            mock_httpx_client, "github.com", {"Authorization": "token"}, "owner", "repo", "feature-branch"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_graphql_find_pr_number_invalid_response(self, mock_httpx_client) -> None:
        """Test GraphQL PR number finding with invalid response data."""
        mock_response = create_mock_response(json_data="invalid")
        mock_httpx_client.add_post_response(mock_response)
        
        result = await git_pr_resolver._graphql_find_pr_number(
            mock_httpx_client, "github.com", {"Authorization": "token"}, "owner", "repo", "feature-branch"
        )
        assert result is None


class TestHtmlPrUrl:
    """Test HTML PR URL generation."""

    def test_html_pr_url_generation(self) -> None:
        """Test HTML PR URL generation for different hosts."""
        # Standard GitHub
        url = git_pr_resolver._html_pr_url("github.com", "owner", "repo", 123)
        assert url == "https://github.com/owner/repo/pull/123"
        
        # Enterprise GitHub
        url = git_pr_resolver._html_pr_url("github.mycorp.com", "owner", "repo", 456)
        assert url == "https://github.mycorp.com/owner/repo/pull/456"