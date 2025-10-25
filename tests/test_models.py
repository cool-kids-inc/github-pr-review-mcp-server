"""Tests for Pydantic models in models.py."""

import pytest
from pydantic import ValidationError

from mcp_github_pr_review.models import (
    ErrorMessageModel,
    FetchPRReviewCommentsArgs,
    GitContextModel,
    GitHubUserModel,
    ResolveOpenPrUrlArgs,
    ReviewCommentModel,
)


class TestGitHubUserModel:
    """Tests for GitHubUserModel."""

    def test_default_unknown_login(self) -> None:
        """Test that login defaults to 'unknown' when not provided."""
        user = GitHubUserModel()
        assert user.login == "unknown"

    def test_custom_login(self) -> None:
        """Test that custom login is preserved."""
        user = GitHubUserModel(login="octocat")
        assert user.login == "octocat"

    def test_rejects_empty_string_login(self) -> None:
        """Test that empty string login is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            GitHubUserModel(login="")
        assert "String should have at least 1 character" in str(exc_info.value)

    def test_strips_whitespace_from_login(self) -> None:
        """Test that whitespace is stripped from login."""
        user = GitHubUserModel(login="  octocat  ")
        assert user.login == "octocat"

    def test_forbids_extra_fields(self) -> None:
        """Test that extra fields are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            GitHubUserModel(login="octocat", extra_field="value")  # type: ignore
        assert "Extra inputs are not permitted" in str(exc_info.value)


class TestErrorMessageModel:
    """Tests for ErrorMessageModel."""

    def test_creates_error_message(self) -> None:
        """Test that error message is created correctly."""
        error = ErrorMessageModel(error="Something went wrong")
        assert error.error == "Something went wrong"

    def test_rejects_empty_error(self) -> None:
        """Test that empty error string is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            ErrorMessageModel(error="")
        assert "String should have at least 1 character" in str(exc_info.value)

    def test_preserves_error_content(self) -> None:
        """Test that error content is preserved exactly."""
        message = "API rate limit exceeded: 403"
        error = ErrorMessageModel(error=message)
        assert error.error == message

    def test_forbids_extra_fields(self) -> None:
        """Test that extra fields are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            ErrorMessageModel(error="test", extra="field")  # type: ignore
        assert "Extra inputs are not permitted" in str(exc_info.value)


class TestGitContextModel:
    """Tests for GitContextModel."""

    def test_creates_git_context(self) -> None:
        """Test that git context is created correctly."""
        ctx = GitContextModel(
            host="github.com",
            owner="octocat",
            repo="Hello-World",
            branch="main",
        )
        assert ctx.host == "github.com"
        assert ctx.owner == "octocat"
        assert ctx.repo == "Hello-World"
        assert ctx.branch == "main"

    def test_rejects_empty_host(self) -> None:
        """Test that empty host is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            GitContextModel(host="", owner="octocat", repo="repo", branch="main")
        assert "String should have at least 1 character" in str(exc_info.value)

    def test_rejects_empty_owner(self) -> None:
        """Test that empty owner is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            GitContextModel(host="github.com", owner="", repo="repo", branch="main")
        assert "String should have at least 1 character" in str(exc_info.value)

    def test_rejects_empty_repo(self) -> None:
        """Test that empty repo is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            GitContextModel(host="github.com", owner="octocat", repo="", branch="main")
        assert "String should have at least 1 character" in str(exc_info.value)

    def test_rejects_empty_branch(self) -> None:
        """Test that empty branch is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            GitContextModel(host="github.com", owner="octocat", repo="repo", branch="")
        assert "String should have at least 1 character" in str(exc_info.value)

    def test_normalizes_host_to_lowercase(self) -> None:
        """Test that host is normalized to lowercase."""
        ctx = GitContextModel(
            host="GitHub.COM",
            owner="octocat",
            repo="repo",
            branch="main",
        )
        assert ctx.host == "github.com"

    def test_strips_whitespace_from_host(self) -> None:
        """Test that whitespace is stripped from host."""
        ctx = GitContextModel(
            host="  github.com  ",
            owner="octocat",
            repo="repo",
            branch="main",
        )
        assert ctx.host == "github.com"

    def test_strips_whitespace_from_fields(self) -> None:
        """Test that whitespace is stripped from all fields."""
        ctx = GitContextModel(
            host="  github.com  ",
            owner="  octocat  ",
            repo="  repo  ",
            branch="  main  ",
        )
        assert ctx.host == "github.com"
        assert ctx.owner == "octocat"
        assert ctx.repo == "repo"
        assert ctx.branch == "main"

    def test_forbids_extra_fields(self) -> None:
        """Test that extra fields are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            GitContextModel(
                host="github.com",
                owner="octocat",
                repo="repo",
                branch="main",
                extra="field",  # type: ignore
            )
        assert "Extra inputs are not permitted" in str(exc_info.value)


class TestReviewCommentModel:
    """Tests for ReviewCommentModel."""

    def test_creates_review_comment(self) -> None:
        """Test that review comment is created correctly."""
        comment = ReviewCommentModel(
            user=GitHubUserModel(login="reviewer"),
            path="src/main.py",
            line=42,
            body="Please fix this",
            diff_hunk="@@ -40,3 +40,3 @@",
            is_resolved=False,
            is_outdated=False,
            resolved_by=None,
        )
        assert comment.user.login == "reviewer"
        assert comment.path == "src/main.py"
        assert comment.line == 42
        assert comment.body == "Please fix this"
        assert comment.diff_hunk == "@@ -40,3 +40,3 @@"
        assert comment.is_resolved is False
        assert comment.is_outdated is False
        assert comment.resolved_by is None

    def test_defaults_line_to_zero(self) -> None:
        """Test that line defaults to 0 for file-level comments."""
        comment = ReviewCommentModel(
            user=GitHubUserModel(login="reviewer"),
            path="README.md",
            body="General comment",
        )
        assert comment.line == 0

    def test_defaults_diff_hunk_to_empty(self) -> None:
        """Test that diff_hunk defaults to empty string."""
        comment = ReviewCommentModel(
            user=GitHubUserModel(login="reviewer"),
            path="README.md",
            body="Comment",
        )
        assert comment.diff_hunk == ""

    def test_defaults_booleans_to_false(self) -> None:
        """Test that boolean fields default to False."""
        comment = ReviewCommentModel(
            user=GitHubUserModel(login="reviewer"),
            path="README.md",
            body="Comment",
        )
        assert comment.is_resolved is False
        assert comment.is_outdated is False

    def test_allows_empty_body(self) -> None:
        """Test that empty body is allowed."""
        comment = ReviewCommentModel(
            user=GitHubUserModel(login="reviewer"),
            path="README.md",
            body="",
        )
        assert comment.body == ""

    def test_converts_empty_path_to_unknown(self) -> None:
        """Test that empty path is converted to 'unknown'."""
        comment = ReviewCommentModel(
            user=GitHubUserModel(login="reviewer"),
            path="",
            body="Comment",
        )
        assert comment.path == "unknown"

        # Test with None path too
        comment2 = ReviewCommentModel(
            user=GitHubUserModel(login="reviewer"),
            path=None,  # type: ignore
            body="Comment",
        )
        assert comment2.path == "unknown"

    def test_rejects_negative_line(self) -> None:
        """Test that negative line number is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            ReviewCommentModel(
                user=GitHubUserModel(login="reviewer"),
                path="README.md",
                line=-1,
                body="Comment",
            )
        assert "Input should be greater than or equal to 0" in str(exc_info.value)

    def test_from_rest_with_complete_data(self) -> None:
        """Test from_rest() with complete REST API data."""
        rest_data = {
            "user": {"login": "octocat"},
            "path": "src/app.py",
            "line": 100,
            "body": "Looks good!",
            "diff_hunk": "@@ -98,3 +98,3 @@",
            "is_resolved": True,
            "is_outdated": False,
            "resolved_by": "maintainer",
        }
        comment = ReviewCommentModel.from_rest(rest_data)
        assert comment.user.login == "octocat"
        assert comment.path == "src/app.py"
        assert comment.line == 100
        assert comment.body == "Looks good!"
        assert comment.diff_hunk == "@@ -98,3 +98,3 @@"
        assert comment.is_resolved is True
        assert comment.is_outdated is False
        assert comment.resolved_by == "maintainer"

    def test_from_rest_with_missing_user(self) -> None:
        """Test from_rest() handles missing user gracefully."""
        rest_data = {
            "path": "src/app.py",
            "body": "Comment from deleted user",
        }
        comment = ReviewCommentModel.from_rest(rest_data)
        assert comment.user.login == "unknown"

    def test_from_rest_with_null_user(self) -> None:
        """Test from_rest() handles null user gracefully."""
        rest_data = {
            "user": None,
            "path": "src/app.py",
            "body": "Comment",
        }
        comment = ReviewCommentModel.from_rest(rest_data)
        assert comment.user.login == "unknown"

    def test_from_rest_with_missing_optional_fields(self) -> None:
        """Test from_rest() handles missing optional fields."""
        rest_data = {
            "user": {"login": "octocat"},
            "path": "src/app.py",
            "body": "Comment",
        }
        comment = ReviewCommentModel.from_rest(rest_data)
        assert comment.line == 0
        assert comment.diff_hunk == ""
        assert comment.is_resolved is False
        assert comment.is_outdated is False
        assert comment.resolved_by is None

    def test_from_rest_with_null_line(self) -> None:
        """Test from_rest() handles null line as 0."""
        rest_data = {
            "user": {"login": "octocat"},
            "path": "src/app.py",
            "line": None,
            "body": "File-level comment",
        }
        comment = ReviewCommentModel.from_rest(rest_data)
        assert comment.line == 0

    def test_from_graphql_with_complete_data(self) -> None:
        """Test from_graphql() with complete GraphQL node data."""
        graphql_node = {
            "author": {"login": "octocat"},
            "path": "src/app.py",
            "line": 100,
            "body": "Nice work!",
            "diffHunk": "@@ -98,3 +98,3 @@",
            "isResolved": True,
            "isOutdated": False,
            "resolvedBy": {"login": "maintainer"},
        }
        comment = ReviewCommentModel.from_graphql(graphql_node)
        assert comment.user.login == "octocat"
        assert comment.path == "src/app.py"
        assert comment.line == 100
        assert comment.body == "Nice work!"
        assert comment.diff_hunk == "@@ -98,3 +98,3 @@"
        assert comment.is_resolved is True
        assert comment.is_outdated is False
        assert comment.resolved_by == "maintainer"

    def test_from_graphql_with_missing_author(self) -> None:
        """Test from_graphql() handles missing author gracefully."""
        graphql_node = {
            "path": "src/app.py",
            "body": "Comment from deleted user",
        }
        comment = ReviewCommentModel.from_graphql(graphql_node)
        assert comment.user.login == "unknown"

    def test_from_graphql_with_null_author(self) -> None:
        """Test from_graphql() handles null author gracefully."""
        graphql_node = {
            "author": None,
            "path": "src/app.py",
            "body": "Comment",
        }
        comment = ReviewCommentModel.from_graphql(graphql_node)
        assert comment.user.login == "unknown"

    def test_from_graphql_with_missing_resolved_by(self) -> None:
        """Test from_graphql() handles missing resolvedBy."""
        graphql_node = {
            "author": {"login": "octocat"},
            "path": "src/app.py",
            "body": "Comment",
            "isResolved": False,
        }
        comment = ReviewCommentModel.from_graphql(graphql_node)
        assert comment.resolved_by is None

    def test_from_graphql_with_null_resolved_by(self) -> None:
        """Test from_graphql() handles null resolvedBy."""
        graphql_node = {
            "author": {"login": "octocat"},
            "path": "src/app.py",
            "body": "Comment",
            "resolvedBy": None,
        }
        comment = ReviewCommentModel.from_graphql(graphql_node)
        assert comment.resolved_by is None

    def test_from_rest_defaults_empty_path_to_unknown(self) -> None:
        """Test from_rest() converts empty path to 'unknown'."""
        rest_comment = {
            "user": {"login": "user1"},
            "path": "",  # Empty path
            "body": "Comment",
        }
        comment = ReviewCommentModel.from_rest(rest_comment)
        assert comment.path == "unknown"

    def test_from_rest_defaults_missing_path_to_unknown(self) -> None:
        """Test from_rest() converts missing path to 'unknown'."""
        rest_comment = {
            "user": {"login": "user1"},
            # No 'path' field
            "body": "Comment",
        }
        comment = ReviewCommentModel.from_rest(rest_comment)
        assert comment.path == "unknown"

    def test_from_graphql_defaults_empty_path_to_unknown(self) -> None:
        """Test from_graphql() converts empty path to 'unknown'."""
        graphql_node = {
            "author": {"login": "user1"},
            "path": "",  # Empty path
            "body": "Comment",
        }
        comment = ReviewCommentModel.from_graphql(graphql_node)
        assert comment.path == "unknown"

    def test_from_graphql_defaults_missing_path_to_unknown(self) -> None:
        """Test from_graphql() converts missing path to 'unknown'."""
        graphql_node = {
            "author": {"login": "user1"},
            # No 'path' field
            "body": "Comment",
        }
        comment = ReviewCommentModel.from_graphql(graphql_node)
        assert comment.path == "unknown"

    def test_from_graphql_preserves_string_id(self) -> None:
        """Test from_graphql() preserves GraphQL-style opaque string IDs."""
        graphql_node = {
            "id": "PRRC_cmt_123abc",  # Opaque string ID
            "author": {"login": "user1"},
            "path": "src/app.py",
            "body": "Comment",
        }
        comment = ReviewCommentModel.from_graphql(graphql_node)
        assert comment.id == "PRRC_cmt_123abc"

    def test_model_dump_matches_typeddict_format(self) -> None:
        """Test that model_dump() produces dict matching TypedDict format."""
        comment = ReviewCommentModel(
            user=GitHubUserModel(login="octocat"),
            path="src/app.py",
            line=42,
            body="Comment",
            diff_hunk="@@ -40,3 +40,3 @@",
            is_resolved=True,
            is_outdated=False,
            resolved_by="maintainer",
        )
        dumped = comment.model_dump()
        assert dumped["user"]["login"] == "octocat"
        assert dumped["path"] == "src/app.py"
        assert dumped["line"] == 42
        assert dumped["body"] == "Comment"
        assert dumped["diff_hunk"] == "@@ -40,3 +40,3 @@"
        assert dumped["is_resolved"] is True
        assert dumped["is_outdated"] is False
        assert dumped["resolved_by"] == "maintainer"

    def test_forbids_extra_fields(self) -> None:
        """Test that extra fields are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            ReviewCommentModel(
                user=GitHubUserModel(login="reviewer"),
                path="README.md",
                body="Comment",
                extra_field="value",  # type: ignore
            )
        assert "Extra inputs are not permitted" in str(exc_info.value)


class TestFetchPRReviewCommentsArgs:
    """Tests for FetchPRReviewCommentsArgs."""

    def test_creates_with_defaults(self) -> None:
        """Test that args are created with defaults."""
        args = FetchPRReviewCommentsArgs()
        assert args.pr_url is None
        assert args.output == "markdown"
        assert args.per_page is None
        assert args.max_pages is None
        assert args.max_comments is None
        assert args.max_retries is None
        assert args.owner is None
        assert args.repo is None
        assert args.branch is None
        assert args.select_strategy == "branch"

    def test_validates_per_page_range(self) -> None:
        """Test that per_page is validated within range 1-100."""
        args = FetchPRReviewCommentsArgs(per_page=50)
        assert args.per_page == 50

        with pytest.raises(ValidationError) as exc_info:
            FetchPRReviewCommentsArgs(per_page=0)
        assert "Input should be greater than or equal to 1" in str(exc_info.value)

        with pytest.raises(ValidationError) as exc_info:
            FetchPRReviewCommentsArgs(per_page=101)
        assert "Input should be less than or equal to 100" in str(exc_info.value)

    def test_validates_max_pages_range(self) -> None:
        """Test that max_pages is validated within range 1-200."""
        args = FetchPRReviewCommentsArgs(max_pages=50)
        assert args.max_pages == 50

        with pytest.raises(ValidationError) as exc_info:
            FetchPRReviewCommentsArgs(max_pages=0)
        assert "Input should be greater than or equal to 1" in str(exc_info.value)

        with pytest.raises(ValidationError) as exc_info:
            FetchPRReviewCommentsArgs(max_pages=201)
        assert "Input should be less than or equal to 200" in str(exc_info.value)

    def test_validates_max_comments_range(self) -> None:
        """Test that max_comments is validated within range 100-100000."""
        args = FetchPRReviewCommentsArgs(max_comments=1000)
        assert args.max_comments == 1000

        with pytest.raises(ValidationError) as exc_info:
            FetchPRReviewCommentsArgs(max_comments=99)
        assert "Input should be greater than or equal to 100" in str(exc_info.value)

        with pytest.raises(ValidationError) as exc_info:
            FetchPRReviewCommentsArgs(max_comments=100001)
        assert "Input should be less than or equal to 100000" in str(exc_info.value)

    def test_validates_max_retries_range(self) -> None:
        """Test that max_retries is validated within range 0-10."""
        args = FetchPRReviewCommentsArgs(max_retries=3)
        assert args.max_retries == 3

        with pytest.raises(ValidationError) as exc_info:
            FetchPRReviewCommentsArgs(max_retries=-1)
        assert "Input should be greater than or equal to 0" in str(exc_info.value)

        with pytest.raises(ValidationError) as exc_info:
            FetchPRReviewCommentsArgs(max_retries=11)
        assert "Input should be less than or equal to 10" in str(exc_info.value)

    def test_rejects_boolean_for_per_page(self) -> None:
        """Test that boolean values are rejected for per_page."""
        with pytest.raises(ValidationError) as exc_info:
            FetchPRReviewCommentsArgs(per_page=True)  # type: ignore
        assert "Invalid type: expected integer" in str(exc_info.value)

    def test_rejects_boolean_for_max_pages(self) -> None:
        """Test that boolean values are rejected for max_pages."""
        with pytest.raises(ValidationError) as exc_info:
            FetchPRReviewCommentsArgs(max_pages=False)  # type: ignore
        assert "Invalid type: expected integer" in str(exc_info.value)

    def test_rejects_boolean_for_max_comments(self) -> None:
        """Test that boolean values are rejected for max_comments."""
        with pytest.raises(ValidationError) as exc_info:
            FetchPRReviewCommentsArgs(max_comments=True)  # type: ignore
        assert "Invalid type: expected integer" in str(exc_info.value)

    def test_rejects_boolean_for_max_retries(self) -> None:
        """Test that boolean values are rejected for max_retries."""
        with pytest.raises(ValidationError) as exc_info:
            FetchPRReviewCommentsArgs(max_retries=False)  # type: ignore
        assert "Invalid type: expected integer" in str(exc_info.value)

    def test_rejects_float_for_per_page(self) -> None:
        """Test that float values are rejected for per_page."""
        with pytest.raises(ValidationError) as exc_info:
            FetchPRReviewCommentsArgs(per_page=1.5)  # type: ignore
        assert "Invalid type: expected integer" in str(exc_info.value)

    def test_rejects_float_for_max_pages(self) -> None:
        """Test that float values are rejected for max_pages."""
        with pytest.raises(ValidationError) as exc_info:
            FetchPRReviewCommentsArgs(max_pages=10.0)  # type: ignore
        assert "Invalid type: expected integer" in str(exc_info.value)

    def test_rejects_float_for_max_comments(self) -> None:
        """Test that float values are rejected for max_comments."""
        with pytest.raises(ValidationError) as exc_info:
            FetchPRReviewCommentsArgs(max_comments=1000.0)  # type: ignore
        assert "Invalid type: expected integer" in str(exc_info.value)

    def test_rejects_float_for_max_retries(self) -> None:
        """Test that float values are rejected for max_retries."""
        with pytest.raises(ValidationError) as exc_info:
            FetchPRReviewCommentsArgs(max_retries=3.0)  # type: ignore
        assert "Invalid type: expected integer" in str(exc_info.value)

    def test_accepts_none_for_optional_fields(self) -> None:
        """Test that None is accepted for optional fields."""
        args = FetchPRReviewCommentsArgs(
            per_page=None,
            max_pages=None,
            max_comments=None,
            max_retries=None,
        )
        assert args.per_page is None
        assert args.max_pages is None
        assert args.max_comments is None
        assert args.max_retries is None

    def test_validates_output_enum(self) -> None:
        """Test that output is validated against enum."""
        args = FetchPRReviewCommentsArgs(output="json")
        assert args.output == "json"

        args = FetchPRReviewCommentsArgs(output="both")
        assert args.output == "both"

        with pytest.raises(ValidationError) as exc_info:
            FetchPRReviewCommentsArgs(output="invalid")  # type: ignore
        # Check that error mentions all valid options
        error_str = str(exc_info.value)
        assert "markdown" in error_str and "json" in error_str and "both" in error_str

    def test_validates_select_strategy_enum(self) -> None:
        """Test that select_strategy is validated against enum."""
        args = FetchPRReviewCommentsArgs(select_strategy="latest")
        assert args.select_strategy == "latest"

        with pytest.raises(ValidationError) as exc_info:
            FetchPRReviewCommentsArgs(select_strategy="invalid")  # type: ignore
        # Check that error mentions at least some valid options
        error_str = str(exc_info.value)
        assert "branch" in error_str or "latest" in error_str or "first" in error_str

    def test_forbids_extra_fields(self) -> None:
        """Test that extra fields are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            FetchPRReviewCommentsArgs(extra_field="value")  # type: ignore
        assert "Extra inputs are not permitted" in str(exc_info.value)


class TestResolveOpenPrUrlArgs:
    """Tests for ResolveOpenPrUrlArgs."""

    def test_creates_with_defaults(self) -> None:
        """Test that args are created with defaults."""
        args = ResolveOpenPrUrlArgs()
        assert args.host is None
        assert args.owner is None
        assert args.repo is None
        assert args.branch is None
        assert args.select_strategy == "branch"

    def test_accepts_custom_values(self) -> None:
        """Test that custom values are accepted."""
        args = ResolveOpenPrUrlArgs(
            host="github.enterprise.com",
            owner="myorg",
            repo="myrepo",
            branch="feature",
            select_strategy="latest",
        )
        assert args.host == "github.enterprise.com"
        assert args.owner == "myorg"
        assert args.repo == "myrepo"
        assert args.branch == "feature"
        assert args.select_strategy == "latest"

    def test_validates_select_strategy_enum(self) -> None:
        """Test that select_strategy is validated against enum."""
        args = ResolveOpenPrUrlArgs(select_strategy="first")
        assert args.select_strategy == "first"

        with pytest.raises(ValidationError) as exc_info:
            ResolveOpenPrUrlArgs(select_strategy="invalid")  # type: ignore
        assert "Input should be" in str(exc_info.value)

    def test_forbids_extra_fields(self) -> None:
        """Test that extra fields are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            ResolveOpenPrUrlArgs(extra_field="value")  # type: ignore
        assert "Extra inputs are not permitted" in str(exc_info.value)
