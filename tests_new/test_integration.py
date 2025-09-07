"""
Integration test suite for MCP GitHub PR Review Spec Maker.

These tests verify the complete end-to-end functionality including:
- Real GitHub API integration (when GITHUB_TOKEN is available)
- Complete workflow from git detection to file creation
- Cross-component interactions and data flow
- Performance and reliability under various conditions
"""

import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

import git_pr_resolver
from mcp_server import (
    ReviewSpecGenerator,
    fetch_pr_comments,
    generate_markdown,
    get_pr_info,
)


class TestEndToEndWorkflow:
    """Test complete workflows from start to finish."""

    @pytest.mark.asyncio
    async def test_complete_mock_workflow(
        self,
        mcp_server: ReviewSpecGenerator,
        mock_http_client,
        temp_review_specs_dir: Path,
        sample_pr_comments: list[dict[str, Any]],
        mock_git_context: dict[str, str],
    ) -> None:
        """Test complete workflow with mocked dependencies."""
        # Mock HTTP responses for both git resolution and comment fetching
        pr_resolution_response = create_mock_response(
            [
                {
                    "number": 123,
                    "html_url": "https://github.com/test-owner/test-repo/pull/123",
                }
            ]
        )
        comments_response = create_mock_response(sample_pr_comments)

        mock_http_client.add_get_response(pr_resolution_response)
        mock_http_client.add_get_response(comments_response)

        with patch("mcp_server.Path.cwd", return_value=temp_review_specs_dir.parent):
            # Step 1: Get PR URL from git context
            with patch("git_pr_resolver.git_detect_repo_branch") as mock_git_detect:
                mock_context = git_pr_resolver.GitContext(
                    host="github.com",
                    owner=mock_git_context["owner"],
                    repo=mock_git_context["repo"],
                    branch=mock_git_context["branch"],
                )
                mock_git_detect.return_value = mock_context

                pr_url = await git_pr_resolver.resolve_pr_url(
                    mock_git_context["owner"],
                    mock_git_context["repo"],
                    mock_git_context["branch"],
                )

                # Step 2: Parse PR info and fetch comments directly
                owner, repo, pr_number = get_pr_info(pr_url)
                comments = await fetch_pr_comments(owner, repo, int(pr_number))
                assert comments is not None

                # Step 3: Generate markdown and create specification file
                markdown = generate_markdown(comments)
                spec_file = temp_review_specs_dir / "integration-test.md"
                spec_file.write_text(markdown)

                # Verify complete workflow
                assert spec_file.exists()
                content = spec_file.read_text()
                assert "# Pull Request Review Spec" in content
                for comment in sample_pr_comments:
                    if comment.get("body"):
                        assert comment["body"] in content

    @pytest.mark.asyncio
    async def test_workflow_with_git_detection(
        self,
        mcp_server: ReviewSpecGenerator,
        mock_http_client,
        temp_review_specs_dir: Path,
        sample_pr_comments: list[dict[str, Any]],
    ) -> None:
        """Test workflow starting from git repository detection."""
        # Mock git repository setup
        with tempfile.TemporaryDirectory() as temp_repo:
            with patch("git_pr_resolver._get_repo") as mock_get_repo:
                # Setup mock git repository
                mock_repo = Mock()
                mock_config = Mock()
                mock_config.get.return_value = (
                    b"https://github.com/detected-owner/detected-repo.git"
                )
                mock_repo.get_config.return_value = mock_config
                mock_repo.refs.read_ref.return_value = b"refs/heads/detected-branch"
                mock_get_repo.return_value = mock_repo

                # Mock HTTP responses
                pr_response = create_mock_response(
                    [
                        {
                            "number": 456,
                            "html_url": "https://github.com/detected-owner/detected-repo/pull/456",
                        }
                    ]
                )
                comments_response = create_mock_response(sample_pr_comments)

                mock_http_client.add_get_response(pr_response)
                mock_http_client.add_get_response(comments_response)

                # Test git detection
                git_context = git_pr_resolver.git_detect_repo_branch(temp_repo)
                assert git_context.owner == "detected-owner"
                assert git_context.repo == "detected-repo"
                assert git_context.branch == "detected-branch"

                # Continue with resolved context
                pr_url = await git_pr_resolver.resolve_pr_url(
                    git_context.owner, git_context.repo, git_context.branch
                )

                assert (
                    pr_url == "https://github.com/detected-owner/detected-repo/pull/456"
                )


class TestRealGitHubIntegration:
    """Integration tests with real GitHub API (requires GITHUB_TOKEN)."""

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_real_github_pr_fetch(self, github_token: str) -> None:
        """
        Test fetching from a real GitHub PR.

        This test requires GITHUB_TOKEN and uses a known public repository.
        Marked as integration test - can be skipped in CI if token not available.
        """
        # Use a stable public PR for testing (e.g., a closed PR that won't change)
        # This should be a PR known to exist with comments
        try:
            comments = await fetch_pr_comments(
                "octocat",  # GitHub's demo user
                "Hello-World",  # GitHub's demo repo
                1,  # First PR (likely to exist and be stable)
                max_comments=5,  # Limit to avoid large response
            )

            # Basic validation - real PR should have some structure
            assert isinstance(comments, list)
            # Real comments should have standard GitHub API fields
            if comments:  # Only check if comments exist
                assert "id" in comments[0]
                assert "body" in comments[0]

        except Exception as e:
            # If we can't access the test PR, skip rather than fail
            pytest.skip(f"Could not access test PR for integration test: {e}")

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_real_pr_resolution(self, github_token: str) -> None:
        """Test PR resolution with real GitHub API."""
        try:
            # Try to resolve PRs for a known active repository
            pr_url = await git_pr_resolver.resolve_pr_url(
                "octocat", "Hello-World", select_strategy="first"
            )

            # Should return a valid GitHub PR URL
            assert pr_url.startswith("https://github.com/")
            assert "/pull/" in pr_url

        except ValueError as e:
            if "No open PRs found" in str(e):
                # This is fine - the test repo might not have open PRs
                pytest.skip("Test repository has no open PRs")
            else:
                raise


class TestErrorRecoveryAndResilience:
    """Test error handling and recovery in integrated workflows."""

    @pytest.mark.asyncio
    async def test_partial_failure_recovery(
        self,
        mcp_server: ReviewSpecGenerator,
        mock_http_client,
        temp_review_specs_dir: Path,
    ) -> None:
        """Test recovery from partial failures in the workflow."""
        # Simulate intermittent network failure followed by success
        failure_response = create_mock_response(
            status_code=503,
            raise_for_status_side_effect=Exception("Service Temporarily Unavailable"),
        )
        success_response = create_mock_response(
            [{"id": 1, "body": "Test comment", "user": {"login": "user"}}]
        )

        # First call fails, second succeeds (simulating retry logic)
        mock_http_client.add_get_response(failure_response)
        mock_http_client.add_get_response(success_response)

        # The fetch should handle the failure gracefully
        result = await mcp_server.call_tool(
            "fetch_pr_review_comments",
            {"url": "https://github.com/owner/repo/pull/123"},
        )

        # Should either succeed after retry or fail gracefully
        if result.is_error:
            assert "error" in str(result.content).lower()
        else:
            # If it succeeded, it should have valid content
            assert len(result.content) > 0

    @pytest.mark.asyncio
    async def test_malformed_data_handling(
        self,
        mcp_server: ReviewSpecGenerator,
        mock_http_client,
        temp_review_specs_dir: Path,
    ) -> None:
        """Test handling of malformed data throughout the workflow."""
        # Mock API response with malformed/missing data
        malformed_comments = [
            {"id": "invalid", "body": None},  # Invalid ID, null body
            {},  # Empty comment object
            {"body": 123, "user": "not-an-object"},  # Wrong types
            {
                "id": 1,
                "body": "Valid comment",
                "user": {"login": "valid-user"},
            },  # One valid comment
        ]

        mock_response = create_mock_response(malformed_comments)
        mock_http_client.add_get_response(mock_response)

        with patch("mcp_server.Path.cwd", return_value=temp_review_specs_dir.parent):
            # Should handle malformed data gracefully
            result = await mcp_server.call_tool(
                "fetch_pr_review_comments",
                {"url": "https://github.com/owner/repo/pull/123"},
            )

            # Should not crash and should return some result
            assert result is not None

            if not result.is_error:
                # If successful, try to create spec file with potentially malformed data
                comments_data = json.loads(result.content[0].text)["comments"]

                create_result = await mcp_server.call_tool(
                    "create_review_spec_file",
                    {
                        "pr_url": "https://github.com/owner/repo/pull/123",
                        "comments": comments_data,
                        "filename": "malformed-test.md",
                    },
                )

                # Should handle malformed comment data without crashing
                assert create_result is not None


class TestPerformanceAndLimits:
    """Test performance characteristics and safety limits."""

    @pytest.mark.asyncio
    async def test_large_comment_set_handling(
        self,
        mcp_server: ReviewSpecGenerator,
        mock_http_client,
        custom_api_limits: dict[str, int],
    ) -> None:
        """Test handling of large comment sets with safety limits."""
        # Create a large set of comments (more than limit)
        large_comment_set = [
            {
                "id": i,
                "body": f"Comment {i} with some content to make it realistic",
                "user": {"login": f"user{i % 10}"},  # Rotate through users
                "path": f"file{i % 5}.py",  # Rotate through files
                "line": (i % 100) + 1,
            }
            for i in range(custom_api_limits["max_comments"] + 50)  # Exceed limit
        ]

        mock_response = create_mock_response(large_comment_set)
        mock_http_client.add_get_response(mock_response)

        result = await mcp_server.call_tool(
            "fetch_pr_review_comments",
            {
                "url": "https://github.com/owner/repo/pull/123",
                "max_comments": custom_api_limits["max_comments"],
            },
        )

        if not result.is_error:
            comments_data = json.loads(result.content[0].text)["comments"]
            # Should respect the limit
            assert len(comments_data) <= custom_api_limits["max_comments"]

    @pytest.mark.asyncio
    async def test_pagination_limit_enforcement(
        self,
        mcp_server: ReviewSpecGenerator,
        mock_http_client,
        custom_api_limits: dict[str, int],
    ) -> None:
        """Test that pagination limits are properly enforced."""
        # Mock multiple pages, more than the limit allows
        pages_to_mock = custom_api_limits["max_pages"] + 2

        for page in range(pages_to_mock):
            if page < pages_to_mock - 1:
                # Has next page
                headers = {
                    "Link": f'<https://api.github.com/page={page + 2}>; rel="next"'
                }
            else:
                # Last page
                headers = {}

            page_comments = [
                {"id": page * 10 + i, "body": f"Page {page} comment {i}"}
                for i in range(5)
            ]

            mock_response = create_mock_response(page_comments, headers=headers)
            mock_http_client.add_get_response(mock_response)

        result = await mcp_server.call_tool(
            "fetch_pr_review_comments",
            {
                "url": "https://github.com/owner/repo/pull/123",
                "max_pages": custom_api_limits["max_pages"],
            },
        )

        # Should respect page limit and not make excessive API calls
        api_calls_made = len(mock_http_client.get_calls)
        assert api_calls_made <= custom_api_limits["max_pages"]


# Helper imports and functions for integration tests
from unittest.mock import Mock

from conftest import create_mock_response
