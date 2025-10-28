"""Tests for GitHub rate limit handling and retry backoff logic."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from mcp_github_pr_review.server import (
    SECONDARY_RATE_LIMIT_BACKOFF,
    RateLimitHandler,
    SecondaryRateLimitError,
    _calculate_backoff_delay,
    fetch_pr_comments,
    fetch_pr_comments_graphql,
)


class SleepRecorder:
    """Helper to record asyncio.sleep calls without delaying tests."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, delay: float) -> None:  # pragma: no cover - trivial
        self.calls.append(delay)


def _make_rest_response(
    status: int,
    json_data: Any,
    *,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    request = httpx.Request(
        "GET",
        "https://api.github.com/repos/owner/repo/pulls/123/comments?per_page=100",
    )
    return httpx.Response(status, request=request, json=json_data, headers=headers)


def _make_graphql_response(
    status: int,
    json_data: Any,
    *,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    request = httpx.Request("POST", "https://api.github.com/graphql")
    return httpx.Response(status, request=request, json=json_data, headers=headers)


def _mock_async_client(method: str, side_effect: list[httpx.Response]) -> AsyncMock:
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.__aexit__.return_value = None
    async_method: Callable[..., Awaitable[httpx.Response]] = AsyncMock(
        side_effect=side_effect
    )
    setattr(client, method, async_method)
    return client


@pytest.mark.asyncio
async def test_rest_secondary_rate_limit_retries_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Secondary limits should sleep once and retry before succeeding."""

    secondary = _make_rest_response(
        403,
        {"message": "You have triggered an abuse detection mechanism."},
        headers={"X-GitHub-Request-Id": "abc123"},
    )
    success = _make_rest_response(
        200,
        [
            {
                "id": 1,
                "user": {"login": "reviewer"},
                "path": "file.py",
                "line": 7,
                "body": "Looks good",
                "diff_hunk": "@@ -1 +1 @@",
            }
        ],
    )

    client = _mock_async_client("get", [secondary, success])
    with patch("httpx.AsyncClient", return_value=client):
        recorder = SleepRecorder()
        monkeypatch.setattr("mcp_github_pr_review.server.asyncio.sleep", recorder)

        result = await fetch_pr_comments("owner", "repo", 123)

    assert result is not None
    assert len(result) == 1
    assert client.get.call_count == 2
    assert recorder.calls == [SECONDARY_RATE_LIMIT_BACKOFF]


@pytest.mark.asyncio
async def test_rest_secondary_rate_limit_stops_after_second_hit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Secondary limits should abort after a second consecutive response."""

    secondary_headers = {"X-GitHub-Request-Id": "def456"}
    secondary = _make_rest_response(
        403,
        {"message": "Secondary rate limit exceeded"},
        headers=secondary_headers,
    )

    client = _mock_async_client("get", [secondary, secondary])
    with patch("httpx.AsyncClient", return_value=client):
        recorder = SleepRecorder()
        monkeypatch.setattr("mcp_github_pr_review.server.asyncio.sleep", recorder)

        result = await fetch_pr_comments("owner", "repo", 123)

    assert result is None
    assert client.get.call_count == 2
    assert recorder.calls == [SECONDARY_RATE_LIMIT_BACKOFF]


@pytest.mark.asyncio
async def test_rest_primary_rate_limit_uses_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Primary limits should respect the Retry-After header for delays."""

    primary = _make_rest_response(
        403,
        {"message": "API rate limit exceeded"},
        headers={"Retry-After": "5", "X-GitHub-Request-Id": "ghi789"},
    )
    success = _make_rest_response(
        200,
        [
            {
                "id": 2,
                "user": {"login": "dev"},
                "path": "file.py",
                "line": 3,
                "body": "More info",
                "diff_hunk": "@@ -2 +2 @@",
            }
        ],
    )

    client = _mock_async_client("get", [primary, success])
    with patch("httpx.AsyncClient", return_value=client):
        recorder = SleepRecorder()
        monkeypatch.setattr("mcp_github_pr_review.server.asyncio.sleep", recorder)

        result = await fetch_pr_comments("owner", "repo", 456)

    assert result is not None
    assert len(result) == 1
    assert client.get.call_count == 2
    assert recorder.calls == [5.0]


@pytest.mark.asyncio
async def test_graphql_secondary_rate_limit_handling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GraphQL fetches should mimic REST secondary rate limit behavior."""

    monkeypatch.setenv("GITHUB_TOKEN", "token")

    secondary = _make_graphql_response(
        403,
        {"message": "Abuse detection triggered"},
        headers={"X-GitHub-Request-Id": "graphql-1"},
    )
    success = _make_graphql_response(
        200,
        {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [
                                {
                                    "isResolved": False,
                                    "isOutdated": False,
                                    "resolvedBy": {"login": "maintainer"},
                                    "comments": {
                                        "nodes": [
                                            {
                                                "id": "c1",
                                                "author": {"login": "reviewer"},
                                                "body": "GraphQL comment",
                                                "path": "file.py",
                                                "line": 10,
                                                "diffHunk": "@@ -3 +3 @@",
                                            }
                                        ]
                                    },
                                }
                            ],
                        }
                    }
                }
            }
        },
    )

    client = _mock_async_client("post", [secondary, success])
    with patch("httpx.AsyncClient", return_value=client):
        recorder = SleepRecorder()
        monkeypatch.setattr("mcp_github_pr_review.server.asyncio.sleep", recorder)

        result = await fetch_pr_comments_graphql("owner", "repo", 789)

    assert result is not None
    assert len(result) == 1
    assert client.post.call_count == 2
    assert recorder.calls == [SECONDARY_RATE_LIMIT_BACKOFF]


@pytest.mark.asyncio
async def test_graphql_secondary_rate_limit_abort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GraphQL fetch should abort after repeated secondary limits."""

    monkeypatch.setenv("GITHUB_TOKEN", "token")

    secondary = _make_graphql_response(
        403,
        {"message": "Secondary rate limit"},
        headers={"X-GitHub-Request-Id": "graphql-2"},
    )

    client = _mock_async_client("post", [secondary, secondary])
    with patch("httpx.AsyncClient", return_value=client):
        recorder = SleepRecorder()
        monkeypatch.setattr("mcp_github_pr_review.server.asyncio.sleep", recorder)

        result = await fetch_pr_comments_graphql("owner", "repo", 101)

    assert result is None
    assert client.post.call_count == 2
    assert recorder.calls == [SECONDARY_RATE_LIMIT_BACKOFF]


def test_calculate_backoff_delay_caps_at_fifteen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Backoff delay should not exceed the new 15 second ceiling."""

    monkeypatch.setattr("mcp_github_pr_review.server.random.uniform", lambda *_: 0.0)
    # Attempt 6 would yield 32 seconds without the cap
    assert _calculate_backoff_delay(6) == 15.0


# Unit tests for RateLimitHandler class


@pytest.mark.asyncio
async def test_rate_limit_handler_ignores_success_response() -> None:
    """Handler should return None for successful responses."""

    handler = RateLimitHandler("test_context")
    response = httpx.Response(
        200,
        request=httpx.Request("GET", "https://api.github.com/test"),
        json={"data": "success"},
    )

    result = await handler.handle_rate_limit(response)
    assert result is None
    assert not handler.secondary_retry_attempted


@pytest.mark.asyncio
async def test_rate_limit_handler_secondary_limit_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Handler should detect secondary limits and retry once."""

    recorder = SleepRecorder()
    monkeypatch.setattr("mcp_github_pr_review.server.asyncio.sleep", recorder)

    handler = RateLimitHandler("test_context", secondary_backoff=30.0)
    response = httpx.Response(
        403,
        request=httpx.Request("GET", "https://api.github.com/test"),
        json={"message": "You have exceeded a secondary rate limit"},
        headers={"X-GitHub-Request-Id": "test123"},
    )

    result = await handler.handle_rate_limit(response)
    assert result == "retry"
    assert handler.secondary_retry_attempted
    assert recorder.calls == [30.0]


@pytest.mark.asyncio
async def test_rate_limit_handler_secondary_limit_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Handler should raise SecondaryRateLimitError on second consecutive hit."""

    recorder = SleepRecorder()
    monkeypatch.setattr("mcp_github_pr_review.server.asyncio.sleep", recorder)

    handler = RateLimitHandler("test_context")
    response = httpx.Response(
        403,
        request=httpx.Request("GET", "https://api.github.com/test"),
        json={"message": "Abuse detection triggered"},
    )

    # First call should retry
    result = await handler.handle_rate_limit(response)
    assert result == "retry"
    assert recorder.calls == [SECONDARY_RATE_LIMIT_BACKOFF]

    # Second call should raise
    with pytest.raises(SecondaryRateLimitError) as exc_info:
        await handler.handle_rate_limit(response)

    assert exc_info.value.response == response


@pytest.mark.asyncio
async def test_rate_limit_handler_primary_limit_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Handler should respect Retry-After header for primary limits."""

    recorder = SleepRecorder()
    monkeypatch.setattr("mcp_github_pr_review.server.asyncio.sleep", recorder)

    handler = RateLimitHandler("test_context")
    response = httpx.Response(
        429,
        request=httpx.Request("GET", "https://api.github.com/test"),
        json={"message": "API rate limit exceeded"},
        headers={"Retry-After": "15", "X-GitHub-Request-Id": "primary123"},
    )

    result = await handler.handle_rate_limit(response)
    assert result == "retry"
    assert not handler.secondary_retry_attempted  # Should not affect secondary state
    assert recorder.calls == [15.0]


@pytest.mark.asyncio
async def test_rate_limit_handler_primary_limit_reset_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Handler should use X-RateLimit-Reset when available."""

    recorder = SleepRecorder()
    monkeypatch.setattr("mcp_github_pr_review.server.asyncio.sleep", recorder)

    # Mock time to ensure consistent test behavior
    mock_now = 1000000.0
    future_reset = mock_now + 25.0
    monkeypatch.setattr("mcp_github_pr_review.server.time.time", lambda: mock_now)

    handler = RateLimitHandler("test_context")
    response = httpx.Response(
        403,
        request=httpx.Request("GET", "https://api.github.com/test"),
        json={"message": "Rate limit exceeded"},
        headers={
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": str(int(future_reset)),
        },
    )

    result = await handler.handle_rate_limit(response)
    assert result == "retry"
    assert recorder.calls == [25.0]


@pytest.mark.asyncio
async def test_rate_limit_handler_custom_backoff() -> None:
    """Handler should accept custom secondary backoff duration."""

    handler = RateLimitHandler("test_context", secondary_backoff=120.0)
    assert handler.secondary_backoff == 120.0
    assert handler.context == "test_context"


@pytest.mark.asyncio
async def test_rate_limit_handler_primary_limit_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Handler should abort after max primary rate limit retries."""

    recorder = SleepRecorder()
    monkeypatch.setattr("mcp_github_pr_review.server.asyncio.sleep", recorder)

    handler = RateLimitHandler("test_context")
    response = httpx.Response(
        429,
        request=httpx.Request("GET", "https://api.github.com/test"),
        json={"message": "API rate limit exceeded"},
        headers={"Retry-After": "10"},
    )

    # First 3 retries should succeed
    for i in range(3):
        result = await handler.handle_rate_limit(response)
        assert result == "retry", f"Attempt {i + 1} should retry"
        assert handler.primary_retry_count == i + 1

    # 4th attempt should abort (3 is the max)
    result = await handler.handle_rate_limit(response)
    assert result is None, "Should abort after max retries"
    assert handler.primary_retry_count == 3
    assert recorder.calls == [10.0, 10.0, 10.0]  # 3 sleeps, no 4th


@pytest.mark.asyncio
async def test_rate_limit_handler_primary_retry_count_tracking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Handler should track primary retry count correctly."""

    recorder = SleepRecorder()
    monkeypatch.setattr("mcp_github_pr_review.server.asyncio.sleep", recorder)

    handler = RateLimitHandler("test_context")
    response = httpx.Response(
        403,
        request=httpx.Request("GET", "https://api.github.com/test"),
        json={"message": "Rate limit exceeded"},
        headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1000000"},
    )

    # Mock time to ensure consistent behavior
    monkeypatch.setattr("mcp_github_pr_review.server.time.time", lambda: 999990.0)

    assert handler.primary_retry_count == 0

    result = await handler.handle_rate_limit(response)
    assert result == "retry"
    assert handler.primary_retry_count == 1

    result = await handler.handle_rate_limit(response)
    assert result == "retry"
    assert handler.primary_retry_count == 2


@pytest.mark.asyncio
async def test_rate_limit_handler_primary_and_secondary_independent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Primary and secondary retry counts should be independent."""

    recorder = SleepRecorder()
    monkeypatch.setattr("mcp_github_pr_review.server.asyncio.sleep", recorder)

    handler = RateLimitHandler("test_context")

    # Hit secondary limit first
    secondary_response = httpx.Response(
        403,
        request=httpx.Request("GET", "https://api.github.com/test"),
        json={"message": "You have exceeded a secondary rate limit"},
    )

    result = await handler.handle_rate_limit(secondary_response)
    assert result == "retry"
    assert handler.secondary_retry_attempted is True
    assert handler.primary_retry_count == 0  # Should not affect primary count

    # Now hit primary limit
    primary_response = httpx.Response(
        429,
        request=httpx.Request("GET", "https://api.github.com/test"),
        json={"message": "API rate limit exceeded"},
        headers={"Retry-After": "5"},
    )

    result = await handler.handle_rate_limit(primary_response)
    assert result == "retry"
    assert handler.primary_retry_count == 1  # Should increment primary
    assert handler.secondary_retry_attempted is True  # Should not reset secondary


@pytest.mark.asyncio
async def test_rest_primary_rate_limit_persistent_aborts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Persistent primary rate limits should abort after max retries."""

    primary = _make_rest_response(
        403,
        {"message": "API rate limit exceeded"},
        headers={"Retry-After": "1", "X-GitHub-Request-Id": "ghi999"},
    )

    # Return primary rate limit response 4 times (initial + 3 retries)
    client = _mock_async_client("get", [primary, primary, primary, primary])

    with patch("httpx.AsyncClient", return_value=client):
        recorder = SleepRecorder()
        monkeypatch.setattr("mcp_github_pr_review.server.asyncio.sleep", recorder)

        # With PRIMARY_RATE_LIMIT_MAX_RETRIES=3, we should abort after 3 retries
        # and raise HTTPStatusError
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await fetch_pr_comments("owner", "repo", 123)

    # Should have raised 403 error
    assert exc_info.value.response.status_code == 403
    # Should have made 4 requests (initial + 3 retries)
    assert client.get.call_count == 4
    # Should have slept 3 times (once per retry)
    assert len(recorder.calls) == 3
    assert recorder.calls == [1.0, 1.0, 1.0]
