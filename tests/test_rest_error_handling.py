"""Additional REST API error-handling tests for fetch_pr_comments."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from mcp_server import fetch_pr_comments


def _make_response(
    *,
    status: int,
    json_value: Any = None,
    headers: dict[str, str] | None = None,
    raise_error: Exception | None = None,
) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.headers = headers or {}
    response.json.return_value = [] if json_value is None else json_value
    if raise_error is not None:
        response.raise_for_status.side_effect = raise_error
    else:
        response.raise_for_status.return_value = None
    return response


@pytest.mark.asyncio
async def test_fetch_pr_comments_token_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Should retry with classic token scheme after a 401 using Bearer."""
    monkeypatch.setenv("GITHUB_TOKEN", "token123")

    unauthorized = _make_response(status=401)
    success = _make_response(status=200, json_value=[])

    auth_headers: list[str] = []

    async def _get(url: str, *, headers: dict[str, str]) -> MagicMock:  # noqa: ARG001
        responses = getattr(_get, "_responses", [unauthorized, success])
        if not responses:
            raise AssertionError("No responses left for AsyncClient.get")
        response = responses.pop(0)
        _get._responses = responses
        auth_headers.append(headers.get("Authorization", ""))
        return response

    mock_client = AsyncMock()
    mock_client.get.side_effect = _get
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("mcp_server.httpx.AsyncClient", return_value=mock_client):
        result = await fetch_pr_comments("owner", "repo", 1)

    assert result == []
    assert mock_client.get.await_count == 2
    assert auth_headers[0].startswith("Bearer ")
    assert auth_headers[1].startswith("token ")


@pytest.mark.asyncio
async def test_fetch_pr_comments_rate_limit_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Should back off on 403 responses with Retry-After before succeeding."""
    rate_limited = _make_response(status=403, headers={"Retry-After": "2"})
    success = _make_response(status=200, json_value=[])

    sleep_mock = AsyncMock()
    monkeypatch.setattr("mcp_server.asyncio.sleep", sleep_mock)

    async def _get(url: str, *, headers: dict[str, str]) -> MagicMock:  # noqa: ARG001
        responses = getattr(_get, "_responses", [rate_limited, success])
        if not responses:
            raise AssertionError("No responses left for AsyncClient.get")
        response = responses.pop(0)
        _get._responses = responses
        return response

    mock_client = AsyncMock()
    mock_client.get.side_effect = _get
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("mcp_server.httpx.AsyncClient", return_value=mock_client):
        result = await fetch_pr_comments("owner", "repo", 1)

    assert result == []
    sleep_mock.assert_awaited_once()
    assert sleep_mock.await_args.args[0] == 2


@pytest.mark.asyncio
async def test_fetch_pr_comments_rate_limit_uses_reset_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rate_limited = _make_response(
        status=403,
        headers={"X-RateLimit-Reset": "1005", "X-RateLimit-Remaining": "0"},
    )
    success = _make_response(status=200, json_value=[])

    sleep_mock = AsyncMock()
    monkeypatch.setattr("mcp_server.asyncio.sleep", sleep_mock)
    monkeypatch.setenv("GITHUB_TOKEN", "token123")
    monkeypatch.setattr("time.time", lambda: 1000.0)

    async def _get(url: str, *, headers: dict[str, str]) -> MagicMock:  # noqa: ARG001
        responses = getattr(_get, "_responses", [rate_limited, success])
        response = responses.pop(0)
        _get._responses = responses
        return response

    mock_client = AsyncMock()
    mock_client.get.side_effect = _get
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("mcp_server.httpx.AsyncClient", return_value=mock_client):
        await fetch_pr_comments("owner", "repo", 1)

    sleep_mock.assert_awaited_once()
    assert sleep_mock.await_args.args[0] == 5


@pytest.mark.asyncio
async def test_fetch_pr_comments_rate_limit_invalid_header(monkeypatch: pytest.MonkeyPatch) -> None:
    rate_limited = _make_response(status=429, headers={"Retry-After": "not-a-number"})
    success = _make_response(status=200, json_value=[])

    sleep_mock = AsyncMock()
    monkeypatch.setattr("mcp_server.asyncio.sleep", sleep_mock)

    async def _get(url: str, *, headers: dict[str, str]) -> MagicMock:  # noqa: ARG001
        responses = getattr(_get, "_responses", [rate_limited, success])
        response = responses.pop(0)
        _get._responses = responses
        return response

    mock_client = AsyncMock()
    mock_client.get.side_effect = _get
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("mcp_server.httpx.AsyncClient", return_value=mock_client):
        await fetch_pr_comments("owner", "repo", 1)

    sleep_mock.assert_awaited_once()
    assert sleep_mock.await_args.args[0] == 60


@pytest.mark.asyncio
async def test_fetch_pr_comments_returns_none_when_server_error_exhausts_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Should return None when 5xx responses exhaust retries."""
    request = httpx.Request("GET", "https://api.github.com")
    http_error = httpx.HTTPStatusError(
        "Server error",
        request=request,
        response=httpx.Response(500, request=request),
    )
    server_error = _make_response(status=500, raise_error=http_error)

    mock_client = AsyncMock()
    mock_client.get.side_effect = [server_error]
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("mcp_server.httpx.AsyncClient", return_value=mock_client):
        result = await fetch_pr_comments("owner", "repo", 1, max_retries=0)

    assert result is None


@pytest.mark.asyncio
async def test_fetch_pr_comments_returns_none_for_invalid_payload() -> None:
    """Should return None when the response payload is not a list."""
    invalid_payload = _make_response(status=200, json_value={"message": "oops"})

    mock_client = AsyncMock()
    mock_client.get.side_effect = [invalid_payload]
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("mcp_server.httpx.AsyncClient", return_value=mock_client):
        result = await fetch_pr_comments("owner", "repo", 1)

    assert result is None


@pytest.mark.asyncio
async def test_fetch_pr_comments_handles_timeout_exception() -> None:
    """Should return None when httpx raises a TimeoutException."""
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.get.side_effect = httpx.TimeoutException("timeout")

    with patch("mcp_server.httpx.AsyncClient", return_value=mock_client):
        result = await fetch_pr_comments("owner", "repo", 1)

    assert result is None
