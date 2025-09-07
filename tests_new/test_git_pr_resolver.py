"""
Test suite for git PR resolver functionality.

Tests all aspects of git repository detection and GitHub PR URL resolution:
- Git remote URL parsing (HTTPS and SSH)
- Repository and branch detection
- GitHub API URL construction
- PR resolution strategies (first, latest, branch-specific)
- GraphQL fallback handling
"""

import tempfile
from unittest.mock import Mock, patch

import pytest

import git_pr_resolver
from conftest import create_mock_response


class TestRemoteUrlParsing:
    """Test parsing of git remote URLs in various formats."""

    def test_parse_https_urls(self) -> None:
        """Test parsing HTTPS remote URLs."""
        test_cases = [
            ("https://github.com/owner/repo", ("github.com", "owner", "repo")),
            ("https://github.com/owner/repo.git", ("github.com", "owner", "repo")),
            (
                "https://github.mycorp.com/team/project",
                ("github.mycorp.com", "team", "project"),
            ),
            (
                "https://ghe.example.com/user/repo.git",
                ("ghe.example.com", "user", "repo"),
            ),
        ]

        for url, expected in test_cases:
            result = git_pr_resolver.parse_remote_url(url)
            assert result == expected, f"Failed to parse {url}"

    def test_parse_ssh_urls(self) -> None:
        """Test parsing SSH remote URLs."""
        test_cases = [
            ("git@github.com:owner/repo.git", ("github.com", "owner", "repo")),
            ("git@github.com:owner/repo", ("github.com", "owner", "repo")),
            (
                "git@github.mycorp.com:team/project.git",
                ("github.mycorp.com", "team", "project"),
            ),
            ("git@ghe.example.com:user/repo", ("ghe.example.com", "user", "repo")),
        ]

        for url, expected in test_cases:
            result = git_pr_resolver.parse_remote_url(url)
            assert result == expected, f"Failed to parse {url}"

    def test_parse_invalid_urls(self) -> None:
        """Test handling of invalid remote URL formats."""
        invalid_urls = [
            "not-a-url",
            "https://github.com/invalid",  # Missing repo
            "git@github.com:invalid",  # Missing repo
            "ftp://github.com/owner/repo",  # Wrong protocol
            "",  # Empty string
        ]

        for url in invalid_urls:
            with pytest.raises(ValueError, match="Unsupported remote URL"):
                git_pr_resolver.parse_remote_url(url)


class TestApiUrlConstruction:
    """Test GitHub API URL construction for different hosts."""

    def test_api_base_github_com(self) -> None:
        """Test API base URL for github.com."""
        result = git_pr_resolver.api_base_for_host("github.com")
        assert result == "https://api.github.com"

    def test_api_base_enterprise_hosts(self) -> None:
        """Test API base URL for GitHub Enterprise hosts."""
        test_cases = [
            ("github.mycorp.com", "https://github.mycorp.com/api/v3"),
            ("ghe.example.com", "https://ghe.example.com/api/v3"),
            ("git.company.com", "https://git.company.com/api/v3"),
        ]

        for host, expected in test_cases:
            result = git_pr_resolver.api_base_for_host(host)
            assert result == expected

    def test_api_base_with_environment_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test API base URL with GITHUB_API_URL environment override."""
        monkeypatch.setenv("GITHUB_API_URL", "https://custom.api.com/v3")

        # Should use override for any host
        result = git_pr_resolver.api_base_for_host("github.com")
        assert result == "https://custom.api.com/v3"

        result = git_pr_resolver.api_base_for_host("any-host.com")
        assert result == "https://custom.api.com/v3"

    def test_api_base_url_normalization(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that API URLs are properly normalized (trailing slash removal)."""
        monkeypatch.setenv("GITHUB_API_URL", "https://ghe.example.com/api/v3/")

        result = git_pr_resolver.api_base_for_host("ghe.example.com")
        assert result == "https://ghe.example.com/api/v3"  # No trailing slash


class TestGraphqlUrlConstruction:
    """Test GraphQL URL construction for different hosts."""

    def test_graphql_url_github_com(self) -> None:
        """Test GraphQL URL for github.com."""
        result = git_pr_resolver._graphql_url_for_host("github.com")
        assert result == "https://api.github.com/graphql"

    def test_graphql_url_enterprise_patterns(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test GraphQL URL construction for enterprise with various API patterns."""
        # Test different API URL patterns
        test_cases = [
            ("https://ghe.example.com/api/v3", "https://ghe.example.com/api/graphql"),
            ("https://ghe.example.com/api", "https://ghe.example.com/api/graphql"),
            ("https://ghe.example.com", "https://ghe.example.com/graphql"),
        ]

        for api_url, expected_graphql_url in test_cases:
            monkeypatch.setenv("GITHUB_API_URL", api_url)
            result = git_pr_resolver._graphql_url_for_host("ghe.example.com")
            assert result == expected_graphql_url

    def test_graphql_url_explicit_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test GraphQL URL with explicit GITHUB_GRAPHQL_URL override."""
        # Test with github.com override (should match)
        monkeypatch.setenv("GITHUB_GRAPHQL_URL", "https://api.github.com/graphql")
        result = git_pr_resolver._graphql_url_for_host("github.com")
        assert result == "https://api.github.com/graphql"

        # Test with custom host override
        monkeypatch.setenv("GITHUB_GRAPHQL_URL", "https://custom.graphql.com/graphql")
        result = git_pr_resolver._graphql_url_for_host("custom.graphql.com")
        assert result == "https://custom.graphql.com/graphql"


class TestGitRepositoryDetection:
    """Test git repository detection and context extraction."""

    def test_env_variable_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test git detection with environment variable overrides."""
        # Set environment variables
        monkeypatch.setenv("MCP_PR_OWNER", "env-owner")
        monkeypatch.setenv("MCP_PR_REPO", "env-repo")
        monkeypatch.setenv("MCP_PR_BRANCH", "env-branch")

        result = git_pr_resolver.git_detect_repo_branch("/some/path")

        assert result.owner == "env-owner"
        assert result.repo == "env-repo"
        assert result.branch == "env-branch"

    def test_git_repo_detection_from_remote(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test git repository detection from actual git remote."""
        # Clear environment variables to force git detection
        monkeypatch.delenv("MCP_PR_OWNER", raising=False)
        monkeypatch.delenv("MCP_PR_REPO", raising=False)
        monkeypatch.delenv("MCP_PR_BRANCH", raising=False)

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("git_pr_resolver._get_repo") as mock_get_repo:
                # Mock git repository
                mock_repo = Mock()
                mock_config = Mock()
                mock_config.get.return_value = (
                    b"https://github.com/test-owner/test-repo.git"
                )
                mock_repo.get_config.return_value = mock_config
                mock_repo.refs.read_ref.return_value = b"refs/heads/main"
                mock_get_repo.return_value = mock_repo

                result = git_pr_resolver.git_detect_repo_branch(temp_dir)

                assert result.host == "github.com"
                assert result.owner == "test-owner"
                assert result.repo == "test-repo"
                assert result.branch == "main"

    def test_git_detection_fallback_to_first_remote(self) -> None:
        """Test fallback to first available remote when origin is not configured."""
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("git_pr_resolver._get_repo") as mock_get_repo:
                mock_repo = Mock()
                mock_config = Mock()
                # origin remote fails, but upstream remote succeeds
                mock_config.get.side_effect = [
                    KeyError(),  # origin fails
                    b"https://github.com/upstream-owner/upstream-repo.git",  # upstream succeeds
                ]
                mock_config.sections.return_value = [(b"remote", b"upstream")]
                mock_repo.get_config.return_value = mock_config
                mock_repo.refs.read_ref.return_value = b"refs/heads/feature"
                mock_get_repo.return_value = mock_repo

                result = git_pr_resolver.git_detect_repo_branch(temp_dir)

                assert result.owner == "upstream-owner"
                assert result.repo == "upstream-repo"

    def test_git_detection_no_remote_configured(self) -> None:
        """Test error handling when no git remote is configured."""
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("git_pr_resolver._get_repo") as mock_get_repo:
                mock_repo = Mock()
                mock_config = Mock()
                mock_config.get.side_effect = KeyError()  # No remotes
                mock_config.sections.return_value = []  # No remote sections
                mock_repo.get_config.return_value = mock_config
                mock_get_repo.return_value = mock_repo

                with pytest.raises(ValueError, match="No git remote configured"):
                    git_pr_resolver.git_detect_repo_branch(temp_dir)

    def test_git_detection_detached_head_handling(self) -> None:
        """Test handling of detached HEAD state with active branch detection."""
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("git_pr_resolver._get_repo") as mock_get_repo:
                mock_repo = Mock()
                mock_config = Mock()
                mock_config.get.return_value = b"https://github.com/owner/repo.git"
                mock_repo.get_config.return_value = mock_config
                mock_repo.refs.read_ref.return_value = (
                    b"abc123"  # Detached HEAD (commit hash)
                )

                with patch(
                    "git_pr_resolver.porcelain.active_branch",
                    return_value=b"detached-branch",
                ):
                    mock_get_repo.return_value = mock_repo

                    result = git_pr_resolver.git_detect_repo_branch(temp_dir)
                    assert result.branch == "detached-branch"

    def test_git_detection_no_branch_determinable(self) -> None:
        """Test error handling when no branch can be determined."""
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("git_pr_resolver._get_repo") as mock_get_repo:
                mock_repo = Mock()
                mock_config = Mock()
                mock_config.get.return_value = b"https://github.com/owner/repo.git"
                mock_repo.get_config.return_value = mock_config
                mock_repo.refs.read_ref.return_value = b"abc123"  # Detached HEAD

                # Both methods fail
                with patch(
                    "git_pr_resolver.porcelain.active_branch",
                    side_effect=Exception("No branch"),
                ):
                    mock_get_repo.return_value = mock_repo

                    with pytest.raises(
                        ValueError, match="Unable to determine current branch"
                    ):
                        git_pr_resolver.git_detect_repo_branch(temp_dir)


class TestPrUrlResolution:
    """Test PR URL resolution with different strategies and configurations."""

    @pytest.mark.asyncio
    async def test_resolve_pr_branch_strategy_success(self, mock_http_client) -> None:
        """Test successful PR resolution using branch strategy."""
        # Mock successful REST API response
        mock_response = create_mock_response(
            [
                {
                    "number": 123,
                    "head": {"ref": "feature-branch"},
                    "html_url": "https://github.com/owner/repo/pull/123",
                }
            ]
        )
        mock_http_client.add_get_response(mock_response)

        result = await git_pr_resolver.resolve_pr_url(
            "owner", "repo", "feature-branch", select_strategy="branch"
        )

        assert result == "https://github.com/owner/repo/pull/123"

        # Verify correct API call was made
        calls = mock_http_client.get_calls
        assert len(calls) == 1
        assert "head=owner:feature-branch" in calls[0][0]

    @pytest.mark.asyncio
    async def test_resolve_pr_first_strategy(self, mock_http_client) -> None:
        """Test PR resolution using first strategy (lowest PR number)."""
        # Mock REST API response with multiple PRs
        mock_response = create_mock_response(
            [
                {"number": 456, "html_url": "https://github.com/owner/repo/pull/456"},
                {
                    "number": 123,
                    "html_url": "https://github.com/owner/repo/pull/123",
                },  # Should be selected
                {"number": 789, "html_url": "https://github.com/owner/repo/pull/789"},
            ]
        )
        mock_http_client.add_get_response(mock_response)

        result = await git_pr_resolver.resolve_pr_url(
            "owner", "repo", select_strategy="first"
        )

        assert result == "https://github.com/owner/repo/pull/123"

    @pytest.mark.asyncio
    async def test_resolve_pr_latest_strategy(self, mock_http_client) -> None:
        """Test PR resolution using latest strategy (most recently updated)."""
        # Mock REST API response (API returns in updated_at desc order)
        mock_response = create_mock_response(
            [
                {
                    "number": 456,
                    "html_url": "https://github.com/owner/repo/pull/456",
                    "updated_at": "2023-01-02T00:00:00Z",
                },
                {
                    "number": 123,
                    "html_url": "https://github.com/owner/repo/pull/123",
                    "updated_at": "2023-01-01T00:00:00Z",
                },
            ]
        )
        mock_http_client.add_get_response(mock_response)

        result = await git_pr_resolver.resolve_pr_url(
            "owner", "repo", select_strategy="latest"
        )

        # Should select first (most recent) PR
        assert result == "https://github.com/owner/repo/pull/456"

    @pytest.mark.asyncio
    async def test_resolve_pr_graphql_success(self, mock_http_client) -> None:
        """Test successful GraphQL PR resolution."""
        # Mock successful GraphQL response
        graphql_response = create_mock_response(
            {
                "data": {
                    "repository": {
                        "pullRequests": {
                            "nodes": [{"number": 789, "headRefName": "feature-branch"}]
                        }
                    }
                }
            }
        )
        mock_http_client.add_post_response(graphql_response)

        result = await git_pr_resolver.resolve_pr_url("owner", "repo", "feature-branch")

        assert result == "https://github.com/owner/repo/pull/789"

        # Should have made only GraphQL call (no REST fallback needed)
        assert len(mock_http_client.get_calls) == 0  # No REST calls
        assert len(mock_http_client.post_calls) == 1  # GraphQL call

    @pytest.mark.asyncio
    async def test_resolve_pr_no_results_found(self, mock_http_client) -> None:
        """Test error handling when no PRs are found."""
        # Mock empty REST response
        empty_rest = create_mock_response([])
        mock_http_client.add_get_response(empty_rest)

        # Mock empty GraphQL response
        empty_graphql = create_mock_response(
            {"data": {"repository": {"pullRequests": {"nodes": []}}}}
        )
        mock_http_client.add_post_response(empty_graphql)

        with pytest.raises(ValueError, match="No open PRs found"):
            await git_pr_resolver.resolve_pr_url("owner", "repo")

    @pytest.mark.asyncio
    async def test_resolve_pr_branch_not_found(self, mock_http_client) -> None:
        """Test error when specific branch PR is not found."""
        # Mock REST response for specific branch (empty)
        empty_branch_response = create_mock_response([])
        mock_http_client.add_get_response(empty_branch_response)

        # Mock REST response for all PRs (different branches)
        all_prs_response = create_mock_response(
            [{"number": 123, "head": {"ref": "different-branch"}, "html_url": "url"}]
        )
        mock_http_client.add_get_response(all_prs_response)

        with pytest.raises(ValueError, match="No open PR found for branch"):
            await git_pr_resolver.resolve_pr_url(
                "owner", "repo", "missing-branch", select_strategy="branch"
            )

    @pytest.mark.asyncio
    async def test_resolve_pr_invalid_strategy(self) -> None:
        """Test error handling for invalid selection strategy."""
        with pytest.raises(ValueError, match="Invalid select_strategy"):
            await git_pr_resolver.resolve_pr_url(
                "owner", "repo", select_strategy="invalid"
            )

    @pytest.mark.asyncio
    async def test_resolve_pr_debug_logging(
        self, mock_http_client, debug_logging_enabled
    ) -> None:
        """Test that debug logging works correctly."""
        # Mock GraphQL failure to trigger debug logging
        graphql_response = create_mock_response(
            json_data={"errors": [{"message": "GraphQL error"}]},
            raise_for_status_side_effect=Exception("GraphQL failed"),
        )
        mock_http_client.add_post_response(graphql_response)

        # Mock successful REST fallback
        rest_response = create_mock_response(
            [{"number": 123, "html_url": "https://github.com/owner/repo/pull/123"}]
        )
        mock_http_client.add_get_response(rest_response)

        # Should succeed despite GraphQL failure (using latest strategy since no branch provided)
        result = await git_pr_resolver.resolve_pr_url(
            "owner", "repo", select_strategy="latest"
        )
        assert result == "https://github.com/owner/repo/pull/123"


class TestGraphqlHandling:
    """Test GraphQL query handling and error scenarios."""

    @pytest.mark.asyncio
    async def test_graphql_find_pr_success(self, mock_http_client) -> None:
        """Test successful GraphQL PR finding."""
        from unittest.mock import AsyncMock

        mock_response = create_mock_response(
            {
                "data": {
                    "repository": {
                        "pullRequests": {
                            "nodes": [{"number": 456, "headRefName": "feature-branch"}]
                        }
                    }
                }
            }
        )

        # Create a proper async mock client
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        result = await git_pr_resolver._graphql_find_pr_number(
            mock_client, "github.com", {}, "owner", "repo", "feature-branch"
        )

        assert result == 456

    @pytest.mark.asyncio
    async def test_graphql_error_response(self, mock_http_client) -> None:
        """Test handling of GraphQL error responses."""
        from unittest.mock import AsyncMock

        mock_response = create_mock_response(
            {"errors": [{"message": "Repository not found"}]}
        )

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        result = await git_pr_resolver._graphql_find_pr_number(
            mock_client, "github.com", {}, "owner", "repo", "feature-branch"
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_graphql_no_matching_pr(self, mock_http_client) -> None:
        """Test GraphQL response with no matching PR."""
        from unittest.mock import AsyncMock

        mock_response = create_mock_response(
            {
                "data": {
                    "repository": {
                        "pullRequests": {
                            "nodes": []  # Empty results
                        }
                    }
                }
            }
        )

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        result = await git_pr_resolver._graphql_find_pr_number(
            mock_client, "github.com", {}, "owner", "repo", "missing-branch"
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_graphql_malformed_response(self, mock_http_client) -> None:
        """Test handling of malformed GraphQL responses."""
        from unittest.mock import AsyncMock

        malformed_responses = [
            {},  # Empty response
            {"data": None},  # Null data
            {"data": {"repository": None}},  # Null repository
            {"data": {"repository": {"pullRequests": None}}},  # Null pullRequests
        ]

        for response_data in malformed_responses:
            mock_response = create_mock_response(response_data)
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response

            result = await git_pr_resolver._graphql_find_pr_number(
                mock_client, "github.com", {}, "owner", "repo", "branch"
            )

            assert result is None
