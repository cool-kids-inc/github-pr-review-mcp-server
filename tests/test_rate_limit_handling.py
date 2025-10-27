"""Tests for GitHub rate limit handling and retry backoff logic."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from mcp_github_pr_review.server import (
    SECONDARY_RATE_LIMIT_BACKOFF,
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
