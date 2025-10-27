"""Tests for GraphQL API error handling and edge cases."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from mcp_github_pr_review.server import fetch_pr_comments_graphql


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

        # Mock asyncio.sleep to avoid actual delays during retries
        with patch("asyncio.sleep", new_callable=AsyncMock):
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


@pytest.mark.asyncio
async def test_graphql_limit_reached_breaks_both_loops(
    monkeypatch: pytest.MonkeyPatch, github_token: str, caplog: pytest.LogCaptureFixture
) -> None:
    """
    Test that limit_reached flag properly breaks out of both thread and comment loops.

    This test verifies the fix where the limit check now sets a flag that
    breaks both the inner (comments) and outer (threads) loops, preventing
    further processing once max_comments is reached.
    """
    import logging

    caplog.set_level(logging.INFO)
    monkeypatch.setenv("HTTP_MAX_RETRIES", "0")

    # Create a response with 3 threads, each with 60 comments
    # Set max_comments to 150, which should stop mid-way through thread 3
    mock_response = MagicMock()
    mock_response.status_code = 200

    threads = []
    for thread_num in range(1, 4):  # 3 threads
        thread_comments = []
        for comment_num in range(1, 61):  # 60 comments per thread
            comment_id = (thread_num - 1) * 60 + comment_num
            hunk = f"@@ -{comment_id},{comment_id} +{comment_id},{comment_id} @@"
            thread_comments.append(
                {
                    "author": {"login": f"user{comment_id}"},
                    "body": f"Comment {comment_id}",
                    "path": "file.py",
                    "line": comment_id,
                    "diffHunk": hunk,
                }
            )

        threads.append(
            {
                "isResolved": False,
                "isOutdated": False,
                "resolvedBy": None,
                "comments": {"nodes": thread_comments},
            }
        )

    mock_response.json.return_value = {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": threads,
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

        # Set max_comments to 150 (thread 1: 60, thread 2: 60, thread 3: 30)
        result = await fetch_pr_comments_graphql("owner", "repo", 123, max_comments=150)

        assert result is not None
        assert len(result) == 150, "Should stop exactly at 150 comments"

        # Verify we got comments from threads 1 and 2, and partial from thread 3
        assert result[0]["body"] == "Comment 1"
        assert result[59]["body"] == "Comment 60"  # Last from thread 1
        assert result[60]["body"] == "Comment 61"  # First from thread 2
        assert result[119]["body"] == "Comment 120"  # Last from thread 2
        assert result[120]["body"] == "Comment 121"  # First from thread 3
        assert result[149]["body"] == "Comment 150"  # Last comment collected

        # Verify diagnostic message was printed
        # Check log records
        assert "Reached max_comments limit" in caplog.text


@pytest.mark.asyncio
async def test_graphql_limit_reached_at_thread_boundary(
    monkeypatch: pytest.MonkeyPatch, github_token: str, caplog: pytest.LogCaptureFixture
) -> None:
    """
    Test that limit is handled correctly when reached exactly at thread boundary.

    Verifies that when max_comments is reached exactly at the end of a thread,
    the next thread is not processed.
    """
    import logging

    caplog.set_level(logging.INFO)
    monkeypatch.setenv("HTTP_MAX_RETRIES", "0")

    # Create 3 threads with 50 comments each
    threads = []
    for thread_num in range(1, 4):
        thread_comments = []
        for comment_num in range(1, 51):
            comment_id = (thread_num - 1) * 50 + comment_num
            thread_comments.append(
                {
                    "author": {"login": f"user{comment_id}"},
                    "body": f"Comment {comment_id}",
                    "path": "file.py",
                    "line": comment_id,
                    "diffHunk": "@@ -1,1 +1,1 @@",
                }
            )

        threads.append(
            {
                "isResolved": False,
                "isOutdated": False,
                "resolvedBy": None,
                "comments": {"nodes": thread_comments},
            }
        )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": threads,
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

        # Set max_comments to exactly 100 (2 complete threads)
        result = await fetch_pr_comments_graphql("owner", "repo", 123, max_comments=100)

        assert result is not None
        assert len(result) == 100, "Should stop at exactly 100 comments"

        # Verify we got exactly 2 threads (100 comments)
        assert result[0]["body"] == "Comment 1"
        assert result[49]["body"] == "Comment 50"  # Last from thread 1
        assert result[50]["body"] == "Comment 51"  # First from thread 2
        assert result[99]["body"] == "Comment 100"  # Last from thread 2

        # Verify diagnostic message
        # Check log records
        assert "Reached max_comments limit" in caplog.text


@pytest.mark.asyncio
async def test_graphql_limit_reached_mid_comment_loop(
    monkeypatch: pytest.MonkeyPatch, github_token: str, caplog: pytest.LogCaptureFixture
) -> None:
    """
    Test limit check happens for each comment, stopping mid-thread if needed.

    This validates that the inner comment loop checks the limit and sets
    the flag to break out of both loops.
    """
    import logging

    caplog.set_level(logging.INFO)
    monkeypatch.setenv("HTTP_MAX_RETRIES", "0")

    # Single thread with 200 comments, limit at 125
    thread_comments = []
    for i in range(1, 201):
        thread_comments.append(
            {
                "author": {"login": f"user{i}"},
                "body": f"Comment {i}",
                "path": "file.py",
                "line": i,
                "diffHunk": f"@@ -{i},{i} +{i},{i} @@",
            }
        )

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
                                "comments": {"nodes": thread_comments},
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

        result = await fetch_pr_comments_graphql("owner", "repo", 123, max_comments=125)

        assert result is not None
        assert len(result) == 125, "Should stop at 125 comments mid-thread"
        assert result[0]["body"] == "Comment 1"
        assert result[124]["body"] == "Comment 125"

        # Check log records
        assert "Reached max_comments limit" in caplog.text


@pytest.mark.asyncio
async def test_graphql_limit_check_before_thread_processing(
    monkeypatch: pytest.MonkeyPatch, github_token: str, caplog: pytest.LogCaptureFixture
) -> None:
    """
    Test that limit is checked before processing each thread.

    Verifies the outer loop limit check that prevents processing a new thread
    when the limit has already been reached.
    """
    import logging

    caplog.set_level(logging.INFO)
    monkeypatch.setenv("HTTP_MAX_RETRIES", "0")

    # Create 5 threads with 25 comments each
    threads = []
    for thread_num in range(1, 6):
        thread_comments = []
        for comment_num in range(1, 26):
            comment_id = (thread_num - 1) * 25 + comment_num
            thread_comments.append(
                {
                    "author": {"login": f"user{comment_id}"},
                    "body": f"Thread{thread_num}-Comment{comment_num}",
                    "path": "file.py",
                    "line": comment_id,
                    "diffHunk": "@@ -1,1 +1,1 @@",
                }
            )

        threads.append(
            {
                "isResolved": thread_num % 2 == 0,
                "isOutdated": False,
                "resolvedBy": {"login": "resolver"} if thread_num % 2 == 0 else None,
                "comments": {"nodes": thread_comments},
            }
        )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": threads,
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

        # Limit to 105 comments (4 complete threads + 5 from thread 5)
        result = await fetch_pr_comments_graphql("owner", "repo", 123, max_comments=105)

        assert result is not None
        assert len(result) == 105

        # Verify we got threads 1-4 complete and partial thread 5
        assert result[0]["body"] == "Thread1-Comment1"
        assert result[24]["body"] == "Thread1-Comment25"
        assert result[25]["body"] == "Thread2-Comment1"
        assert result[99]["body"] == "Thread4-Comment25"
        assert result[100]["body"] == "Thread5-Comment1"
        assert result[104]["body"] == "Thread5-Comment5"

        # Check log records
        assert "Reached max_comments limit" in caplog.text


@pytest.mark.asyncio
async def test_graphql_limit_with_pagination_stops_early(
    monkeypatch: pytest.MonkeyPatch, github_token: str, caplog: pytest.LogCaptureFixture
) -> None:
    """
    Test that pagination stops when limit is reached during page processing.

    Verifies that the function fills up to max_comments across multiple pages,
    stopping mid-page when the limit is reached.
    """
    import logging

    caplog.set_level(logging.INFO)
    monkeypatch.setenv("HTTP_MAX_RETRIES", "0")

    # First page: 80 comments
    thread_comments_page1 = []
    for i in range(1, 81):
        thread_comments_page1.append(
            {
                "author": {"login": f"user{i}"},
                "body": f"Page1-Comment{i}",
                "path": "file.py",
                "line": i,
                "diffHunk": "@@ -1,1 +1,1 @@",
            }
        )

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
                                "comments": {"nodes": thread_comments_page1},
                            }
                        ],
                    }
                }
            }
        }
    }
    mock_response_1.raise_for_status = MagicMock()

    # Second page: 80 more comments (we'll stop at 120 total)
    thread_comments_page2 = []
    for i in range(81, 161):
        thread_comments_page2.append(
            {
                "author": {"login": f"user{i}"},
                "body": f"Page2-Comment{i}",
                "path": "file.py",
                "line": i,
                "diffHunk": "@@ -1,1 +1,1 @@",
            }
        )

    mock_response_2 = MagicMock()
    mock_response_2.status_code = 200
    mock_response_2.json.return_value = {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "pageInfo": {"hasNextPage": True, "endCursor": "cursor2"},
                        "nodes": [
                            {
                                "isResolved": False,
                                "isOutdated": False,
                                "resolvedBy": None,
                                "comments": {"nodes": thread_comments_page2},
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

        # Set limit to 120, page 1 has 80, page 2 has 80, should stop at 120
        result = await fetch_pr_comments_graphql("owner", "repo", 123, max_comments=120)

        assert result is not None
        # Should have exactly 120 comments (80 from page 1, 40 from page 2)
        assert len(result) == 120

        # Verify both pages were fetched to fill up to the limit
        assert mock_client.post.call_count == 2

        # Verify comments from both pages
        assert result[0]["body"] == "Page1-Comment1"
        assert result[79]["body"] == "Page1-Comment80"
        assert result[80]["body"] == "Page2-Comment81"
        assert result[119]["body"] == "Page2-Comment120"

        # Verify limit message was printed
        # Check log records
        assert "Reached max_comments limit" in caplog.text


@pytest.mark.asyncio
async def test_graphql_no_limit_message_when_under_limit(
    monkeypatch: pytest.MonkeyPatch, github_token: str, caplog: pytest.LogCaptureFixture
) -> None:
    """
    Test that no limit message is printed when total comments are under the limit.

    Verifies that the diagnostic message only appears when the limit is
    actually reached, not on normal completion.
    """
    monkeypatch.setenv("HTTP_MAX_RETRIES", "0")

    # Single thread with only 50 comments
    thread_comments = []
    for i in range(1, 51):
        thread_comments.append(
            {
                "author": {"login": f"user{i}"},
                "body": f"Comment {i}",
                "path": "file.py",
                "line": i,
                "diffHunk": "@@ -1,1 +1,1 @@",
            }
        )

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
                                "comments": {"nodes": thread_comments},
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

        # Set limit much higher than actual comments
        result = await fetch_pr_comments_graphql("owner", "repo", 123, max_comments=200)

        assert result is not None
        assert len(result) == 50

        # Verify NO limit message was printed
        # Check log records
        assert "Reached max_comments limit" not in caplog.text


@pytest.mark.asyncio
async def test_graphql_limit_exactly_at_comment_count(
    monkeypatch: pytest.MonkeyPatch, github_token: str, caplog: pytest.LogCaptureFixture
) -> None:
    """
    Test behavior when limit is set exactly to the total comment count.

    Verifies that when we have exactly max_comments, the limit message
    is printed appropriately.
    """
    import logging

    caplog.set_level(logging.INFO)
    monkeypatch.setenv("HTTP_MAX_RETRIES", "0")

    # Exactly 100 comments (the minimum allowed max_comments)
    thread_comments = []
    for i in range(1, 101):
        thread_comments.append(
            {
                "author": {"login": f"user{i}"},
                "body": f"Comment {i}",
                "path": "file.py",
                "line": i,
                "diffHunk": "@@ -1,1 +1,1 @@",
            }
        )

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
                                "comments": {"nodes": thread_comments},
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

        result = await fetch_pr_comments_graphql("owner", "repo", 123, max_comments=100)

        assert result is not None
        assert len(result) == 100

        # When we hit exactly the limit, the message should be printed
        # Check log records
        assert "Reached max_comments limit" in caplog.text


@pytest.mark.asyncio
async def test_graphql_empty_threads_do_not_affect_limit(
    monkeypatch: pytest.MonkeyPatch, github_token: str
) -> None:
    """
    Test that empty threads (no comments) don't interfere with limit logic.

    Verifies that threads with no comments are processed correctly and
    don't cause issues with the limit_reached flag.
    """
    monkeypatch.setenv("HTTP_MAX_RETRIES", "0")

    # Mix of empty and non-empty threads
    threads = []

    # Thread 1: empty
    threads.append(
        {
            "isResolved": False,
            "isOutdated": False,
            "resolvedBy": None,
            "comments": {"nodes": []},
        }
    )

    # Thread 2: 60 comments
    thread2_comments = []
    for i in range(1, 61):
        thread2_comments.append(
            {
                "author": {"login": f"user{i}"},
                "body": f"Comment {i}",
                "path": "file.py",
                "line": i,
                "diffHunk": "@@ -1,1 +1,1 @@",
            }
        )
    threads.append(
        {
            "isResolved": False,
            "isOutdated": False,
            "resolvedBy": None,
            "comments": {"nodes": thread2_comments},
        }
    )

    # Thread 3: empty
    threads.append(
        {
            "isResolved": True,
            "isOutdated": False,
            "resolvedBy": {"login": "resolver"},
            "comments": {"nodes": []},
        }
    )

    # Thread 4: 50 comments
    thread4_comments = []
    for i in range(61, 111):
        thread4_comments.append(
            {
                "author": {"login": f"user{i}"},
                "body": f"Comment {i}",
                "path": "file.py",
                "line": i,
                "diffHunk": "@@ -1,1 +1,1 @@",
            }
        )
    threads.append(
        {
            "isResolved": False,
            "isOutdated": False,
            "resolvedBy": None,
            "comments": {"nodes": thread4_comments},
        }
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": threads,
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

        result = await fetch_pr_comments_graphql("owner", "repo", 123, max_comments=150)

        assert result is not None
        # Should get all 110 comments (60 + 50) from non-empty threads
        assert len(result) == 110
        assert result[0]["body"] == "Comment 1"
        assert result[59]["body"] == "Comment 60"
        assert result[60]["body"] == "Comment 61"
        assert result[109]["body"] == "Comment 110"
