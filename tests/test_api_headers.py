"""Tests for GitHub API header standardization."""

import pytest
from httpx import Response

from mcp_github_pr_review.git_pr_resolver import resolve_pr_url
from mcp_github_pr_review.github_api_constants import (
    GITHUB_ACCEPT_HEADER,
    GITHUB_API_VERSION,
    GITHUB_USER_AGENT,
)
from mcp_github_pr_review.server import fetch_pr_comments, fetch_pr_comments_graphql


@pytest.mark.asyncio
async def test_rest_api_uses_modern_headers(respx_mock):
    """Verify REST API calls include modern GitHub headers."""
    # Mock the REST API response
    route = respx_mock.get(
        "https://api.github.com/repos/owner/repo/pulls/123/comments?per_page=100"
    ).mock(
        return_value=Response(
            200,
            json=[
                {
                    "user": {"login": "reviewer"},
                    "path": "test.py",
                    "line": 10,
                    "body": "Test comment",
                    "diff_hunk": "@@ -1,1 +1,1 @@",
                }
            ],
        )
    )

    await fetch_pr_comments("owner", "repo", 123)

    # Verify the request was made
    assert route.called
    request = route.calls[0].request

    # Verify modern headers are present
    assert request.headers.get("Accept") == GITHUB_ACCEPT_HEADER
    assert request.headers.get("X-GitHub-Api-Version") == GITHUB_API_VERSION
    assert request.headers.get("User-Agent") == GITHUB_USER_AGENT


@pytest.mark.asyncio
async def test_graphql_api_uses_modern_headers(respx_mock, monkeypatch):
    """Verify GraphQL API calls include modern GitHub headers."""
    monkeypatch.setenv("GITHUB_TOKEN", "test_token")

    # Mock the GraphQL response
    route = respx_mock.post("https://api.github.com/graphql").mock(
        return_value=Response(
            200,
            json={
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
                                                    "author": {"login": "reviewer"},
                                                    "body": "Test comment",
                                                    "path": "test.py",
                                                    "line": 10,
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
            },
        )
    )

    await fetch_pr_comments_graphql("owner", "repo", 123)

    # Verify the request was made
    assert route.called
    request = route.calls[0].request

    # Verify modern headers are present
    assert request.headers.get("Accept") == GITHUB_ACCEPT_HEADER
    assert request.headers.get("X-GitHub-Api-Version") == GITHUB_API_VERSION
    assert request.headers.get("User-Agent") == GITHUB_USER_AGENT
    assert request.headers.get("Content-Type") == "application/json"


@pytest.mark.asyncio
async def test_pr_resolver_uses_modern_headers(respx_mock, monkeypatch):
    """Verify PR resolution API calls include modern GitHub headers."""
    monkeypatch.setenv("GITHUB_TOKEN", "test_token")

    # Mock GraphQL endpoint (resolve_pr_url tries this first)
    graphql_route = respx_mock.post("https://api.github.com/graphql").mock(
        return_value=Response(
            200,
            json={
                "data": {
                    "repository": {
                        "pullRequests": {
                            "nodes": [{"number": 123, "headRefName": "feature-branch"}]
                        }
                    }
                }
            },
        )
    )

    # Mock the REST PR list endpoint (fallback, not used but needed for routing)
    respx_mock.get(
        "https://api.github.com/repos/owner/repo/pulls"
        "?state=open&head=owner:feature-branch"
    ).mock(
        return_value=Response(
            200,
            json=[
                {
                    "number": 123,
                    "html_url": "https://github.com/owner/repo/pull/123",
                    "head": {"ref": "feature-branch"},
                }
            ],
        )
    )

    await resolve_pr_url("owner", "repo", "feature-branch", select_strategy="branch")

    # GraphQL should be called first - verify its headers
    assert graphql_route.called
    graphql_request = graphql_route.calls[0].request

    # Verify modern headers are present in GraphQL request
    assert graphql_request.headers.get("Accept") == "application/vnd.github+json"
    assert graphql_request.headers.get("X-GitHub-Api-Version") == "2022-11-28"
    assert graphql_request.headers.get("User-Agent") == "mcp-pr-review/1.0"


@pytest.mark.asyncio
async def test_deprecated_v3_header_not_used(respx_mock):
    """Verify deprecated v3 header is not used in REST API calls."""
    route = respx_mock.get(
        "https://api.github.com/repos/owner/repo/pulls/123/comments?per_page=100"
    ).mock(
        return_value=Response(
            200,
            json=[],
        )
    )

    await fetch_pr_comments("owner", "repo", 123)

    assert route.called
    request = route.calls[0].request

    # Ensure deprecated header is NOT used
    assert request.headers.get("Accept") != "application/vnd.github.v3+json"
    # Ensure modern header IS used
    assert request.headers.get("Accept") == GITHUB_ACCEPT_HEADER


@pytest.mark.asyncio
async def test_api_version_header_present_in_retry(respx_mock):
    """Verify API version header persists through retries."""
    # Mock server error followed by success
    route = respx_mock.get(
        "https://api.github.com/repos/owner/repo/pulls/123/comments?per_page=100"
    ).mock(side_effect=[Response(500), Response(200, json=[])])

    await fetch_pr_comments("owner", "repo", 123, max_retries=1)

    # Both requests should have been made
    assert route.call_count == 2

    # Verify both requests have the version header
    for call in route.calls:
        assert call.request.headers.get("X-GitHub-Api-Version") == GITHUB_API_VERSION
        assert call.request.headers.get("Accept") == GITHUB_ACCEPT_HEADER
