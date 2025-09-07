"""
Shared test configuration and fixtures for the MCP GitHub PR Review Spec Maker.

This module provides:
- Common fixtures for testing
- Async mock utilities
- Test data generators
- Configuration for test timeouts and environment
"""

import asyncio
import faulthandler
import os
import signal
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, AsyncGenerator, Generator
from unittest.mock import AsyncMock, Mock

import pytest


# Enable faulthandler to dump tracebacks on hard hangs
faulthandler.enable(file=sys.stderr)


def _get_timeout_seconds() -> int:
    """Get timeout configuration from environment variables."""
    try:
        return int(
            os.getenv(
                "PYTEST_PER_TEST_TIMEOUT",
                os.getenv("PYTEST_TIMEOUT", "5"),
            )
        )
    except Exception:
        return 5


@pytest.fixture(autouse=True)
def per_test_timeout(request: pytest.FixtureRequest) -> Generator[None, None, None]:
    """
    Enforce a per-test timeout without external plugins.
    
    Uses SIGALRM on Unix main thread to fail fast after N seconds.
    Falls back to faulthandler-only on platforms without SIGALRM.
    Configure via env var PYTEST_PER_TEST_TIMEOUT (seconds), default 5.
    """
    timeout = _get_timeout_seconds()
    if timeout <= 0:
        # Disabled
        yield
        return

    # If pytest-timeout plugin is present, let it enforce the fail-fast
    has_pytest_timeout = request.config.pluginmanager.hasplugin("timeout")

    if has_pytest_timeout:
        # Always provide diagnostic stack dumps if a test stalls
        faulthandler.dump_traceback_later(timeout, repeat=False)
        try:
            yield
        finally:
            faulthandler.cancel_dump_traceback_later()
    else:
        # Fallback enforcement without plugin: Use SIGALRM on POSIX main thread
        use_alarm = hasattr(signal, "SIGALRM") and (
            threading.current_thread() is threading.main_thread()
        )
        if use_alarm:

            def _on_timeout(signum: int, frame: Any) -> None:  # noqa: ARG001
                # Dump all thread stacks then fail this test
                faulthandler.dump_traceback(file=sys.stderr)
                pytest.fail(f"Test timed out after {timeout}s", pytrace=False)

            old_handler = signal.getsignal(signal.SIGALRM)
            signal.signal(signal.SIGALRM, _on_timeout)
            # Start timer
            signal.setitimer(signal.ITIMER_REAL, float(timeout))
            try:
                yield
            finally:
                # Cancel timer and restore
                signal.setitimer(signal.ITIMER_REAL, 0.0)
                signal.signal(signal.SIGALRM, old_handler)
        else:
            # Non-POSIX fallback: diagnostics only
            faulthandler.dump_traceback_later(timeout, repeat=False)
            try:
                yield
            finally:
                faulthandler.cancel_dump_traceback_later()


class AsyncMockClient:
    """
    Properly configured async mock client for httpx.AsyncClient.
    
    This class provides separate response queues for GET and POST requests
    to ensure proper sequencing of mock responses.
    """
    
    def __init__(self) -> None:
        self._get_responses: list[Mock] = []
        self._post_responses: list[Mock] = []
        self._get_calls: list[tuple[str, dict[str, Any]]] = []
        self._post_calls: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    
    def add_get_response(self, response: Mock) -> None:
        """Add a response for GET requests."""
        self._get_responses.append(response)
    
    def add_post_response(self, response: Mock) -> None:
        """Add a response for POST requests."""
        self._post_responses.append(response)
    
    async def get(self, url: str, **kwargs: Any) -> Mock:
        """Mock GET request."""
        self._get_calls.append((url, kwargs))
        if self._get_responses:
            return self._get_responses.pop(0)
        # Default response
        response = Mock()
        response.json.return_value = []
        response.raise_for_status.return_value = None
        response.status_code = 200
        response.headers = {}
        return response
    
    async def post(self, url: str, **kwargs: Any) -> Mock:
        """Mock POST request."""
        self._post_calls.append((url, kwargs))
        if self._post_responses:
            return self._post_responses.pop(0)
        # Default response
        response = Mock()
        response.json.return_value = {"data": {"repository": {"pullRequests": {"nodes": []}}}}
        response.raise_for_status.return_value = None
        response.status_code = 200
        response.headers = {}
        return response
    
    async def __aenter__(self) -> "AsyncMockClient":
        return self
    
    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass


@pytest.fixture
def mock_httpx_client() -> Generator[AsyncMockClient, None, None]:
    """
    Fixture that patches httpx.AsyncClient with our mock.
    
    This fixture provides a properly configured async mock client that can
    be used to test HTTP interactions without making real network requests.
    """
    mock_client = AsyncMockClient()
    with pytest.MonkeyPatch().context() as m:
        m.setattr("httpx.AsyncClient", lambda *args, **kwargs: mock_client)
        yield mock_client


@pytest.fixture
def mock_git_context() -> Generator[dict[str, str], None, None]:
    """
    Fixture providing mock git context environment variables.
    
    Sets up environment variables that simulate a git repository context
    for testing git-related functionality.
    """
    with pytest.MonkeyPatch().context() as m:
        m.setenv("MCP_PR_OWNER", "test-owner")
        m.setenv("MCP_PR_REPO", "test-repo")
        m.setenv("MCP_PR_BRANCH", "test-branch")
        m.setenv("GH_HOST", "github.com")
        yield {
            "owner": "test-owner",
            "repo": "test-repo", 
            "branch": "test-branch",
            "host": "github.com"
        }


@pytest.fixture
def temp_review_specs_dir() -> Generator[Path, None, None]:
    """
    Fixture providing a temporary directory for review specs.
    
    Creates a temporary directory with a 'review_specs' subdirectory
    for testing file creation functionality.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        specs_dir = Path(temp_dir) / "review_specs"
        specs_dir.mkdir()
        yield specs_dir


@pytest.fixture
def sample_comments() -> list[dict[str, Any]]:
    """
    Fixture providing comprehensive sample comment data for testing.
    
    Returns a list of comment dictionaries with all common fields
    to test markdown generation and processing.
    """
    return [
        {
            "id": 1,
            "body": "This is a test comment with detailed feedback",
            "path": "src/main.py",
            "line": 42,
            "user": {"login": "testuser"},
            "diff_hunk": "@@ -1,1 +1,1 @@\n-old code\n+new code"
        },
        {
            "id": 2,
            "body": "Another comment without diff hunk",
            "path": "tests/test_file.py",
            "line": 15,
            "user": {"login": "testuser2"}
        },
        {
            "id": 3,
            "body": "Comment with ```code blocks``` in body",
            "path": "docs/README.md",
            "line": 8,
            "user": {"login": "testuser3"}
        }
    ]


@pytest.fixture
def sample_comments_minimal() -> list[dict[str, Any]]:
    """
    Fixture providing minimal comment data for testing edge cases.
    
    Returns comment data with missing optional fields to test
    fallback behavior and error handling.
    """
    return [
        {
            "id": 1,
            "body": "Comment without optional fields",
            # Missing path, line, user, diff_hunk
        },
        {
            "id": 2,
            "body": None,  # None body
            "path": "test.py",
            "line": 10,
            "user": {"login": "testuser"}
        },
        {
            "id": 3,
            "body": "",  # Empty body
            "path": "test.py",
            "line": 20,
            "user": {}
        }
    ]


@pytest.fixture
def sample_comments_edge_cases() -> list[dict[str, Any]]:
    """
    Fixture providing edge case comment data for comprehensive testing.
    
    Returns comment data with various edge cases like missing fields,
    special characters, and unusual content.
    """
    return [
        {
            "id": 1,
            "body": "Comment with many ```````backticks",  # 7 backticks
            "path": "test.py",
            "line": 10,
            "user": {"login": "testuser"}
        },
        {
            "id": 2,
            "body": "Comment with special chars: @#$%^&*()",
            "path": "test.py",
            "line": 20,
            "user": {"login": "user-with-dashes"}
        },
        {
            "id": 3,
            "body": "Comment with unicode: 🚀✨🎉",
            "path": "test.py",
            "line": 30,
            "user": {"login": "user_with_underscores"}
        }
    ]


@pytest.fixture
def mcp_server() -> Any:
    """
    Fixture providing a ReviewSpecGenerator instance for testing.
    
    Returns a properly initialized MCP server instance for testing
    server functionality and tool execution.
    """
    from mcp_server import ReviewSpecGenerator
    return ReviewSpecGenerator()


def create_mock_response(
    json_data: Any = None,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
    raise_for_status_side_effect: Exception | None = None
) -> Mock:
    """
    Helper function to create properly configured mock HTTP responses.
    
    Args:
        json_data: Data to return from response.json()
        status_code: HTTP status code
        headers: HTTP headers
        raise_for_status_side_effect: Exception to raise from raise_for_status()
    
    Returns:
        Mock response object configured with the specified parameters
    """
    response = Mock()
    response.json.return_value = json_data or []
    response.status_code = status_code
    response.headers = headers or {}
    if raise_for_status_side_effect:
        response.raise_for_status.side_effect = raise_for_status_side_effect
    else:
        response.raise_for_status.return_value = None
    return response


@pytest.fixture
def github_token_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fixture that sets up a mock GitHub token environment variable."""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token-12345")


@pytest.fixture
def no_github_token_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fixture that ensures no GitHub token is set in environment."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)


@pytest.fixture
def temp_git_repo() -> Generator[Path, None, None]:
    """
    Fixture providing a temporary directory that can be used as a git repository.
    
    Creates a temporary directory that can be used for testing git-related
    functionality without affecting the actual repository.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)
