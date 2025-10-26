"""Tests for the Pydantic BaseSettings implementation."""

import math

import pytest
from pydantic import SecretStr, ValidationError

from mcp_github_pr_review.config import ServerSettings, get_settings


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

    def test_token_accepts_secret_str_input(self) -> None:
        settings = ServerSettings(github_token=SecretStr("token123"))  # noqa: S106
        assert settings.github_token.get_secret_value() == "token123"

    def test_missing_token_raises_validation_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Ensure no token in environment
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with pytest.raises(ValidationError, match="Field required"):
            ServerSettings(_env_file=None)

    def test_none_token_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError, match="GITHUB_TOKEN is required"):
            ServerSettings(github_token=None)  # type: ignore[arg-type]

    def test_non_string_token_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError, match="GITHUB_TOKEN must be a string"):
            ServerSettings(github_token=12345)  # type: ignore[arg-type]

    def test_whitespace_only_token_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError, match="cannot be whitespace-only"):
            ServerSettings(github_token="   ")  # noqa: S106


class TestUrlValidation:
    """GitHub API URL fields should validate HTTPS and structure."""

    def test_valid_https_urls_are_accepted(self) -> None:
        settings = make_settings(
            github_api_url="https://api.github.example.com",
            github_graphql_url="https://graphql.github.example.com",
        )
        assert settings.github_api_url == "https://api.github.example.com"
        assert settings.github_graphql_url == "https://graphql.github.example.com"

    def test_none_and_empty_urls_are_accepted(self) -> None:
        settings = make_settings(github_api_url=None, github_graphql_url="")
        assert settings.github_api_url is None
        assert settings.github_graphql_url is None

    def test_http_url_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="HTTP URLs are not allowed"):
            make_settings(github_api_url="http://api.example.com")

    def test_non_string_url_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="URL must be a string"):
            make_settings(github_api_url=12345)  # type: ignore[arg-type]

    def test_url_with_spaces_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="URL contains spaces"):
            make_settings(github_api_url="https://api.exam ple.com")

    def test_url_with_invalid_scheme_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Invalid URL scheme"):
            make_settings(github_api_url="ftp://api.example.com")

    def test_url_without_scheme_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="URL is missing scheme"):
            make_settings(github_api_url="api.example.com")

    def test_url_without_hostname_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="URL is missing hostname"):
            make_settings(github_api_url="https://")

    def test_url_with_only_whitespace_path_is_rejected(self) -> None:
        # Whitespace-only hostname caught by spaces check first
        with pytest.raises(ValidationError, match="URL contains spaces"):
            make_settings(github_api_url="https://   ")


class TestNumericClampingEdgeCases:
    """Test edge cases in numeric clamping validators."""

    def test_invalid_string_for_int_field_uses_default(self) -> None:
        settings = make_settings(http_per_page="not_a_number")  # type: ignore[arg-type]
        assert settings.http_per_page == 100  # default value

    def test_invalid_string_for_float_field_uses_default(self) -> None:
        settings = make_settings(http_timeout="not_a_number")  # type: ignore[arg-type]
        assert settings.http_timeout == pytest.approx(30.0)  # default value

    def test_none_for_int_field_uses_default(self) -> None:
        # This simulates environment variable being unset
        settings = make_settings(http_per_page=None)  # type: ignore[arg-type]
        assert settings.http_per_page == 100

    def test_none_for_float_field_uses_default(self) -> None:
        settings = make_settings(http_timeout=None)  # type: ignore[arg-type]
        assert settings.http_timeout == pytest.approx(30.0)


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


def test_get_settings_returns_cached_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that get_settings() returns a singleton."""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token-123")
    # Clear the LRU cache to ensure clean state
    get_settings.cache_clear()

    # First call creates the instance
    settings1 = get_settings()
    # Second call should return the same cached instance
    settings2 = get_settings()

    assert settings1 is settings2
    assert settings1.github_token.get_secret_value() == "test-token-123"


def test_frozen_settings_cannot_be_modified() -> None:
    """Verify that settings are immutable after creation."""
    settings = make_settings()

    with pytest.raises(ValidationError, match="Instance is frozen"):
        settings.http_per_page = 50  # type: ignore[misc]


class TestConstraintHelpers:
    """Test the internal constraint helper functions."""

    def test_field_without_constraints_returns_defaults(self) -> None:
        """Test that fields without ge/le constraints use defaults correctly."""
        # gh_host has no numeric constraints, test the default path
        settings = make_settings(gh_host="custom.github.com")
        assert settings.gh_host == "custom.github.com"


class TestUrlParsingFailures:
    """Test URL parsing error handling."""

    def test_malformed_url_with_parsing_exception(self) -> None:
        """Test that URL parsing exceptions are handled properly."""
        # URLs with special characters that might cause urlparse to fail
        # Most invalid URLs are caught by earlier checks, but test recovery
        with pytest.raises(ValidationError):
            # This tests the general URL validation flow
            make_settings(github_api_url="not-a-url")
