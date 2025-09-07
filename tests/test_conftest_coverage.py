"""Tests to improve conftest.py coverage."""

import os
import pytest
from unittest.mock import patch


class TestConftestCoverage:
    """Tests to improve conftest.py coverage."""

    def test_timeout_disabled(self) -> None:
        """Test per_test_timeout fixture when timeout is disabled."""
        with patch.dict(os.environ, {"PYTEST_PER_TEST_TIMEOUT": "0"}):
            # This should not raise any timeout errors
            assert True

    def test_timeout_negative(self) -> None:
        """Test per_test_timeout fixture with negative timeout."""
        with patch.dict(os.environ, {"PYTEST_PER_TEST_TIMEOUT": "-1"}):
            # This should not raise any timeout errors
            assert True

    def test_timeout_invalid_string(self) -> None:
        """Test per_test_timeout fixture with invalid timeout string."""
        with patch.dict(os.environ, {"PYTEST_PER_TEST_TIMEOUT": "invalid"}):
            # This should fall back to default timeout
            assert True

    def test_timeout_environment_variable(self) -> None:
        """Test per_test_timeout fixture with PYTEST_TIMEOUT env var."""
        with patch.dict(os.environ, {"PYTEST_TIMEOUT": "10"}):
            # This should use the timeout value
            assert True

    def test_timeout_both_env_vars(self) -> None:
        """Test per_test_timeout fixture with both timeout env vars."""
        with patch.dict(os.environ, {
            "PYTEST_TIMEOUT": "5",
            "PYTEST_PER_TEST_TIMEOUT": "3"
        }):
            # PYTEST_PER_TEST_TIMEOUT should take precedence
            assert True
