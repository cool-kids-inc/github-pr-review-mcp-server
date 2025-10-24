"""Performance tests for Pydantic model validation.

These tests ensure that model validation overhead is acceptable and
doesn't significantly impact the overall performance of the MCP server.
"""

import time

from pydantic import ValidationError

from mcp_github_pr_review.models import (
    FetchPRReviewCommentsArgs,
    GitContextModel,
    GitHubUserModel,
    ReviewCommentModel,
)


class TestModelValidationPerformance:
    """Performance tests for model validation."""

    def test_validate_1000_comments_under_100ms(self) -> None:
        """Test that validating 1000 comment objects completes in <100ms."""
        # Create a sample comment dict
        sample_rest_comment = {
            "id": 123456,
            "user": {"login": "octocat"},
            "path": "src/example.py",
            "line": 42,
            "body": "This looks good!",
            "diff_hunk": "@@ -40,3 +40,3 @@",
            "is_resolved": False,
            "is_outdated": False,
            "resolved_by": None,
        }

        # Warm up the validator
        for _ in range(10):
            ReviewCommentModel.from_rest(sample_rest_comment)

        # Measure validation time for 1000 comments
        start = time.perf_counter()
        for _ in range(1000):
            ReviewCommentModel.from_rest(sample_rest_comment)
        elapsed = time.perf_counter() - start

        # Should complete in under 100ms on typical hardware
        assert elapsed < 0.1, (
            f"Validation took {elapsed * 1000:.2f}ms (expected <100ms)"
        )

    def test_validate_graphql_comments_performance(self) -> None:
        """Test GraphQL comment validation performance."""
        sample_graphql_node = {
            "id": "MDEyOklzc3VlQ29tbWVudDE=",
            "author": {"login": "octocat"},
            "path": "src/example.py",
            "line": 42,
            "body": "Nice work!",
            "diffHunk": "@@ -40,3 +40,3 @@",
            "isResolved": True,
            "isOutdated": False,
            "resolvedBy": {"login": "maintainer"},
        }

        # Warm up
        for _ in range(10):
            ReviewCommentModel.from_graphql(sample_graphql_node)

        # Measure validation time for 1000 comments
        start = time.perf_counter()
        for _ in range(1000):
            ReviewCommentModel.from_graphql(sample_graphql_node)
        elapsed = time.perf_counter() - start

        # Should complete in under 100ms
        assert elapsed < 0.1, (
            f"Validation took {elapsed * 1000:.2f}ms (expected <100ms)"
        )

    def test_tool_args_validation_performance(self) -> None:
        """Test that tool argument validation is fast."""
        sample_args = {
            "pr_url": "https://github.com/owner/repo/pull/123",
            "output": "markdown",
            "per_page": 50,
            "max_pages": 10,
            "max_comments": 1000,
            "max_retries": 3,
        }

        # Warm up
        for _ in range(10):
            FetchPRReviewCommentsArgs.model_validate(sample_args)

        # Measure validation time for 10000 validations
        start = time.perf_counter()
        for _ in range(10000):
            FetchPRReviewCommentsArgs.model_validate(sample_args)
        elapsed = time.perf_counter() - start

        # Should complete in under 100ms (10μs per validation)
        assert elapsed < 0.1, (
            f"Validation took {elapsed * 1000:.2f}ms (expected <100ms)"
        )

    def test_git_context_validation_performance(self) -> None:
        """Test git context model validation performance."""
        # Warm up
        for _ in range(10):
            GitContextModel(
                host="github.com",
                owner="octocat",
                repo="Hello-World",
                branch="main",
            )

        # Measure validation time for 10000 validations
        start = time.perf_counter()
        for _ in range(10000):
            GitContextModel(
                host="github.com",
                owner="octocat",
                repo="Hello-World",
                branch="main",
            )
        elapsed = time.perf_counter() - start

        # Should complete in under 50ms (5μs per validation)
        assert elapsed < 0.05, (
            f"Validation took {elapsed * 1000:.2f}ms (expected <50ms)"
        )

    def test_model_dump_performance(self) -> None:
        """Test that model_dump() is fast enough for typical use."""
        comment = ReviewCommentModel(
            id=123456,
            user=GitHubUserModel(login="octocat"),
            path="src/example.py",
            line=42,
            body="This looks good!",
            diff_hunk="@@ -40,3 +40,3 @@",
            is_resolved=False,
            is_outdated=False,
            resolved_by=None,
        )

        # Warm up
        for _ in range(10):
            comment.model_dump(exclude_none=True)

        # Measure dump time for 10000 operations
        start = time.perf_counter()
        for _ in range(10000):
            comment.model_dump(exclude_none=True)
        elapsed = time.perf_counter() - start

        # Should complete in under 100ms (10μs per dump)
        assert elapsed < 0.1, (
            f"model_dump took {elapsed * 1000:.2f}ms (expected <100ms)"
        )

    def test_validation_overhead_vs_mock_api_call(self) -> None:
        """Test that validation overhead is <5% compared to typical API latency."""
        # Simulate typical API latency (100-500ms)
        simulated_api_latency = 0.100  # 100ms

        # Measure validation time for a batch of 100 comments
        sample_comment = {
            "id": 123456,
            "user": {"login": "octocat"},
            "path": "src/example.py",
            "line": 42,
            "body": "This looks good!",
            "diff_hunk": "@@ -40,3 +40,3 @@",
            "is_resolved": False,
            "is_outdated": False,
        }

        # Warm up
        for _ in range(10):
            ReviewCommentModel.from_rest(sample_comment)

        # Measure validation time for 100 comments (typical page)
        start = time.perf_counter()
        for _ in range(100):
            ReviewCommentModel.from_rest(sample_comment)
        validation_time = time.perf_counter() - start

        # Calculate overhead percentage
        overhead_percentage = (validation_time / simulated_api_latency) * 100

        # Should be less than 5% of API latency
        assert overhead_percentage < 5.0, (
            f"Validation overhead is {overhead_percentage:.2f}% (expected <5%)"
        )

    def test_complex_comment_with_nested_data(self) -> None:
        """Test validation performance with complex nested data."""
        complex_comment = {
            "id": 123456,
            "user": {
                "login": "very-long-username-with-many-characters-" * 5
            },  # Long username
            "path": "src/" + "/".join(["very", "deeply"] * 20) + "/nested/file.py",
            "line": 999999,
            "body": "A" * 10000,  # Large comment body
            "diff_hunk": "@@ -1,100 +1,100 @@\n" + ("-old line\n+new line\n" * 50),
            "is_resolved": True,
            "is_outdated": False,
            "resolved_by": "another-very-long-username",
        }

        # Warm up
        for _ in range(10):
            ReviewCommentModel.from_rest(complex_comment)

        # Measure validation time for 100 complex comments
        start = time.perf_counter()
        for _ in range(100):
            ReviewCommentModel.from_rest(complex_comment)
        elapsed = time.perf_counter() - start

        # Should still complete in reasonable time (<50ms for 100 comments)
        assert elapsed < 0.05, (
            f"Validation took {elapsed * 1000:.2f}ms (expected <50ms)"
        )


class TestValidationErrorPerformance:
    """Performance tests for validation error handling."""

    def test_validation_error_handling_performance(self) -> None:
        """Test that validation errors are raised quickly."""
        invalid_args = {
            "per_page": 999,  # Out of range
            "max_pages": 999,
            "max_comments": 1,  # Too low
        }

        # Measure error handling time for 1000 validations
        error_count = 0
        start = time.perf_counter()
        for _ in range(1000):
            try:
                FetchPRReviewCommentsArgs.model_validate(invalid_args)
            except (ValidationError, ValueError):
                error_count += 1
        elapsed = time.perf_counter() - start

        assert error_count == 1000, "All validations should have failed"
        # Error handling should be fast (<50ms for 1000 errors)
        assert elapsed < 0.05, (
            f"Error handling took {elapsed * 1000:.2f}ms (expected <50ms)"
        )

    def test_boolean_rejection_performance(self) -> None:
        """Test performance of boolean rejection validator."""
        invalid_args = {
            "per_page": True,  # Boolean should be rejected
        }

        # Measure rejection time for 1000 validations
        error_count = 0
        start = time.perf_counter()
        for _ in range(1000):
            try:
                FetchPRReviewCommentsArgs.model_validate(invalid_args)
            except (ValidationError, ValueError):
                error_count += 1
        elapsed = time.perf_counter() - start

        assert error_count == 1000, "All validations should have failed"
        # Boolean rejection should be fast (<30ms for 1000 errors)
        assert elapsed < 0.03, (
            f"Boolean rejection took {elapsed * 1000:.2f}ms (expected <30ms)"
        )
