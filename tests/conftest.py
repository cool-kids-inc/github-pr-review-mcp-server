"""
Shared test configuration and fixtures for the MCP GitHub PR Review Spec Maker.

This module provides:
- Common fixtures for testing HTTP clients, git contexts, and file operations
- Async mock utilities with proper cleanup
- Test data generators for various scenarios
- Configuration for test timeouts and environment setup
"""

import faulthandler
import os
import signal
import sys
import tempfile
import threading
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

# Enable faulthandler for debugging hanging tests
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
    except ValueError:
        return 5


@pytest.fixture(autouse=True)
def per_test_timeout(request: pytest.FixtureRequest) -> Generator[None, None, None]:
    """
    Enforce a per-test timeout without external plugins.

    Uses SIGALRM on Unix main thread to fail fast after N seconds.
    Configure via PYTEST_PER_TEST_TIMEOUT environment variable.
    """
    timeout = _get_timeout_seconds()
    if timeout <= 0:
        yield
        return

    # Check if pytest-timeout plugin is available
    has_pytest_timeout = request.config.pluginmanager.hasplugin("timeout")

    if has_pytest_timeout:
        # Plugin handles timeout, we just provide diagnostics
        faulthandler.dump_traceback_later(timeout, repeat=False)
        try:
            yield
        finally:
            faulthandler.cancel_dump_traceback_later()
    else:
        # Manual timeout enforcement on POSIX systems
        use_alarm = hasattr(signal, "SIGALRM") and (
            threading.current_thread() is threading.main_thread()
        )
        if use_alarm:

            def _on_timeout(signum: int, frame: Any) -> None:  # noqa: ARG001
                faulthandler.dump_traceback(file=sys.stderr)
                pytest.fail(f"Test timed out after {timeout}s", pytrace=False)

            old_handler = signal.getsignal(signal.SIGALRM)
            signal.signal(signal.SIGALRM, _on_timeout)
            signal.setitimer(signal.ITIMER_REAL, float(timeout))
            try:
                yield
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0.0)
                signal.signal(signal.SIGALRM, old_handler)
        else:
            # Fallback: diagnostic only
            faulthandler.dump_traceback_later(timeout, repeat=False)
            try:
                yield
            finally:
                faulthandler.cancel_dump_traceback_later()


class MockHttpClient:
    """
    Mock HTTP client for testing httpx.AsyncClient interactions.

    Provides separate queues for GET and POST requests with proper
    async context management and request tracking.
    """

    def __init__(self) -> None:
        self._get_responses: list[Mock] = []
        self._post_responses: list[Mock] = []
        self._get_calls: list[tuple[str, dict[str, Any]]] = []
        self._post_calls: list[tuple[str, dict[str, Any]]] = []

    def add_get_response(self, response: Mock) -> None:
        """Queue a mock response for the next GET request."""
        self._get_responses.append(response)

    def add_post_response(self, response: Mock) -> None:
        """Queue a mock response for the next POST request."""
        self._post_responses.append(response)

    @property
    def get_calls(self) -> list[tuple[str, dict[str, Any]]]:
        """Return all GET calls made to this client."""
        return self._get_calls.copy()

    @property
    def post_calls(self) -> list[tuple[str, dict[str, Any]]]:
        """Return all POST calls made to this client."""
        return self._post_calls.copy()

    async def get(self, url: str, **kwargs: Any) -> Mock:
        """Mock HTTP GET request."""
        self._get_calls.append((url, kwargs))
        if self._get_responses:
            return self._get_responses.pop(0)

        # Default successful response
        response = create_mock_response([])
        return response

    async def post(self, url: str, **kwargs: Any) -> Mock:
        """Mock HTTP POST request."""
        self._post_calls.append((url, kwargs))
        if self._post_responses:
            return self._post_responses.pop(0)

        # Default GraphQL-style response
        response = create_mock_response(
            {"data": {"repository": {"pullRequests": {"nodes": []}}}}
        )
        return response

    async def __aenter__(self) -> "MockHttpClient":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass


def create_mock_response(
    json_data: Any = None,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
    raise_for_status_side_effect: Exception | None = None,
) -> Mock:
    """
    Create a properly configured mock HTTP response.

    Args:
        json_data: Data to return from response.json()
        status_code: HTTP status code
        headers: HTTP headers dictionary
        raise_for_status_side_effect: Exception to raise from raise_for_status()

    Returns:
        Mock response object with all necessary attributes configured
    """
    response = Mock()
    response.json.return_value = [] if json_data is None else json_data
    response.status_code = status_code
    response.headers = headers or {}

    if raise_for_status_side_effect:
        response.raise_for_status.side_effect = raise_for_status_side_effect
    else:
        response.raise_for_status.return_value = None

    return response


# Core Test Fixtures


@pytest.fixture
def mock_http_client() -> Generator[MockHttpClient, None, None]:
    """
    Fixture providing a mock HTTP client with request/response tracking.

    Automatically patches httpx.AsyncClient for the duration of the test.
    """
    mock_client = MockHttpClient()
    with pytest.MonkeyPatch().context() as m:
        m.setattr("httpx.AsyncClient", lambda *args, **kwargs: mock_client)
        yield mock_client


@pytest.fixture
def github_token() -> Generator[str, None, None]:
    """Fixture that provides a mock GitHub token via environment variable."""
    with pytest.MonkeyPatch().context() as m:
        token = "test-token-12345"  # noqa: S105
        m.setenv("GITHUB_TOKEN", token)
        yield token


@pytest.fixture
def no_github_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fixture that ensures no GitHub token is set in environment."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)


@pytest.fixture
def mock_git_context() -> Generator[dict[str, str], None, None]:
    """
    Fixture providing mock git repository context.

    Sets environment variables that simulate a git repository
    for testing git-related functionality.
    """
    with pytest.MonkeyPatch().context() as m:
        context = {
            "owner": "test-owner",
            "repo": "test-repo",
            "branch": "test-branch",
            "host": "github.com",
        }
        m.setenv("MCP_PR_OWNER", context["owner"])
        m.setenv("MCP_PR_REPO", context["repo"])
        m.setenv("MCP_PR_BRANCH", context["branch"])
        m.setenv("GH_HOST", context["host"])
        yield context


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Fixture providing a temporary directory for test file operations."""
    with tempfile.TemporaryDirectory() as temp_path:
        yield Path(temp_path)


@pytest.fixture
def temp_review_specs_dir(temp_dir: Path) -> Path:
    """Fixture providing a temporary review_specs directory."""
    specs_dir = temp_dir / "review_specs"
    specs_dir.mkdir(parents=True, exist_ok=True)
    return specs_dir


@pytest.fixture
def mcp_server():
    """Fixture providing a ReviewSpecGenerator instance for testing."""
    from mcp_server import ReviewSpecGenerator

    return ReviewSpecGenerator()


# Test Data Fixtures


@pytest.fixture
def sample_pr_comments() -> list[dict[str, Any]]:
    """
    Comprehensive sample PR comment data for testing.

    Includes comments with various combinations of fields to test
    different code paths and edge cases.
    """
    return [
        {
            "id": 1,
            "body": "This is a detailed review comment with suggestions",
            "path": "src/main.py",
            "line": 42,
            "user": {"login": "reviewer1"},
            "diff_hunk": "@@ -40,3 +40,3 @@\n def function():\n-    old_code\n+    new_code\n     return result",  # noqa: E501
        },
        {
            "id": 2,
            "body": "Comment without diff hunk but with line number",
            "path": "tests/test_module.py",
            "line": 15,
            "user": {"login": "reviewer2"},
        },
        {
            "id": 3,
            "body": "General comment without specific line reference",
            "path": "docs/README.md",
            "user": {"login": "reviewer3"},
        },
        {
            "id": 4,
            "body": "Comment with ```code blocks``` and `inline code`",
            "path": "config/settings.py",
            "line": 8,
            "user": {"login": "reviewer1"},
        },
    ]


@pytest.fixture
def minimal_pr_comments() -> list[dict[str, Any]]:
    """
    Minimal comment data for testing edge cases and fallback behavior.

    Tests handling of missing optional fields and edge cases.
    """
    return [
        {
            "id": 1,
            "body": "Comment with only required fields",
            # Missing path, line, user, diff_hunk
        },
        {
            "id": 2,
            "body": None,  # None body to test null handling
            "path": "test.py",
            "line": 10,
            "user": {"login": "testuser"},
        },
        {
            "id": 3,
            "body": "",  # Empty string body
            "path": "test.py",
            "line": 20,
            "user": {},  # Empty user object
        },
    ]


@pytest.fixture
def edge_case_pr_comments() -> list[dict[str, Any]]:
    """
    Edge case comment data for comprehensive testing.

    Includes special characters, unicode, and unusual content patterns.
    """
    return [
        {
            "id": 1,
            "body": "Comment with many ```````backticks (7 total)",
            "path": "test.py",
            "line": 10,
            "user": {"login": "testuser"},
        },
        {
            "id": 2,
            "body": "Comment with special chars: @#$%^&*()",
            "path": "special/file-with-dashes.py",
            "line": 20,
            "user": {"login": "user-with-dashes"},
        },
        {
            "id": 3,
            "body": "Comment with unicode: 🚀✨🎉 and émojis",
            "path": "unicode/test_file.py",
            "line": 30,
            "user": {"login": "user_with_underscores"},
        },
    ]


# Environment Configuration Fixtures


@pytest.fixture
def debug_logging_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enable debug logging for tests that need to verify logging behavior."""
    monkeypatch.setenv("DEBUG_GITHUB_PR_RESOLVER", "1")


@pytest.fixture
def custom_api_limits(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Set custom API limits for testing boundary conditions."""
    limits = {"max_pages": 10, "max_comments": 100, "per_page": 25, "max_retries": 2}
    monkeypatch.setenv("PR_FETCH_MAX_PAGES", str(limits["max_pages"]))
    monkeypatch.setenv("PR_FETCH_MAX_COMMENTS", str(limits["max_comments"]))
    monkeypatch.setenv("HTTP_PER_PAGE", str(limits["per_page"]))
    monkeypatch.setenv("HTTP_MAX_RETRIES", str(limits["max_retries"]))
    return limits


# Compatibility mocks for legacy tests


class DummyResp:
    """Mock HTTP response object for testing (legacy compatibility)."""

    def __init__(self, json_data: Any, status_code: int = 200) -> None:
        self._json = json_data
        self.status_code = status_code
        self.headers: dict[str, str] = {}

    def json(self) -> Any:
        return self._json

    def raise_for_status(self) -> None:
        import httpx

        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=None)


class FakeClient:
    """Mock HTTP client for testing API interactions (legacy compatibility)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        assert kwargs.get("follow_redirects", False) is True

    async def __aenter__(self) -> "FakeClient":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None

    async def get(self, url: str, headers: dict[str, str] | None = None) -> DummyResp:  # noqa: ARG002
        return DummyResp(
            [
                {
                    "number": 456,
                    "html_url": "https://github.com/owner/repo/pull/456",
                }
            ]
        )
