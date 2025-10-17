"""
Pagination and safety cap tests for fetch_pr_comments.

Key changes vs. old debug_test.py:
- Converted ad-hoc debug print test into proper pytest tests.
- Use fixtures from tests/conftest.py (mock_http_client, create_mock_response).
- Use pytest.mark.parametrize to cover multiple max_pages values.
- Assert outcomes instead of printing, ensuring idempotent, side-effect-free runs.
"""

from typing import Any

import pytest
from conftest import create_mock_response

from mcp_github_pr_review_spec_maker.server import fetch_pr_comments


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "max_pages, pages_enqueued, expected_count",
    [
        (1, 5, 2),  # stops after 1 page, 2 comments/page
        (3, 10, 6),  # stops after 3 pages, 2 comments/page
    ],
)
async def test_pagination_stops_at_max_pages(
    mock_http_client, max_pages: int, pages_enqueued: int, expected_count: int
) -> None:
    """
    Ensure fetch_pr_comments stops following Link rel="next" when hitting max_pages.

    - We enqueue pages with a Link header pointing to a next page.
    - Each page returns 2 comments; total returned must equal max_pages * 2.
    - The client should not fetch beyond the configured page limit.
    """
    # Prepare a chain of responses that always advertise a next page
    headers_with_next = {"Link": '<https://api.github.com/next>; rel="next"'}
    page_payload: list[dict[str, Any]] = [{"id": 1}, {"id": 2}]
    for _ in range(pages_enqueued):
        mock_http_client.add_get_response(
            create_mock_response(page_payload, headers=headers_with_next)
        )

    comments = await fetch_pr_comments(
        "o", "r", 1, max_pages=max_pages, max_comments=10_000
    )

    assert isinstance(comments, list)
    assert len(comments) == expected_count, "Should stop at max_pages"
    # Verify we fetched exactly the expected number of pages
    assert len(mock_http_client.get_calls) == max_pages


@pytest.mark.asyncio
async def test_comment_count_limit_stops_early(mock_http_client) -> None:
    """
    When max_comments is reached, fetching stops even if Link advertises next pages.

    We enqueue pages with 60 comments each and set max_comments=100 (the
    implementation clamps small values up to a minimum of 100). The function
    processes page 1 (60 items) and page 2 (60 items), then stops because
    120 >= 100.
    We assert no third page is fetched.
    """
    headers_with_next = {"Link": '<https://api.github.com/next>; rel="next"'}
    page_payload = [{"id": i} for i in range(60)]
    # Enqueue more responses than needed; the function should stop after 2
    for _ in range(5):
        mock_http_client.add_get_response(
            create_mock_response(page_payload, headers=headers_with_next)
        )

    max_comments = 100
    comments = await fetch_pr_comments(
        "o", "r", 1, max_pages=50, max_comments=max_comments
    )

    assert isinstance(comments, list)
    # Page 1: 60, Page 2: 60 -> total 120 (>= 100), then stop
    assert len(comments) == 120, "Stops after exceeding max_comments"
    assert len(mock_http_client.get_calls) == 2, (
        "Should not fetch a third page once limit reached"
    )
