from __future__ import annotations

from typing import Any, TypedDict

from mcp_github_pr_review.server import CommentResult, generate_markdown


class _User(TypedDict, total=False):
    login: str


class _Comment(TypedDict, total=False):
    user: _User
    path: str
    line: int
    body: str
    diff_hunk: str
    is_resolved: bool
    is_outdated: bool
    resolved_by: str | None


def _build_comment_template() -> _Comment:
    return _Comment(
        user=_User(login="benchmark-user"),
        path="src/example.py",
        line=42,
        body=(
            "Lorem ipsum dolor sit amet, consectetur adipiscing elit. "
            "Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua."
        ),
        diff_hunk=(
            "@@ -1,3 +1,3 @@\n"
            "-old_value = 1\n"
            "+new_value = 2\n"
            " print('unchanged line')\n"
        ),
        is_resolved=False,
        is_outdated=False,
        resolved_by=None,
    )


def _build_comments(count: int) -> list[CommentResult]:
    base_comment = _build_comment_template()
    comments: list[CommentResult] = []
    for idx in range(count):
        comment: CommentResult = {
            **base_comment,
            "line": base_comment["line"] + idx,
            "body": f"{base_comment['body']} (comment {idx})",
            "diff_hunk": (
                "@@ -1,3 +1,3 @@\n"
                f"-old_value = {idx}\n"
                f"+new_value = {idx + 1}\n"
                " print('unchanged line')\n"
            ),
        }
        comments.append(comment)
    return comments


LARGE_COMMENT_SET = _build_comments(750)


def test_generate_markdown_benchmark(benchmark: Any) -> None:
    result = benchmark(generate_markdown, LARGE_COMMENT_SET)
    assert result.startswith("# Pull Request Review Comments")
    assert "comment 0" in result
    assert "comment 749" in result
