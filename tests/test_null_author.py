"""Tests for handling null/deleted author accounts in GraphQL responses."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_github_pr_review_spec_maker.server import fetch_pr_comments_graphql


@pytest.mark.asyncio
async def test_graphql_handles_null_author(github_token: str) -> None:
    """Should handle comments with null author (deleted accounts) gracefully."""
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
                                            "author": None,  # Deleted user
                                            "body": "Comment from deleted user",
                                            "path": "test.py",
                                            "line": 10,
                                            "diffHunk": "@@ test @@",
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
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        result = await fetch_pr_comments_graphql("owner", "repo", 123)

        assert result is not None
        assert len(result) == 1
        # Verify null author is handled gracefully with default "unknown"
        assert result[0]["user"]["login"] == "unknown"
        assert result[0]["body"] == "Comment from deleted user"


@pytest.mark.asyncio
async def test_graphql_handles_missing_author_field(github_token: str) -> None:
    """Should handle comments missing the author field entirely."""
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
                                            # Missing author field entirely
                                            "body": "Comment without author field",
                                            "path": "test.py",
                                            "line": 20,
                                            "diffHunk": "@@ test @@",
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
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        result = await fetch_pr_comments_graphql("owner", "repo", 123)

        assert result is not None
        assert len(result) == 1
        # Verify missing author field is handled with default "unknown"
        assert result[0]["user"]["login"] == "unknown"
        assert result[0]["body"] == "Comment without author field"


@pytest.mark.asyncio
async def test_graphql_handles_mixed_null_and_valid_authors(
    github_token: str,
) -> None:
    """Should handle mix of null and valid authors in same response."""
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
                                            "author": {"login": "valid_user"},
                                            "body": "Comment from valid user",
                                            "path": "test.py",
                                            "line": 10,
                                            "diffHunk": "@@ test @@",
                                        },
                                        {
                                            "author": None,  # Deleted user
                                            "body": "Comment from deleted user",
                                            "path": "test.py",
                                            "line": 20,
                                            "diffHunk": "@@ test @@",
                                        },
                                        {
                                            "author": {"login": "another_user"},
                                            "body": "Another valid comment",
                                            "path": "test.py",
                                            "line": 30,
                                            "diffHunk": "@@ test @@",
                                        },
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

        result = await fetch_pr_comments_graphql("owner", "repo", 123)

        assert result is not None
        assert len(result) == 3
        # Verify valid users are preserved
        assert result[0]["user"]["login"] == "valid_user"
        # Verify null author is handled
        assert result[1]["user"]["login"] == "unknown"
        # Verify another valid user
        assert result[2]["user"]["login"] == "another_user"


@pytest.mark.asyncio
async def test_graphql_handles_author_with_null_login(github_token: str) -> None:
    """Should handle author object with null login field."""
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
                                            "author": {
                                                "login": None
                                            },  # login is explicitly null
                                            "body": "Comment with null login",
                                            "path": "test.py",
                                            "line": 10,
                                            "diffHunk": "@@ test @@",
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
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        result = await fetch_pr_comments_graphql("owner", "repo", 123)

        assert result is not None
        assert len(result) == 1
        # Verify null login defaults to "unknown"
        assert result[0]["user"]["login"] == "unknown"
        assert result[0]["body"] == "Comment with null login"
