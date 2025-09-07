"""Test utilities and fixtures for consistent testing."""

import asyncio
from typing import Any, AsyncGenerator, Generator
from unittest.mock import AsyncMock, Mock

import pytest


class AsyncMockClient:
    """Properly configured async mock client for httpx.AsyncClient."""
    
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
def mock_async_client() -> AsyncMockClient:
    """Fixture providing a properly configured async mock client."""
    return AsyncMockClient()


@pytest.fixture
def mock_httpx_client() -> Generator[AsyncMockClient, None, None]:
    """Fixture that patches httpx.AsyncClient with our mock."""
    mock_client = AsyncMockClient()
    with pytest.MonkeyPatch().context() as m:
        m.setattr("httpx.AsyncClient", lambda *args, **kwargs: mock_client)
        yield mock_client


@pytest.fixture
def mock_git_context() -> Generator[dict[str, str], None, None]:
    """Fixture providing mock git context."""
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
def temp_review_specs_dir() -> Generator[Any, None, None]:
    """Fixture providing a temporary directory for review specs."""
    import tempfile
    from pathlib import Path
    
    with tempfile.TemporaryDirectory() as temp_dir:
        specs_dir = Path(temp_dir) / "review_specs"
        specs_dir.mkdir()
        yield specs_dir


@pytest.fixture
def sample_comments() -> list[dict[str, Any]]:
    """Fixture providing sample comment data for testing."""
    return [
        {
            "id": 1,
            "body": "This is a test comment",
            "path": "test.py",
            "line": 10,
            "user": {"login": "testuser"},
            "diff_hunk": "@@ -1,1 +1,1 @@\n-old\n+new"
        },
        {
            "id": 2,
            "body": "Another comment",
            "path": "test2.py",
            "line": 20,
            "user": {"login": "testuser2"}
        }
    ]


@pytest.fixture
def sample_comments_minimal() -> list[dict[str, Any]]:
    """Fixture providing minimal comment data for testing edge cases."""
    return [
        {
            "id": 1,
            "body": "Comment without optional fields",
            # Missing path, position, line, user
        }
    ]


def create_mock_response(
    json_data: Any = None,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
    raise_for_status_side_effect: Exception | None = None
) -> Mock:
    """Helper to create properly configured mock responses."""
    response = Mock()
    response.json.return_value = json_data or []
    response.status_code = status_code
    response.headers = headers or {}
    if raise_for_status_side_effect:
        response.raise_for_status.side_effect = raise_for_status_side_effect
    else:
        response.raise_for_status.return_value = None
    return response
