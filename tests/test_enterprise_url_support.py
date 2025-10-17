"""Tests for enterprise GitHub URL support."""

import os
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest

from mcp_github_pr_review_spec_maker.git_pr_resolver import graphql_url_for_host
from mcp_github_pr_review_spec_maker.server import fetch_pr_comments, fetch_pr_comments_graphql, get_pr_info


def create_mock_async_client(
    method: str,
    json_data: dict[str, Any] | list[Any],
    headers: dict[str, Any] | None = None,
) -> AsyncMock:
    """
    Create a mocked httpx.AsyncClient configured as an async context manager.
    
    Parameters:
        method (str): HTTP method name to mock on the client (e.g., "post", "get").
        json_data (dict | list): Value that the mocked response's `json()` call will return.
        headers (dict | None): Optional headers to attach to the mocked response.
    
    Returns:
        AsyncMock: An AsyncMock acting as an AsyncClient whose specified method returns a response
        with `status_code` 200, `json()` returning `json_data`, and `headers` set when provided.
    """
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = json_data
    if headers is not None:
        mock_response.headers = headers

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    setattr(mock_client, method, AsyncMock(return_value=mock_response))

    return mock_client


@pytest.fixture
def mock_graphql_client() -> Generator[AsyncMock, None, None]:
    """
    Provide a pytest fixture that yields an AsyncMock httpx.AsyncClient configured to simulate GraphQL POST responses.
    
    The mocked client is patched into mcp_github_pr_review_spec_maker.server.httpx.AsyncClient and acts as an asynchronous context manager. Its `post` method returns a response with status_code 200 and a `.json()` payload containing an empty `pullRequest.reviewThreads.nodes` structure.
    
    Returns:
        mock_client (AsyncMock): An AsyncMock httpx.AsyncClient whose `post` returns the prepared GraphQL JSON response.
    """
    json_data = {
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

    with patch("mcp_github_pr_review_spec_maker.server.httpx.AsyncClient") as mock_client_class:
        mock_client = create_mock_async_client("post", json_data)
        mock_client_class.return_value = mock_client
        yield mock_client


@pytest.fixture
def mock_rest_client() -> Generator[AsyncMock, None, None]:
    """
    Pytest fixture that provides a mocked httpx.AsyncClient configured for REST GET requests.
    
    Returns:
        AsyncMock: A mock AsyncClient suitable for use as an async context manager where `.get` returns a response with status_code 200 and an empty JSON body; headers can be inspected on the mocked response.
    """
    with patch("mcp_github_pr_review_spec_maker.server.httpx.AsyncClient") as mock_client_class:
        mock_client = create_mock_async_client("get", [], headers={})
        mock_client_class.return_value = mock_client
        yield mock_client


def test_graphql_url_for_host_is_public():
    """Verify graphql_url_for_host can be imported and is public."""
    # Function should be accessible (not prefixed with underscore)
    assert callable(graphql_url_for_host)
    assert not graphql_url_for_host.__name__.startswith("_")


def test_get_pr_info_returns_host_github_com():
    """Test get_pr_info extracts host from github.com URL."""
    url = "https://github.com/owner/repo/pull/123"
    host, owner, repo, num = get_pr_info(url)

    assert host == "github.com"
    assert owner == "owner"
    assert repo == "repo"
    assert num == "123"


def test_get_pr_info_returns_host_enterprise():
    """Test get_pr_info extracts host from enterprise GitHub URL."""
    url = "https://github.enterprise.com/owner/repo/pull/456"
    host, owner, repo, num = get_pr_info(url)

    assert host == "github.enterprise.com"
    assert owner == "owner"
    assert repo == "repo"
    assert num == "456"


def test_get_pr_info_enterprise_with_query_params():
    """Test get_pr_info handles enterprise URLs with query parameters."""
    url = "https://github.enterprise.com/owner/repo/pull/789?diff=split"
    host, owner, repo, num = get_pr_info(url)

    assert host == "github.enterprise.com"
    assert owner == "owner"
    assert repo == "repo"
    assert num == "789"


def test_get_pr_info_enterprise_with_fragment():
    """Test get_pr_info handles enterprise URLs with fragments."""
    url = "https://github.enterprise.com/owner/repo/pull/101#discussion"
    host, owner, repo, num = get_pr_info(url)

    assert host == "github.enterprise.com"
    assert owner == "owner"
    assert repo == "repo"
    assert num == "101"


def test_get_pr_info_enterprise_with_path():
    """Test get_pr_info handles enterprise URLs with trailing path."""
    url = "https://github.enterprise.com/owner/repo/pull/202/files"
    host, owner, repo, num = get_pr_info(url)

    assert host == "github.enterprise.com"
    assert owner == "owner"
    assert repo == "repo"
    assert num == "202"


def test_get_pr_info_invalid_url_format():
    """Test get_pr_info raises ValueError for invalid URLs."""
    with pytest.raises(ValueError, match="Invalid PR URL format"):
        get_pr_info("https://github.com/owner/repo/issues/123")

    with pytest.raises(ValueError, match="Invalid PR URL format"):
        get_pr_info("not-a-url")

    with pytest.raises(ValueError, match="Invalid PR URL format"):
        get_pr_info("https://github.com/owner")


@pytest.mark.asyncio
async def test_fetch_pr_comments_graphql_uses_enterprise_url(mock_graphql_client):
    """Test fetch_pr_comments_graphql uses enterprise URL when host is provided."""
    with patch.dict(os.environ, {"GITHUB_TOKEN": "test_token"}, clear=True):
        result = await fetch_pr_comments_graphql(
            "owner",
            "repo",
            123,
            host="github.enterprise.com",
        )

    # Verify the correct URL was called
    assert mock_graphql_client.post.called
    call_args = mock_graphql_client.post.call_args
    assert call_args[0][0] == "https://github.enterprise.com/api/graphql"
    # Verify Authorization header
    headers = call_args[1].get("headers", {})
    assert headers.get("Authorization") == "Bearer test_token"
    assert result == []


@pytest.mark.asyncio
async def test_fetch_pr_comments_graphql_default_github_com(mock_graphql_client):
    """Test fetch_pr_comments_graphql defaults to github.com."""
    with patch.dict(os.environ, {"GITHUB_TOKEN": "test_token"}, clear=True):
        result = await fetch_pr_comments_graphql("owner", "repo", 123)

    # Verify the correct URL was called (default github.com)
    assert mock_graphql_client.post.called
    call_args = mock_graphql_client.post.call_args
    assert call_args[0][0] == "https://api.github.com/graphql"
    # Verify Authorization header
    headers = call_args[1].get("headers", {})
    assert headers.get("Authorization") == "Bearer test_token"
    assert result == []


@pytest.mark.asyncio
async def test_fetch_pr_comments_rest_uses_enterprise_url(mock_rest_client):
    """Test fetch_pr_comments uses enterprise URL when host is provided."""
    with patch.dict(os.environ, {"GITHUB_TOKEN": "test_token"}, clear=True):
        result = await fetch_pr_comments(
            "owner",
            "repo",
            123,
            host="github.enterprise.com",
        )

    # Verify the correct URL was called
    assert mock_rest_client.get.called
    call_args = mock_rest_client.get.call_args
    called_url = call_args[0][0]
    assert called_url.startswith("https://github.enterprise.com/api/v3/repos/")
    assert "/owner/repo/pulls/123/comments" in called_url
    # Verify Authorization header
    headers = call_args[1].get("headers", {})
    assert headers.get("Authorization") == "Bearer test_token"
    assert result == []


@pytest.mark.asyncio
async def test_fetch_pr_comments_rest_default_github_com(mock_rest_client):
    """Test fetch_pr_comments defaults to github.com."""
    with patch.dict(os.environ, {"GITHUB_TOKEN": "test_token"}, clear=True):
        result = await fetch_pr_comments("owner", "repo", 123)

    # Verify the correct URL was called (default github.com)
    assert mock_rest_client.get.called
    call_args = mock_rest_client.get.call_args
    called_url = call_args[0][0]
    assert called_url.startswith("https://api.github.com/repos/")
    assert "/owner/repo/pulls/123/comments" in called_url
    # Verify Authorization header
    headers = call_args[1].get("headers", {})
    assert headers.get("Authorization") == "Bearer test_token"
    assert result == []


@pytest.mark.asyncio
async def test_fetch_pr_comments_graphql_respects_env_override(mock_graphql_client):
    """Test GraphQL function respects GITHUB_GRAPHQL_URL override when hosts match.

    GITHUB_GRAPHQL_URL uses api.github.com host, which is treated as
    equivalent to github.com when matching.
    """
    env = {
        "GITHUB_TOKEN": "test_token",
        "GITHUB_GRAPHQL_URL": "https://api.github.com/custom/graphql",
    }
    with patch.dict(os.environ, env, clear=False):
        result = await fetch_pr_comments_graphql(
            "owner",
            "repo",
            123,
            host="github.com",
        )

    # Verify the custom URL was used (api.github.com matches github.com)
    assert mock_graphql_client.post.called
    call_args = mock_graphql_client.post.call_args
    assert call_args[0][0] == "https://api.github.com/custom/graphql"
    assert result == []


@pytest.mark.asyncio
async def test_fetch_pr_comments_rest_respects_env_override(mock_rest_client):
    """Test fetch_pr_comments respects GITHUB_API_URL override when hosts match."""
    env = {
        "GITHUB_TOKEN": "test_token",
        "GITHUB_API_URL": "https://custom.api",
    }
    with patch.dict(os.environ, env, clear=False):
        # Use matching host so env override applies
        result = await fetch_pr_comments(
            "owner",
            "repo",
            123,
            host="custom.api",
        )

    # Verify the custom URL was used
    assert mock_rest_client.get.called
    call_args = mock_rest_client.get.call_args
    called_url = call_args[0][0]
    assert called_url.startswith("https://custom.api/repos/")
    assert "/owner/repo/pulls/123/comments" in called_url
    assert result == []


@pytest.mark.asyncio
async def test_fetch_pr_comments_rest_ignores_mismatched_env_override(mock_rest_client):
    """Test fetch_pr_comments ignores GITHUB_API_URL when host doesn't match.

    This verifies the fix for multi-host environments where GITHUB_API_URL
    might be set for a GHES instance but calls to github.com should not be
    affected.
    """
    env = {
        "GITHUB_TOKEN": "test_token",
        "GITHUB_API_URL": "https://ghe.mycorp.com/api/v3",
    }
    with patch.dict(os.environ, env, clear=False):
        # Call with github.com - should NOT use the GHES override
        result = await fetch_pr_comments(
            "owner",
            "repo",
            123,
            host="github.com",
        )

    # Verify the default github.com API was used, not the GHES override
    assert mock_rest_client.get.called
    call_args = mock_rest_client.get.call_args
    called_url = call_args[0][0]
    assert called_url.startswith("https://api.github.com/repos/")
    assert "ghe.mycorp.com" not in called_url
    assert result == []