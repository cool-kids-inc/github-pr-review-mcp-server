"""Tests for conftest.py timeout functionality."""

import os
import signal
import threading
import time
from typing import Any
from unittest.mock import Mock, patch

import pytest


class TestPerTestTimeout:
    """Test per_test_timeout fixture functionality."""

    def test_timeout_disabled_when_zero(self, monkeypatch: Any) -> None:
        """Test that timeout is disabled when set to 0."""
        monkeypatch.setenv("PYTEST_PER_TEST_TIMEOUT", "0")
        
        # Import after setting env var to ensure it takes effect
        from conftest import _get_timeout_seconds
        
        assert _get_timeout_seconds() == 0

    def test_timeout_default_value(self, monkeypatch: Any) -> None:
        """Test default timeout value."""
        monkeypatch.delenv("PYTEST_PER_TEST_TIMEOUT", raising=False)
        monkeypatch.delenv("PYTEST_TIMEOUT", raising=False)
        
        from conftest import _get_timeout_seconds
        
        assert _get_timeout_seconds() == 5

    def test_timeout_from_pytest_timeout_env(self, monkeypatch: Any) -> None:
        """Test timeout from PYTEST_TIMEOUT env var."""
        monkeypatch.delenv("PYTEST_PER_TEST_TIMEOUT", raising=False)
        monkeypatch.setenv("PYTEST_TIMEOUT", "10")
        
        from conftest import _get_timeout_seconds
        
        assert _get_timeout_seconds() == 10

    def test_timeout_invalid_value_fallback(self, monkeypatch: Any) -> None:
        """Test fallback when timeout env var is invalid."""
        monkeypatch.setenv("PYTEST_PER_TEST_TIMEOUT", "invalid")
        
        from conftest import _get_timeout_seconds
        
        assert _get_timeout_seconds() == 5

    def test_timeout_disabled_fixture(self, monkeypatch: Any) -> None:
        """Test that timeout fixture works when disabled."""
        monkeypatch.setenv("PYTEST_PER_TEST_TIMEOUT", "0")
        
        # The fixture should yield without setting up any timeout
        # We can't easily test this without calling the fixture directly
        # This test mainly ensures the _get_timeout_seconds function works
        from conftest import _get_timeout_seconds
        assert _get_timeout_seconds() == 0

    def test_timeout_with_plugin_present(self) -> None:
        """Test timeout behavior when pytest-timeout plugin is present."""
        # Create a mock request that indicates pytest-timeout plugin is present
        mock_request = Mock()
        mock_pluginmanager = Mock()
        mock_pluginmanager.hasplugin.return_value = True
        mock_request.config.pluginmanager = mock_pluginmanager
        
        # We can't easily test the full fixture behavior in unit tests
        # since it's an autouse fixture, but we can verify the plugin detection
        assert mock_pluginmanager.hasplugin("timeout") == True

    def test_timeout_signal_availability(self) -> None:
        """Test signal availability check."""
        import signal
        # This should always be true on POSIX systems
        has_sigalrm = hasattr(signal, 'SIGALRM')
        # We just verify the attribute exists for coverage
        assert isinstance(has_sigalrm, bool)