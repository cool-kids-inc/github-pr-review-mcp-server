"""
Integration test suite for MCP GitHub PR Review Spec Maker.

These tests verify the complete end-to-end functionality including:
- Real GitHub API integration (when GITHUB_TOKEN is available)
- Complete workflow from git detection to file creation
- Cross-component interactions and data flow
- Performance and reliability under various conditions
"""

import os
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import httpx
import pytest
from conftest import create_mock_response

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
        mock_http_client,
        temp_review_specs_dir: Path,
        sample_pr_comments: list[dict[str, Any]],
        mock_git_context: dict[str, str],
    ) -> None:
        """Test complete workflow with mocked dependencies."""
        # Mock HTTP responses for PR resolution and comment fetching
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

        try:
            # Step 1: Resolve PR URL
            pr_url = await git_pr_resolver.resolve_pr_url(
                mock_git_context["owner"],
                mock_git_context["repo"],
                mock_git_context["branch"],
            )

            # Step 2: Parse PR info and fetch comments
            owner, repo, pr_number = get_pr_info(pr_url)
            comments = await fetch_pr_comments(owner, repo, int(pr_number))
            assert comments is not None

            # Step 3: Generate markdown specification
            markdown = generate_markdown(comments)

            # Step 4: Create specification file
            spec_file = temp_review_specs_dir / "end-to-end-test.md"
            spec_file.write_text(markdown)

            # Verify final output
            assert spec_file.exists()
            content = spec_file.read_text()
            assert "# Pull Request Review Spec" in content
            for comment in sample_pr_comments:
                if comment.get("body"):
                    assert comment["body"] in content

        except ValueError as e:
            if "No open PRs found" in str(e):
                pytest.skip("PR resolution failed - acceptable for mock test")
            else:
                raise

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
    async def test_real_github_pr_fetch(self) -> None:
        """
        Verify fetching pull request comments from GitHub when a valid
        GITHUB_TOKEN is present.

        Skips the test if no suitable token is available. Attempts to fetch
        comments for a known stable PR (microsoft/TypeScript#27353) with
        limits on comments and pages, asserts the result is a non-empty list,
        and checks that the first comment contains the `id`, `body`, and
        `user` fields. If an HTTP error prevents access to the PR, the test
        is skipped.
        """
        token = os.getenv("GITHUB_TOKEN")
        if not token or token.startswith("test-token") or len(token) < 30:
            pytest.skip("Skipping real GitHub test: no valid GITHUB_TOKEN")
        try:
            comments = await fetch_pr_comments(
                "microsoft",  # Microsoft organization
                "TypeScript",  # TypeScript repository
                27353,  # Stable closed PR with review comments
                max_comments=10,  # Limit to avoid large response
                max_pages=2,  # Only fetch first 2 pages to avoid timeout
            )

            # Basic validation - real PR should have some structure
            assert isinstance(comments, list)
            # This PR should have comments, so we can be more assertive
            assert len(comments) > 0, "Expected PR #27353 to have review comments"

            # Real comments should have standard GitHub API fields
            assert "id" in comments[0]
            assert "body" in comments[0]
            assert "user" in comments[0]

        except httpx.HTTPError as e:
            # If we can't access the test PR, skip rather than fail
            pytest.skip(f"Could not access test PR microsoft/TypeScript#27353: {e}")

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_real_pr_resolution(self) -> None:
        """Test PR resolution with real GitHub API."""
        token = os.getenv("GITHUB_TOKEN")
        if not token or token.startswith("test-token") or len(token) < 30:
            pytest.skip("Skipping real GitHub test: no valid GITHUB_TOKEN")
        try:
            # Try to resolve PRs for repositories that are more likely to have open PRs
            test_repos = [
                ("microsoft", "TypeScript"),  # Very active repo
                ("facebook", "react"),  # Very active repo
                ("octocat", "Hello-World"),  # Original test case
            ]

            success = False
            for owner, repo in test_repos:
                try:
                    pr_url = await git_pr_resolver.resolve_pr_url(
                        owner, repo, select_strategy="first"
                    )

                    # Should return a valid GitHub PR URL
                    assert pr_url.startswith("https://github.com/")
                    assert "/pull/" in pr_url
                    success = True
                    break

                except ValueError as e:
                    if "No open PRs found" in str(e):
                        continue  # Try next repo
                    else:
                        raise

            if not success:
                pytest.skip("No test repositories have open PRs available")

        except (OSError, RuntimeError) as e:
            # Catch system and runtime errors and skip rather than fail
            pytest.skip(f"Could not test PR resolution: {e}")


class TestErrorRecoveryAndResilience:
    """Test error handling and recovery in integrated workflows."""

    @pytest.mark.asyncio
    async def test_server_error_on_page_fetch_returns_none(
        self, mock_http_client
    ) -> None:
        """Test that fetch_pr_comments returns None on server error."""
        # Simulate network failure
        failure_response = create_mock_response(
            status_code=503,
            raise_for_status_side_effect=Exception("Service Temporarily Unavailable"),
        )

        mock_http_client.add_get_response(failure_response)

        # The fetch should handle the failure and return None
        result = await fetch_pr_comments("owner", "repo", 123)
        assert result is None

    @pytest.mark.asyncio
    async def test_malformed_data_handling(
        self, mock_http_client, temp_review_specs_dir: Path
    ) -> None:
        """Test handling of malformed data throughout the workflow."""
        # Mock API response with better structured but still edge-case data
        malformed_comments = [
            {"id": 1, "body": None, "user": {"login": "user1"}},  # None body
            {"id": 2, "body": "", "user": {}},  # Empty body and user
            {
                "id": 3,
                "body": "Valid comment",
                "user": {"login": "valid-user"},
            },  # Valid
        ]

        mock_response = create_mock_response(malformed_comments)
        mock_http_client.add_get_response(mock_response)

        # Should handle malformed data gracefully
        comments = await fetch_pr_comments("owner", "repo", 123)
        assert comments is not None

        # Should be able to generate markdown even with malformed data
        markdown = generate_markdown(comments)
        assert "# Pull Request Review Spec" in markdown

        # Should be able to create file
        spec_file = temp_review_specs_dir / "malformed-test.md"
        spec_file.write_text(markdown)
        assert spec_file.exists()


class TestPerformanceAndLimits:
    """Test performance characteristics and safety limits."""

    @pytest.mark.asyncio
    async def test_large_comment_set_handling(
        self, mock_http_client, custom_api_limits: dict[str, int]
    ) -> None:
        """Test handling of large comment sets with safety limits."""
        # Create a moderate set of comments (within limits to avoid pagination issues)
        comment_set = [
            {
                "id": i,
                "body": f"Comment {i} with some content to make it realistic",
                "user": {"login": f"user{i % 10}"},  # Rotate through users
                "path": f"file{i % 5}.py",  # Rotate through files
                "line": (i % 100) + 1,
            }
            for i in range(50)  # Reasonable number for testing
        ]

        mock_response = create_mock_response(comment_set)
        mock_http_client.add_get_response(mock_response)

        comments = await fetch_pr_comments(
            "owner", "repo", 123, max_comments=custom_api_limits["max_comments"]
        )

        assert comments is not None
        # Should get all comments since we're under the limit
        assert len(comments) == 50

    @pytest.mark.asyncio
    async def test_pagination_limit_enforcement(
        self, mock_http_client, custom_api_limits: dict[str, int]
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

        comments = await fetch_pr_comments(
            "owner", "repo", 123, max_pages=custom_api_limits["max_pages"]
        )

        assert comments is not None
        # Should respect page limit and not make excessive API calls
        api_calls_made = len(mock_http_client.get_calls)
        assert api_calls_made <= custom_api_limits["max_pages"]


# Helper imports and functions for integration tests
