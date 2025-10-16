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
    assert get_pr_info(url) == ("github.com", "owner", "repo", "123")


@pytest.mark.parametrize(
    "invalid_url",
    [
        # Not a pull request URL
        "https://github.com/owner/repo/issues/123",
        # Missing PR number
        "https://github.com/owner/repo/pull/",
        # Invalid characters after PR number without a separator
        "https://github.com/owner/repo/pull/123foo",
        # Non-numeric PR number
        "https://github.com/owner/repo/pull/abc",
    ],
)
def test_get_pr_info_invalid_url(invalid_url: str) -> None:
    with pytest.raises(ValueError):
        get_pr_info(invalid_url)


def test_get_pr_info_accepts_enterprise_hosts() -> None:
    """Test that any host is accepted for enterprise GitHub support."""
    # GitLab-style host should work (for enterprise GitHub on custom domains)
    host, owner, repo, num = get_pr_info("https://gitlab.com/owner/repo/pull/123")
    assert host == "gitlab.com"
    assert owner == "owner"
    assert repo == "repo"
    assert num == "123"
