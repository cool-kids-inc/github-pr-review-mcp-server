"""Tests for the Pydantic BaseSettings implementation."""

import math

import pytest

from mcp_github_pr_review.config import ServerSettings


def make_settings(**kwargs: object) -> ServerSettings:
    """Helper to build settings with defaults during tests."""

    return ServerSettings(github_token="test-token", **kwargs)  # noqa: S106


class TestNumericClamping:
    """Numeric fields should clamp to their configured bounds."""

    def test_int_fields_clamp_to_max(self) -> None:
        settings = make_settings(http_per_page=500, pr_fetch_max_pages=999)
        assert settings.http_per_page == 100
        assert settings.pr_fetch_max_pages == 200

    def test_int_fields_clamp_to_min(self) -> None:
        settings = make_settings(http_per_page=-5, pr_fetch_max_pages=0)
        assert settings.http_per_page == 1
        assert settings.pr_fetch_max_pages == 1

    def test_float_fields_clamp_out_of_range(self) -> None:
        settings = make_settings(http_timeout=999.0, http_connect_timeout=0.1)
        assert settings.http_timeout == pytest.approx(300.0)
        assert settings.http_connect_timeout == pytest.approx(1.0)

    def test_invalid_float_values_fall_back_to_default(self) -> None:
        settings = make_settings(http_timeout=math.nan, http_connect_timeout=math.inf)
        assert settings.http_timeout == pytest.approx(30.0)
        assert settings.http_connect_timeout == pytest.approx(10.0)


def test_connect_timeout_is_not_allowed_to_exceed_total_timeout() -> None:
    settings = make_settings(http_timeout=30.0, http_connect_timeout=45.0)
    assert settings.http_connect_timeout == pytest.approx(30.0)


class TestGithubToken:
    """GitHub token should be treated as a secret with sanitisation."""

    def test_token_is_trimmed_and_kept_secret(self) -> None:
        settings = ServerSettings(github_token="  abc123  ")  # noqa: S106
        assert settings.github_token.get_secret_value() == "abc123"
        dumped = settings.model_dump()
        assert "abc123" not in repr(dumped["github_token"])


def test_with_overrides_respects_clamping() -> None:
    settings = make_settings()
    updated = settings.with_overrides(
        per_page=500,
        max_pages=-1,
        max_comments=10,
        max_retries=99,
    )
    assert updated.http_per_page == 100
    assert updated.pr_fetch_max_pages == 1
    assert updated.pr_fetch_max_comments == 100
    assert updated.http_max_retries == 10
