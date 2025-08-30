import httpx
import pytest

from git_pr_resolver import (
    api_base_for_host,
    git_detect_repo_branch,
    parse_remote_url,
    resolve_pr_url,
)


def test_parse_remote_url_variants():
    assert parse_remote_url("https://github.com/a/b") == ("github.com", "a", "b")
    assert parse_remote_url("https://github.com/a/b.git") == ("github.com", "a", "b")
    assert parse_remote_url("git@github.com:a/b.git") == ("github.com", "a", "b")


def test_api_base_for_host_ghe(monkeypatch):
    assert api_base_for_host("github.mycorp.com") == "https://github.mycorp.com/api/v3"
    monkeypatch.setenv("GITHUB_API_URL", "https://ghe.example/api/v3/")
    assert api_base_for_host("anything") == "https://ghe.example/api/v3"


def test_git_detect_repo_branch_env_override(monkeypatch):
    monkeypatch.setenv("MCP_PR_OWNER", "o")
    monkeypatch.setenv("MCP_PR_REPO", "r")
    monkeypatch.setenv("MCP_PR_BRANCH", "b")
    ctx = git_detect_repo_branch()
    assert ctx.owner == "o" and ctx.repo == "r" and ctx.branch == "b"


@pytest.mark.asyncio
async def test_resolve_pr_url_branch_strategy(monkeypatch):
    class DummyResp:
        def __init__(self, json_data, status_code=200):
            self._json = json_data
            self.status_code = status_code
            self.headers = {}

        def json(self):
            return self._json

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("error", request=None, response=None)

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None):
            if "head=o:branch" in url:
                return DummyResp(
                    [{"html_url": "https://github.com/o/r/pull/1", "number": 1}]
                )
            return DummyResp([])

    monkeypatch.setattr(
        "git_pr_resolver.httpx.AsyncClient", lambda *a, **k: FakeClient()
    )

    url = await resolve_pr_url("o", "r", branch="branch", select_strategy="branch")
    assert url.endswith("/pull/1")


@pytest.mark.asyncio
async def test_resolve_pr_url_uses_follow_redirects(monkeypatch):
    class DummyResp:
        def __init__(self, json_data, status_code=200):
            self._json = json_data
            self.status_code = status_code
            self.headers = {}

        def json(self):
            return self._json

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("error", request=None, response=None)

    class FakeClient:
        def __init__(self, *args, **kwargs):
            # Ensure our code passed follow_redirects=True
            assert kwargs.get("follow_redirects", False) is True

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None):
            # Return a simple open PR list
            return DummyResp(
                [{"html_url": "https://github.com/o/r/pull/2", "number": 2}]
            )

    monkeypatch.setattr(
        "git_pr_resolver.httpx.AsyncClient", lambda *a, **k: FakeClient(*a, **k)
    )

    url = await resolve_pr_url("o", "r", branch=None, select_strategy="latest")
    assert url.endswith("/pull/2")
