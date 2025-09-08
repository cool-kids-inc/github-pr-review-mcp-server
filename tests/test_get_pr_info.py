import pytest

from mcp_server import get_pr_info


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/owner/repo/pull/123/",
        "https://github.com/owner/repo/pull/123/files",
        "https://github.com/owner/repo/pull/123?diff=split",
        "https://github.com/owner/repo/pull/123/files?foo=bar#fragment",
    ],
)
def test_get_pr_info_accepts_suffixes(url: str) -> None:
    assert get_pr_info(url) == ("owner", "repo", "123")


def test_get_pr_info_invalid_url() -> None:
    with pytest.raises(ValueError):
        get_pr_info("https://github.com/owner/repo/issues/123")
