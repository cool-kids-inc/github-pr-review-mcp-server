"""Tests for GraphQL API timeout configuration."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_github_pr_review.server import fetch_pr_comments_graphql


@pytest.mark.asyncio
async def test_graphql_uses_custom_timeout_from_env(
    monkeypatch: pytest.MonkeyPatch, github_token: str
) -> None:
    """Should use custom timeout values from environment variables."""
    monkeypatch.setenv("HTTP_TIMEOUT", "60.0")
    monkeypatch.setenv("HTTP_CONNECT_TIMEOUT", "20.0")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [],
                    }
                }
            }
        }
    }
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        result = await fetch_pr_comments_graphql("owner", "repo", 123)

        assert result is not None
        # Verify AsyncClient was called with custom timeout
        mock_client_class.assert_called_once()
        call_kwargs = mock_client_class.call_args[1]
        assert "timeout" in call_kwargs
        timeout = call_kwargs["timeout"]
        assert timeout.read == 60.0
        assert timeout.connect == 20.0


@pytest.mark.asyncio
async def test_graphql_uses_default_timeout_when_env_not_set(
    monkeypatch: pytest.MonkeyPatch, github_token: str
) -> None:
    """Should use default timeout values when env vars not set."""
    monkeypatch.delenv("HTTP_TIMEOUT", raising=False)
    monkeypatch.delenv("HTTP_CONNECT_TIMEOUT", raising=False)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [],
                    }
                }
            }
        }
    }
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        result = await fetch_pr_comments_graphql("owner", "repo", 123)

        assert result is not None
        # Verify AsyncClient was called with default timeout (30.0, 10.0)
        mock_client_class.assert_called_once()
        call_kwargs = mock_client_class.call_args[1]
        assert "timeout" in call_kwargs
        timeout = call_kwargs["timeout"]
        assert timeout.read == 30.0
        assert timeout.connect == 10.0


@pytest.mark.asyncio
async def test_graphql_clamps_timeout_to_min(
    monkeypatch: pytest.MonkeyPatch, github_token: str
) -> None:
    """Should clamp timeout values to minimum allowed."""
    monkeypatch.setenv("HTTP_TIMEOUT", "0.5")  # Below minimum of 1.0
    monkeypatch.setenv("HTTP_CONNECT_TIMEOUT", "0.5")  # Below minimum of 1.0

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [],
                    }
                }
            }
        }
    }
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        result = await fetch_pr_comments_graphql("owner", "repo", 123)

        assert result is not None
        # Verify AsyncClient was called with clamped timeout (minimum 1.0)
        mock_client_class.assert_called_once()
        call_kwargs = mock_client_class.call_args[1]
        assert "timeout" in call_kwargs
        timeout = call_kwargs["timeout"]
        assert timeout.read == 1.0
        assert timeout.connect == 1.0


@pytest.mark.asyncio
async def test_graphql_clamps_timeout_to_max(
    monkeypatch: pytest.MonkeyPatch, github_token: str
) -> None:
    """Should clamp timeout values to maximum allowed."""
    monkeypatch.setenv("HTTP_TIMEOUT", "500.0")  # Above maximum of 300.0
    monkeypatch.setenv("HTTP_CONNECT_TIMEOUT", "100.0")  # Above maximum of 60.0

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [],
                    }
                }
            }
        }
    }
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        result = await fetch_pr_comments_graphql("owner", "repo", 123)

        assert result is not None
        # Verify AsyncClient was called with clamped timeout (maximum 300.0, 60.0)
        mock_client_class.assert_called_once()
        call_kwargs = mock_client_class.call_args[1]
        assert "timeout" in call_kwargs
        timeout = call_kwargs["timeout"]
        assert timeout.read == 300.0
        assert timeout.connect == 60.0


@pytest.mark.asyncio
async def test_graphql_invalid_timeout_uses_default(
    monkeypatch: pytest.MonkeyPatch, github_token: str
) -> None:
    """Should use default timeout when env vars contain invalid values."""
    monkeypatch.setenv("HTTP_TIMEOUT", "not_a_number")
    monkeypatch.setenv("HTTP_CONNECT_TIMEOUT", "invalid")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [],
                    }
                }
            }
        }
    }
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        result = await fetch_pr_comments_graphql("owner", "repo", 123)

        assert result is not None
        # Verify AsyncClient was called with default timeout
        mock_client_class.assert_called_once()
        call_kwargs = mock_client_class.call_args[1]
        assert "timeout" in call_kwargs
        timeout = call_kwargs["timeout"]
        assert timeout.read == 30.0
        assert timeout.connect == 10.0
