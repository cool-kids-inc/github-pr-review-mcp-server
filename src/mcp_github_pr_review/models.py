"""Pydantic models for GitHub PR review data structures.

This module provides strongly-typed, validated data models for:
- GitHub review comments (REST and GraphQL formats)
- MCP tool arguments
- Git repository context
- Error messages

All models use Pydantic v2 for runtime validation and type safety.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class GitHubUserModel(BaseModel):
    """Represents a GitHub user.

    Attributes:
        login: GitHub username, defaults to "unknown" if not provided
    """

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
    )

    login: str = Field(default="unknown", min_length=1)

    @field_validator("login")
    @classmethod
    def strip_login(cls, v: str) -> str:
        """Strip whitespace from login."""
        return v.strip()


class ErrorMessageModel(BaseModel):
    """Represents an error message.

    Attributes:
        error: Error description, must not be empty
    """

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
    )

    error: str = Field(min_length=1)


class GitContextModel(BaseModel):
    """Represents git repository context.

    Attributes:
        host: GitHub hostname (e.g., "github.com"), normalized to lowercase
        owner: Repository owner/organization
        repo: Repository name
        branch: Branch name
    """

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
    )

    host: str = Field(min_length=1)
    owner: str = Field(min_length=1)
    repo: str = Field(min_length=1)
    branch: str = Field(min_length=1)

    @field_validator("host")
    @classmethod
    def normalize_host(cls, v: str) -> str:
        """Normalize host to lowercase and strip whitespace."""
        return v.strip().lower()

    @field_validator("owner", "repo", "branch")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        """Strip leading/trailing whitespace."""
        return v.strip()


class ReviewCommentModel(BaseModel):
    """Represents a GitHub PR review comment.

    Supports both REST and GraphQL API response formats.

    Attributes:
        user: Comment author
        path: File path
        line: Line number (0 for file-level comments)
        body: Comment text
        diff_hunk: Diff context
        is_resolved: Whether comment is resolved
        is_outdated: Whether comment is outdated
        resolved_by: Username of resolver, if resolved
    """

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
    )

    id: int | str | None = None
    user: GitHubUserModel
    path: str = Field(min_length=1)
    line: int = Field(default=0, ge=0)
    body: str = Field(default="")
    diff_hunk: str = Field(default="")
    is_resolved: bool = False
    is_outdated: bool = False
    resolved_by: str | None = None

    @field_validator("path", mode="before")
    @classmethod
    def handle_empty_path(cls, v: Any) -> str:
        """Ensure path is not empty, defaulting to 'unknown' if needed.

        Runs before built-in validation to convert empty/None paths.
        """
        if v is None or (isinstance(v, str) and not v.strip()):
            return "unknown"
        return str(v)

    @classmethod
    def from_rest(cls, data: dict[str, Any]) -> ReviewCommentModel:
        """Create a ReviewCommentModel from REST API response data.

        Args:
            data: Raw REST API comment dict

        Returns:
            Validated ReviewCommentModel instance
        """
        # Extract user data, handling missing/null user
        user_data = data.get("user") or {}
        user_login = user_data.get("login", "unknown")

        # Handle None body
        body = data.get("body")
        if body is None:
            body = ""

        return cls(
            id=data.get("id"),
            user=GitHubUserModel(login=user_login),
            path=data.get("path", ""),
            line=data.get("line") or 0,
            body=body,
            diff_hunk=data.get("diff_hunk", ""),
            is_resolved=data.get("is_resolved", False),
            is_outdated=data.get("is_outdated", False),
            resolved_by=data.get("resolved_by"),
        )

    @classmethod
    def from_graphql(cls, node: dict[str, Any]) -> ReviewCommentModel:
        """Create a ReviewCommentModel from GraphQL node data.

        Args:
            node: GraphQL comment node dict

        Returns:
            Validated ReviewCommentModel instance
        """
        # Extract author data from GraphQL node
        author = node.get("author") or {}
        author_login = author.get("login") or "unknown"

        # Handle resolved_by field from GraphQL
        resolved_by_data = node.get("resolvedBy")
        resolved_by = resolved_by_data.get("login") if resolved_by_data else None

        return cls(
            id=node.get("id"),
            user=GitHubUserModel(login=author_login),
            path=node.get("path", ""),
            line=node.get("line") or 0,
            body=node.get("body", ""),
            diff_hunk=node.get("diffHunk", ""),
            is_resolved=node.get("isResolved", False),
            is_outdated=node.get("isOutdated", False),
            resolved_by=resolved_by,
        )


class FetchPRReviewCommentsArgs(BaseModel):
    """Arguments for the fetch_pr_review_comments MCP tool.

    All numeric fields have server-enforced limits to prevent runaway operations.
    """

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
    )

    pr_url: str | None = None
    output: Literal["markdown", "json", "both"] = "markdown"
    per_page: int | None = Field(default=None, ge=1, le=100)
    max_pages: int | None = Field(default=None, ge=1, le=200)
    max_comments: int | None = Field(default=None, ge=100, le=100000)
    max_retries: int | None = Field(default=None, ge=0, le=10)
    owner: str | None = None
    repo: str | None = None
    branch: str | None = None
    select_strategy: Literal["branch", "latest", "first", "error"] = "branch"

    @field_validator(
        "per_page", "max_pages", "max_comments", "max_retries", mode="before"
    )
    @classmethod
    def _reject_bool_and_float(cls, v: Any) -> Any:
        """Reject boolean and float values for numeric fields.

        This mimics the behavior of the original _validate_int function.
        Runs before Pydantic's type coercion.
        """
        if v is None:
            return v
        if isinstance(v, bool):
            raise ValueError("Invalid type: expected integer")
        if isinstance(v, float):
            raise ValueError("Invalid type: expected integer")
        return v


class ResolveOpenPrUrlArgs(BaseModel):
    """Arguments for the resolve_open_pr_url MCP tool."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
    )

    host: str | None = None
    owner: str | None = None
    repo: str | None = None
    branch: str | None = None
    select_strategy: Literal["branch", "latest", "first", "error"] = "branch"
