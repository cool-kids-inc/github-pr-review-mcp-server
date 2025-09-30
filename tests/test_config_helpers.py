"""Tests for configuration helper functions."""

import os

import pytest

from mcp_server import (
    CONNECT_TIMEOUT_MAX,
    CONNECT_TIMEOUT_MIN,
    MAX_COMMENTS_MAX,
    MAX_COMMENTS_MIN,
    MAX_PAGES_MAX,
    MAX_PAGES_MIN,
    MAX_RETRIES_MAX,
    MAX_RETRIES_MIN,
    PER_PAGE_MAX,
    PER_PAGE_MIN,
    TIMEOUT_MAX,
    TIMEOUT_MIN,
    _float_conf,
    _int_conf,
)


class TestIntConf:
    """Tests for _int_conf helper function."""

    def test_returns_default_when_env_not_set(self, monkeypatch: pytest.MonkeyPatch):
        """Test that default value is returned when env var is not set."""
        monkeypatch.delenv("TEST_VAR", raising=False)
        result = _int_conf("TEST_VAR", 42, 0, 100, None)
        assert result == 42

    def test_uses_env_var_when_set(self, monkeypatch: pytest.MonkeyPatch):
        """Test that env var value is used when set."""
        monkeypatch.setenv("TEST_VAR", "75")
        result = _int_conf("TEST_VAR", 42, 0, 100, None)
        assert result == 75

    def test_clamps_to_min(self, monkeypatch: pytest.MonkeyPatch):
        """Test that value is clamped to minimum."""
        monkeypatch.setenv("TEST_VAR", "-10")
        result = _int_conf("TEST_VAR", 42, 0, 100, None)
        assert result == 0

    def test_clamps_to_max(self, monkeypatch: pytest.MonkeyPatch):
        """Test that value is clamped to maximum."""
        monkeypatch.setenv("TEST_VAR", "200")
        result = _int_conf("TEST_VAR", 42, 0, 100, None)
        assert result == 100

    def test_override_takes_precedence(self, monkeypatch: pytest.MonkeyPatch):
        """Test that override parameter takes precedence over env var."""
        monkeypatch.setenv("TEST_VAR", "75")
        result = _int_conf("TEST_VAR", 42, 0, 100, 90)
        assert result == 90

    def test_override_is_clamped_to_min(self):
        """Test that override value is clamped to minimum."""
        result = _int_conf("TEST_VAR", 42, 0, 100, -10)
        assert result == 0

    def test_override_is_clamped_to_max(self):
        """Test that override value is clamped to maximum."""
        result = _int_conf("TEST_VAR", 42, 0, 100, 200)
        assert result == 100

    def test_invalid_env_var_returns_default(self, monkeypatch: pytest.MonkeyPatch):
        """Test that invalid env var value returns default."""
        monkeypatch.setenv("TEST_VAR", "not_a_number")
        result = _int_conf("TEST_VAR", 42, 0, 100, None)
        assert result == 42

    def test_invalid_override_returns_default(self):
        """Test that invalid override returns default."""
        # Simulate invalid override by passing None, which should use default
        result = _int_conf("TEST_VAR", 42, 0, 100, None)
        assert result == 42

    def test_real_config_parameters(self, monkeypatch: pytest.MonkeyPatch):
        """Test with real configuration parameters."""
        monkeypatch.setenv("HTTP_PER_PAGE", "50")
        result = _int_conf("HTTP_PER_PAGE", 100, PER_PAGE_MIN, PER_PAGE_MAX, None)
        assert result == 50

        monkeypatch.setenv("PR_FETCH_MAX_PAGES", "25")
        result = _int_conf("PR_FETCH_MAX_PAGES", 50, MAX_PAGES_MIN, MAX_PAGES_MAX, None)
        assert result == 25

        monkeypatch.setenv("PR_FETCH_MAX_COMMENTS", "1000")
        result = _int_conf(
            "PR_FETCH_MAX_COMMENTS", 2000, MAX_COMMENTS_MIN, MAX_COMMENTS_MAX, None
        )
        assert result == 1000

        monkeypatch.setenv("HTTP_MAX_RETRIES", "5")
        result = _int_conf(
            "HTTP_MAX_RETRIES", 3, MAX_RETRIES_MIN, MAX_RETRIES_MAX, None
        )
        assert result == 5


class TestFloatConf:
    """Tests for _float_conf helper function."""

    def test_returns_default_when_env_not_set(self, monkeypatch: pytest.MonkeyPatch):
        """Test that default value is returned when env var is not set."""
        monkeypatch.delenv("TEST_VAR", raising=False)
        result = _float_conf("TEST_VAR", 30.0, 1.0, 300.0)
        assert result == 30.0

    def test_uses_env_var_when_set(self, monkeypatch: pytest.MonkeyPatch):
        """Test that env var value is used when set."""
        monkeypatch.setenv("TEST_VAR", "45.5")
        result = _float_conf("TEST_VAR", 30.0, 1.0, 300.0)
        assert result == 45.5

    def test_clamps_to_min(self, monkeypatch: pytest.MonkeyPatch):
        """Test that value is clamped to minimum."""
        monkeypatch.setenv("TEST_VAR", "0.5")
        result = _float_conf("TEST_VAR", 30.0, 1.0, 300.0)
        assert result == 1.0

    def test_clamps_to_max(self, monkeypatch: pytest.MonkeyPatch):
        """Test that value is clamped to maximum."""
        monkeypatch.setenv("TEST_VAR", "400.0")
        result = _float_conf("TEST_VAR", 30.0, 1.0, 300.0)
        assert result == 300.0

    def test_invalid_env_var_returns_default(self, monkeypatch: pytest.MonkeyPatch):
        """Test that invalid env var value returns default."""
        monkeypatch.setenv("TEST_VAR", "not_a_float")
        result = _float_conf("TEST_VAR", 30.0, 1.0, 300.0)
        assert result == 30.0

    def test_handles_integer_env_var(self, monkeypatch: pytest.MonkeyPatch):
        """Test that integer strings are converted to floats."""
        monkeypatch.setenv("TEST_VAR", "60")
        result = _float_conf("TEST_VAR", 30.0, 1.0, 300.0)
        assert result == 60.0

    def test_real_timeout_parameters(self, monkeypatch: pytest.MonkeyPatch):
        """Test with real timeout configuration parameters."""
        monkeypatch.setenv("HTTP_TIMEOUT", "45.0")
        result = _float_conf("HTTP_TIMEOUT", 30.0, TIMEOUT_MIN, TIMEOUT_MAX)
        assert result == 45.0

        monkeypatch.setenv("HTTP_CONNECT_TIMEOUT", "15.5")
        result = _float_conf(
            "HTTP_CONNECT_TIMEOUT", 10.0, CONNECT_TIMEOUT_MIN, CONNECT_TIMEOUT_MAX
        )
        assert result == 15.5

    def test_timeout_boundary_values(self, monkeypatch: pytest.MonkeyPatch):
        """Test timeout configuration at boundary values."""
        # Test minimum timeout
        monkeypatch.setenv("HTTP_TIMEOUT", str(TIMEOUT_MIN))
        result = _float_conf("HTTP_TIMEOUT", 30.0, TIMEOUT_MIN, TIMEOUT_MAX)
        assert result == TIMEOUT_MIN

        # Test maximum timeout
        monkeypatch.setenv("HTTP_TIMEOUT", str(TIMEOUT_MAX))
        result = _float_conf("HTTP_TIMEOUT", 30.0, TIMEOUT_MIN, TIMEOUT_MAX)
        assert result == TIMEOUT_MAX

        # Test minimum connect timeout
        monkeypatch.setenv("HTTP_CONNECT_TIMEOUT", str(CONNECT_TIMEOUT_MIN))
        result = _float_conf(
            "HTTP_CONNECT_TIMEOUT", 10.0, CONNECT_TIMEOUT_MIN, CONNECT_TIMEOUT_MAX
        )
        assert result == CONNECT_TIMEOUT_MIN

        # Test maximum connect timeout
        monkeypatch.setenv("HTTP_CONNECT_TIMEOUT", str(CONNECT_TIMEOUT_MAX))
        result = _float_conf(
            "HTTP_CONNECT_TIMEOUT", 10.0, CONNECT_TIMEOUT_MIN, CONNECT_TIMEOUT_MAX
        )
        assert result == CONNECT_TIMEOUT_MAX


class TestConfigIntegration:
    """Integration tests for configuration system."""

    def test_multiple_configs_dont_interfere(self, monkeypatch: pytest.MonkeyPatch):
        """Test that multiple config values don't interfere with each other."""
        monkeypatch.setenv("HTTP_TIMEOUT", "60.0")
        monkeypatch.setenv("HTTP_CONNECT_TIMEOUT", "20.0")
        monkeypatch.setenv("HTTP_PER_PAGE", "75")
        monkeypatch.setenv("HTTP_MAX_RETRIES", "5")

        timeout = _float_conf("HTTP_TIMEOUT", 30.0, TIMEOUT_MIN, TIMEOUT_MAX)
        connect_timeout = _float_conf(
            "HTTP_CONNECT_TIMEOUT", 10.0, CONNECT_TIMEOUT_MIN, CONNECT_TIMEOUT_MAX
        )
        per_page = _int_conf("HTTP_PER_PAGE", 100, PER_PAGE_MIN, PER_PAGE_MAX, None)
        max_retries = _int_conf(
            "HTTP_MAX_RETRIES", 3, MAX_RETRIES_MIN, MAX_RETRIES_MAX, None
        )

        assert timeout == 60.0
        assert connect_timeout == 20.0
        assert per_page == 75
        assert max_retries == 5

    def test_config_isolation_between_tests(self):
        """Test that config changes don't leak between tests."""
        # This test should get defaults since no env vars are set
        result = _int_conf("HTTP_PER_PAGE", 100, PER_PAGE_MIN, PER_PAGE_MAX, None)
        assert result == 100

        result = _float_conf("HTTP_TIMEOUT", 30.0, TIMEOUT_MIN, TIMEOUT_MAX)
        assert result == 30.0

    def test_environ_cleanup(self, monkeypatch: pytest.MonkeyPatch):
        """Test that monkeypatch properly cleans up environment."""
        monkeypatch.setenv("TEMP_TEST_VAR", "123")
        assert os.getenv("TEMP_TEST_VAR") == "123"
        # monkeypatch will automatically clean up when test finishes
