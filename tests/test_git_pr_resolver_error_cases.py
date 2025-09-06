"""Tests for git_pr_resolver error cases and edge paths."""

import os
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest

from git_pr_resolver import (
    _get_repo,
    api_base_for_host,
    git_detect_repo_branch,
    parse_remote_url,
    resolve_pr_url,
)


class TestParseRemoteUrl:
    """Test parse_remote_url function."""

    def test_parse_remote_url_unsupported_format(self) -> None:
        """Test parse_remote_url with unsupported URL format."""
        with pytest.raises(ValueError, match="Unsupported remote URL"):
            parse_remote_url("invalid-url-format")

    def test_parse_remote_url_ssh_format(self) -> None:
        """Test parse_remote_url with SSH format."""
        host, owner, repo = parse_remote_url("git@github.com:owner/repo.git")
        assert host == "github.com"
        assert owner == "owner"
        assert repo == "repo"

    def test_parse_remote_url_https_without_git(self) -> None:
        """Test parse_remote_url with HTTPS format without .git."""
        host, owner, repo = parse_remote_url("https://github.com/owner/repo")
        assert host == "github.com"
        assert owner == "owner"
        assert repo == "repo"


class TestGetRepo:
    """Test _get_repo function."""

    def test_get_repo_not_git_repository(self) -> None:
        """Test _get_repo when not in a git repository."""
        with tempfile.TemporaryDirectory() as temp_dir:
            with pytest.raises(ValueError, match="Not a git repository"):
                _get_repo(temp_dir)


class TestGitDetectRepoBranch:
    """Test git_detect_repo_branch function."""

    def test_env_override(self, monkeypatch: Any) -> None:
        """Test environment variable override."""
        monkeypatch.setenv("MCP_PR_OWNER", "test-owner")
        monkeypatch.setenv("MCP_PR_REPO", "test-repo")
        monkeypatch.setenv("MCP_PR_BRANCH", "test-branch")
        monkeypatch.setenv("GH_HOST", "example.com")
        
        result = git_detect_repo_branch()
        assert result.owner == "test-owner"
        assert result.repo == "test-repo"
        assert result.branch == "test-branch"
        assert result.host == "example.com"

    def test_env_override_default_host(self, monkeypatch: Any) -> None:
        """Test environment variable override with default host."""
        monkeypatch.setenv("MCP_PR_OWNER", "test-owner")
        monkeypatch.setenv("MCP_PR_REPO", "test-repo")
        monkeypatch.setenv("MCP_PR_BRANCH", "test-branch")
        monkeypatch.delenv("GH_HOST", raising=False)
        
        result = git_detect_repo_branch()
        assert result.host == "github.com"

    @patch("git_pr_resolver._get_repo")
    def test_no_origin_remote_fallback(self, mock_get_repo: Mock) -> None:
        """Test fallback when origin remote doesn't exist."""
        # Mock repo with no origin remote but has another remote
        mock_repo = Mock()
        mock_config = Mock()
        
        # Mock config.get to raise KeyError for origin, but provide fallback
        def mock_config_get(section: Any, key: Any) -> bytes:
            if section == (b"remote", b"origin") and key == b"url":
                raise KeyError("origin not found")
            if section == (b"remote", b"upstream") and key == b"url":
                return b"https://github.com/owner/repo.git"
            raise KeyError("not found")
        
        def mock_sections() -> list[tuple[bytes, ...]]:
            return [(b"remote", b"upstream")]
        
        mock_config.get.side_effect = mock_config_get
        mock_config.sections.return_value = mock_sections()
        mock_repo.get_config.return_value = mock_config
        
        # Mock refs for branch detection
        mock_repo.refs.read_ref.return_value = b"refs/heads/main"
        mock_get_repo.return_value = mock_repo
        
        result = git_detect_repo_branch()
        assert result.owner == "owner"
        assert result.repo == "repo"
        assert result.branch == "main"

    @patch("git_pr_resolver._get_repo")
    def test_no_remotes_configured(self, mock_get_repo: Mock) -> None:
        """Test error when no remotes are configured."""
        mock_repo = Mock()
        mock_config = Mock()
        
        # Mock config with no remotes
        mock_config.get.side_effect = KeyError("not found")
        mock_config.sections.return_value = []
        mock_repo.get_config.return_value = mock_config
        mock_get_repo.return_value = mock_repo
        
        with pytest.raises(ValueError, match="No git remote configured"):
            git_detect_repo_branch()

    @patch("git_pr_resolver._get_repo")
    def test_detached_head_with_porcelain_fallback(self, mock_get_repo: Mock) -> None:
        """Test detached HEAD with porcelain.active_branch fallback."""
        mock_repo = Mock()
        mock_config = Mock()
        
        # Configure mock for remote
        mock_config.get.return_value = b"https://github.com/owner/repo.git"
        mock_repo.get_config.return_value = mock_config
        
        # Mock detached HEAD
        mock_repo.refs.read_ref.return_value = b"abc123"  # Not refs/heads/
        
        with patch("git_pr_resolver.porcelain.active_branch") as mock_active_branch:
            mock_active_branch.return_value = b"feature-branch"
            mock_get_repo.return_value = mock_repo
            
            result = git_detect_repo_branch()
            assert result.branch == "feature-branch"

    @patch("git_pr_resolver._get_repo")
    def test_unable_to_determine_branch(self, mock_get_repo: Mock) -> None:
        """Test error when unable to determine current branch."""
        mock_repo = Mock()
        mock_config = Mock()
        
        # Configure mock for remote
        mock_config.get.return_value = b"https://github.com/owner/repo.git"
        mock_repo.get_config.return_value = mock_config
        
        # Mock detached HEAD and failing porcelain
        mock_repo.refs.read_ref.return_value = b"abc123"  # Not refs/heads/
        
        with patch("git_pr_resolver.porcelain.active_branch") as mock_active_branch:
            mock_active_branch.side_effect = Exception("Failed to get branch")
            mock_get_repo.return_value = mock_repo
            
            with pytest.raises(ValueError, match="Unable to determine current branch"):
                git_detect_repo_branch()


class TestApiBaseForHost:
    """Test api_base_for_host function."""

    def test_explicit_github_api_url(self, monkeypatch: Any) -> None:
        """Test explicit GITHUB_API_URL override."""
        monkeypatch.setenv("GITHUB_API_URL", "https://custom.api.com/v3/")
        result = api_base_for_host("github.com")
        assert result == "https://custom.api.com/v3"

    def test_github_com_default(self, monkeypatch: Any) -> None:
        """Test GitHub.com default API base."""
        monkeypatch.delenv("GITHUB_API_URL", raising=False)
        result = api_base_for_host("github.com")
        assert result == "https://api.github.com"

    def test_github_enterprise(self, monkeypatch: Any) -> None:
        """Test GitHub Enterprise default pattern."""
        monkeypatch.delenv("GITHUB_API_URL", raising=False)
        result = api_base_for_host("github.example.com")
        assert result == "https://github.example.com/api/v3"


class TestResolvePrUrl:
    """Test resolve_pr_url function."""

    @pytest.mark.asyncio
    async def test_invalid_select_strategy(self) -> None:
        """Test invalid select_strategy parameter."""
        with pytest.raises(ValueError, match="Invalid select_strategy"):
            await resolve_pr_url("owner", "repo", select_strategy="invalid")