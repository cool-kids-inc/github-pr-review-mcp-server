"""Tests for resolved and outdated status display functionality."""

from mcp_github_pr_review_spec_maker.server import generate_markdown


def test_generate_markdown_with_resolved_status() -> None:
    """Should display resolved status with resolver name."""
    comments = [
        {
            "user": {"login": "testuser"},
            "path": "test.py",
            "line": 10,
            "body": "Test comment",
            "diff_hunk": "@@ test @@",
            "is_resolved": True,
            "is_outdated": False,
            "resolved_by": "reviewer",
        }
    ]
    result = generate_markdown(comments)
    assert "**Status:** ✓ Resolved by reviewer" in result


def test_generate_markdown_with_unresolved_status() -> None:
    """Should display unresolved status."""
    comments = [
        {
            "user": {"login": "testuser"},
            "path": "test.py",
            "line": 10,
            "body": "Test comment",
            "diff_hunk": "@@ test @@",
            "is_resolved": False,
            "is_outdated": False,
            "resolved_by": None,
        }
    ]
    result = generate_markdown(comments)
    assert "**Status:** ○ Unresolved" in result


def test_generate_markdown_with_outdated_status() -> None:
    """Should display outdated status."""
    comments = [
        {
            "user": {"login": "testuser"},
            "path": "test.py",
            "line": 10,
            "body": "Test comment",
            "diff_hunk": "@@ test @@",
            "is_resolved": False,
            "is_outdated": True,
            "resolved_by": None,
        }
    ]
    result = generate_markdown(comments)
    assert "**Status:** ○ Unresolved | ⚠ Outdated" in result


def test_generate_markdown_with_resolved_and_outdated() -> None:
    """Should display both resolved and outdated status."""
    comments = [
        {
            "user": {"login": "testuser"},
            "path": "test.py",
            "line": 10,
            "body": "Test comment",
            "diff_hunk": "@@ test @@",
            "is_resolved": True,
            "is_outdated": True,
            "resolved_by": "reviewer",
        }
    ]
    result = generate_markdown(comments)
    assert "**Status:** ✓ Resolved by reviewer | ⚠ Outdated" in result


def test_generate_markdown_without_status_fields() -> None:
    """Should work with comments lacking status fields (backward compatibility)."""
    comments = [
        {
            "user": {"login": "testuser"},
            "path": "test.py",
            "line": 10,
            "body": "Test comment",
            "diff_hunk": "@@ test @@",
        }
    ]
    result = generate_markdown(comments)
    assert "**Status:**" not in result
    assert "testuser" in result


def test_generate_markdown_resolved_without_resolver() -> None:
    """Should display resolved status even without resolver name."""
    comments = [
        {
            "user": {"login": "testuser"},
            "path": "test.py",
            "line": 10,
            "body": "Test comment",
            "diff_hunk": "@@ test @@",
            "is_resolved": True,
            "is_outdated": False,
            "resolved_by": None,
        }
    ]
    result = generate_markdown(comments)
    assert "**Status:** ✓ Resolved" in result
    assert "by" not in result.split("**Status:**")[1].split("\n")[0]


def test_generate_markdown_escapes_resolved_by_name() -> None:
    """Should escape HTML in resolved_by username to prevent XSS."""
    comments = [
        {
            "user": {"login": "testuser"},
            "path": "test.py",
            "line": 10,
            "body": "Test comment",
            "diff_hunk": "@@ test @@",
            "is_resolved": True,
            "is_outdated": False,
            "resolved_by": "<script>alert('xss')</script>",
        }
    ]
    result = generate_markdown(comments)
    assert "<script>" not in result
    assert "&lt;script&gt;" in result
