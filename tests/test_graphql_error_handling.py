"""Tests for GraphQL API error handling and edge cases."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from mcp_server import fetch_pr_comments_graphql


@pytest.mark.asyncio
async def test_graphql_missing_token_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Should return None when GITHUB_TOKEN is not set."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    result = await fetch_pr_comments_graphql("owner", "repo", 123)
    assert result is None


@pytest.mark.asyncio
async def test_graphql_request_error_with_retry(
    monkeypatch: pytest.MonkeyPatch, github_token: str
) -> None:
    """Should retry on RequestError and succeed."""
    monkeypatch.setenv("HTTP_MAX_RETRIES", "2")

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

        # First call raises RequestError, second succeeds
        mock_client.post.side_effect = [
            httpx.RequestError("Network error"),
            mock_response,
        ]
        mock_client_class.return_value = mock_client

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await fetch_pr_comments_graphql("owner", "repo", 123)

            assert result is not None
            assert result == []
            # Should have called sleep once for the retry
            mock_sleep.assert_called_once()
            # Verify delay stays within 0.5-0.75s on the first retry
            assert 0.5 <= mock_sleep.call_args[0][0] <= 0.75


@pytest.mark.asyncio
async def test_graphql_request_error_exceeds_retries(
    monkeypatch: pytest.MonkeyPatch, github_token: str
) -> None:
    """Should raise error after exhausting retries."""
    monkeypatch.setenv("HTTP_MAX_RETRIES", "2")

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        # All calls raise RequestError
        mock_client.post.side_effect = httpx.RequestError("Network error")
        mock_client_class.return_value = mock_client

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(httpx.RequestError):
                await fetch_pr_comments_graphql("owner", "repo", 123)


@pytest.mark.asyncio
async def test_graphql_server_error_with_retry(
    monkeypatch: pytest.MonkeyPatch, github_token: str
) -> None:
    """Should retry on 5xx server errors."""
    monkeypatch.setenv("HTTP_MAX_RETRIES", "2")

    # First response is 503, second is 200
    mock_response_503 = MagicMock()
    mock_response_503.status_code = 503
    mock_response_503.raise_for_status = MagicMock()

    mock_response_200 = MagicMock()
    mock_response_200.status_code = 200
    mock_response_200.json.return_value = {
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
    mock_response_200.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.side_effect = [mock_response_503, mock_response_200]
        mock_client_class.return_value = mock_client

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await fetch_pr_comments_graphql("owner", "repo", 123)

            assert result is not None
            assert result == []
            # Should have called sleep once for the retry
            mock_sleep.assert_called_once()


@pytest.mark.asyncio
async def test_graphql_server_error_exceeds_retries(
    monkeypatch: pytest.MonkeyPatch, github_token: str
) -> None:
    """Should call raise_for_status after exhausting retries on server error."""
    monkeypatch.setenv("HTTP_MAX_RETRIES", "1")

    mock_response = MagicMock()
    mock_response.status_code = 503
    mock_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "Server error", request=MagicMock(), response=mock_response
        )
    )

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(httpx.HTTPStatusError):
                await fetch_pr_comments_graphql("owner", "repo", 123)


@pytest.mark.asyncio
async def test_graphql_client_error_no_retry(
    monkeypatch: pytest.MonkeyPatch, github_token: str
) -> None:
    """Should not retry on 4xx client errors and raise immediately."""
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "Not found", request=MagicMock(), response=mock_response
        )
    )

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        with pytest.raises(httpx.HTTPStatusError, match="Not found"):
            await fetch_pr_comments_graphql("owner", "repo", 123)

        # Should only make one request (no retries for 4xx)
        assert mock_client.post.call_count == 1


@pytest.mark.asyncio
async def test_graphql_non_200_success_breaks_after_raise_for_status(
    monkeypatch: pytest.MonkeyPatch, github_token: str
) -> None:
    """Should break after raise_for_status() for non-200 success responses."""
    mock_response = MagicMock()
    mock_response.status_code = 204
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [
                            {
                                "isResolved": True,
                                "isOutdated": False,
                                "resolvedBy": {"login": "maintainer"},
                                "comments": {
                                    "nodes": [
                                        {
                                            "author": {"login": "reviewer"},
                                            "body": "Looks good",
                                            "path": "src/module.py",
                                            "line": 42,
                                            "diffHunk": "@@ -1,1 +1,1 @@",
                                        }
                                    ]
                                },
                            }
                        ],
                    }
                }
            }
        }
    }

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        result = await fetch_pr_comments_graphql("owner", "repo", 123)

        assert result == [
            {
                "user": {"login": "reviewer"},
                "path": "src/module.py",
                "line": 42,
                "body": "Looks good",
                "diff_hunk": "@@ -1,1 +1,1 @@",
                "is_resolved": True,
                "is_outdated": False,
                "resolved_by": "maintainer",
            }
        ]
        mock_response.raise_for_status.assert_called_once()
        assert mock_client.post.call_count == 1


@pytest.mark.asyncio
async def test_graphql_errors_in_response(
    monkeypatch: pytest.MonkeyPatch, github_token: str
) -> None:
    """Should return None when GraphQL response contains errors."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "errors": [{"message": "Field 'pullRequest' doesn't exist"}]
    }
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        result = await fetch_pr_comments_graphql("owner", "repo", 123)
        assert result is None


@pytest.mark.asyncio
async def test_graphql_missing_pr_data(
    monkeypatch: pytest.MonkeyPatch, github_token: str
) -> None:
    """Should return None when PR data is missing from response."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": {
            "repository": {
                "pullRequest": None  # PR doesn't exist
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
        assert result is None


@pytest.mark.asyncio
async def test_graphql_max_comments_limit(
    monkeypatch: pytest.MonkeyPatch, github_token: str
) -> None:
    """Should stop adding comments once max_comments limit is reached."""
    # Single response with 200 comments, but limit set to 150
    # Note: min allowed max_comments is 100, so we use 150 which is within range
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [
                            {
                                "isResolved": False,
                                "isOutdated": False,
                                "resolvedBy": None,
                                "comments": {
                                    "nodes": [
                                        {
                                            "author": {"login": "user1"},
                                            "body": f"Comment {i}",
                                            "path": "file.py",
                                            "line": i,
                                            "diffHunk": "@@ -1,1 +1,1 @@",
                                        }
                                        for i in range(1, 201)  # 200 comments
                                    ]
                                },
                            }
                        ],
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

        # Set max_comments to 150 (min allowed is 100)
        # The break is checked after each comment is added, so it will add 150 comments
        result = await fetch_pr_comments_graphql("owner", "repo", 123, max_comments=150)

        assert result is not None
        assert len(result) == 150
        assert result[0]["body"] == "Comment 1"
        assert result[149]["body"] == "Comment 150"
        # Should only make one request
        assert mock_client.post.call_count == 1


@pytest.mark.asyncio
async def test_graphql_timeout_exception(
    monkeypatch: pytest.MonkeyPatch, github_token: str
) -> None:
    """Should return None on timeout exception."""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.side_effect = httpx.TimeoutException("Timeout")
        mock_client_class.return_value = mock_client

        result = await fetch_pr_comments_graphql("owner", "repo", 123)
        assert result is None


@pytest.mark.asyncio
async def test_graphql_request_error_final_propagation(
    monkeypatch: pytest.MonkeyPatch, github_token: str
) -> None:
    """Should propagate RequestError after final retry exhaustion."""
    monkeypatch.setenv("HTTP_MAX_RETRIES", "0")  # No retries

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.side_effect = httpx.RequestError("Connection refused")
        mock_client_class.return_value = mock_client

        with pytest.raises(httpx.RequestError, match="Connection refused"):
            await fetch_pr_comments_graphql("owner", "repo", 123)


@pytest.mark.asyncio
async def test_graphql_pagination_with_multiple_pages(
    monkeypatch: pytest.MonkeyPatch, github_token: str
) -> None:
    """Should paginate through multiple pages of results."""
    # First page response
    mock_response_1 = MagicMock()
    mock_response_1.status_code = 200
    mock_response_1.json.return_value = {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "pageInfo": {"hasNextPage": True, "endCursor": "cursor1"},
                        "nodes": [
                            {
                                "isResolved": False,
                                "isOutdated": False,
                                "resolvedBy": None,
                                "comments": {
                                    "nodes": [
                                        {
                                            "author": {"login": "user1"},
                                            "body": "Comment 1",
                                            "path": "file.py",
                                            "line": 1,
                                            "diffHunk": "@@ -1,1 +1,1 @@",
                                        }
                                    ]
                                },
                            }
                        ],
                    }
                }
            }
        }
    }
    mock_response_1.raise_for_status = MagicMock()

    # Second page response
    mock_response_2 = MagicMock()
    mock_response_2.status_code = 200
    mock_response_2.json.return_value = {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [
                            {
                                "isResolved": True,
                                "isOutdated": False,
                                "resolvedBy": {"login": "resolver"},
                                "comments": {
                                    "nodes": [
                                        {
                                            "author": {"login": "user2"},
                                            "body": "Comment 2",
                                            "path": "file.py",
                                            "line": 2,
                                            "diffHunk": "@@ -2,2 +2,2 @@",
                                        }
                                    ]
                                },
                            }
                        ],
                    }
                }
            }
        }
    }
    mock_response_2.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.side_effect = [mock_response_1, mock_response_2]
        mock_client_class.return_value = mock_client

        result = await fetch_pr_comments_graphql("owner", "repo", 123)

        assert result is not None
        assert len(result) == 2
        assert result[0]["body"] == "Comment 1"
        assert result[0]["is_resolved"] is False
        assert result[1]["body"] == "Comment 2"
        assert result[1]["is_resolved"] is True
        assert result[1]["resolved_by"] == "resolver"
        # Should have made two requests (one per page)
        assert mock_client.post.call_count == 2


@pytest.mark.asyncio
async def test_graphql_retry_delay_calculation(
    monkeypatch: pytest.MonkeyPatch, github_token: str
) -> None:
    """Should calculate exponential backoff delays correctly."""
    monkeypatch.setenv("HTTP_MAX_RETRIES", "3")

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

        # Fail 3 times with RequestError, then succeed
        mock_client.post.side_effect = [
            httpx.RequestError("Error 1"),
            httpx.RequestError("Error 2"),
            httpx.RequestError("Error 3"),
            mock_response,
        ]
        mock_client_class.return_value = mock_client

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await fetch_pr_comments_graphql("owner", "repo", 123)

            assert result is not None
            # Should have called sleep 3 times
            assert mock_sleep.call_count == 3

            # Verify delays are in expected ranges for exponential backoff
            delays = [call[0][0] for call in mock_sleep.call_args_list]
            # First retry: 0.5 * 2^0 + random = 0.5 to 0.75
            assert 0.5 <= delays[0] <= 0.75
            # Second retry: 0.5 * 2^1 + random = 1.0 to 1.25
            assert 1.0 <= delays[1] <= 1.25
            # Third retry: 0.5 * 2^2 + random = 2.0 to 2.25
            assert 2.0 <= delays[2] <= 2.25
