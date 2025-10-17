"""Tests for configuration helper edge cases."""

import pytest

from mcp_github_pr_review.server import _int_conf


def test_int_conf_override_with_invalid_type() -> None:
    """Should return default when override cannot be converted to int."""

    # Pass an object that will raise exception when converted to int
    class BadOverride:
        def __int__(self):
            raise ValueError("Cannot convert")

    result = _int_conf("TEST_VAR", 50, 0, 100, BadOverride())  # type: ignore[arg-type]
    assert result == 50  # Should return default


def test_int_conf_override_with_none_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Should handle environment variables gracefully."""
    # Set env var to something that raises when converted
    monkeypatch.setenv("TEST_VAR", "not_a_number")
    result = _int_conf("TEST_VAR", 50, 0, 100, None)
    assert result == 50  # Should return default due to conversion error
