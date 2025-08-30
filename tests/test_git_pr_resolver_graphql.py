import httpx
import pytest

from git_pr_resolver import resolve_pr_url


@pytest.mark.asyncio
async def test_resolve_pr_url_branch_graphql_success(monkeypatch):
    class DummyResp:
        def __init__(self, json_data, status_code=200):
            self._json = json_data
            self.status_code = status_code

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

        async def post(self, url, json=None, headers=None):  # noqa: A002
            # Return a GraphQL response with matching OPEN PR
            return DummyResp(
                {
                    "data": {
                        "repository": {
                            "pullRequests": {
                                "nodes": [
                                    {
                                        "number": 42,
                                        "headRefName": "branch",
                                        "state": "OPEN",
                                    }
                                ]
                            }
                        }
                    }
                }
            )

        async def get(self, url, headers=None):
            raise AssertionError(
                "REST fallback should not be called on GraphQL success"
            )

    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GH_HOST", "github.com")
    monkeypatch.setattr(
        "git_pr_resolver.httpx.AsyncClient", lambda *a, **k: FakeClient()
    )

    url = await resolve_pr_url("o", "r", branch="branch", select_strategy="branch")
    assert url == "https://github.com/o/r/pull/42"


@pytest.mark.asyncio
async def test_resolve_pr_url_branch_graphql_errors_fallback_rest(monkeypatch):
    class DummyResp:
        def __init__(self, json_data, status_code=200):
            self._json = json_data
            self.status_code = status_code

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

        async def post(self, url, json=None, headers=None):  # noqa: A002
            # GraphQL returns errors
            return DummyResp({"errors": [{"message": "bad"}]})

        async def get(self, url, headers=None):
            # Fallback REST returns first PR
            return DummyResp(
                [{"html_url": "https://github.com/o/r/pull/5", "number": 5}]
            )

    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setattr(
        "git_pr_resolver.httpx.AsyncClient", lambda *a, **k: FakeClient()
    )

    url = await resolve_pr_url("o", "r", branch="branch", select_strategy="branch")
    assert url.endswith("/pull/5")


@pytest.mark.asyncio
async def test_graphql_url_inference_on_ghe(monkeypatch):
    class DummyResp:
        def __init__(self, json_data, status_code=200):
            self._json = json_data
            self.status_code = status_code

        def json(self):
            return self._json

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("error", request=None, response=None)

    posted = {"called": False}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            # Ensure follow_redirects is enabled
            assert kwargs.get("follow_redirects", False) is True

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json=None, headers=None):  # noqa: A002
            # Ensure GraphQL endpoint inference from REST base
            assert url == "https://github.mycorp.com/api/graphql"
            posted["called"] = True
            return DummyResp(
                {
                    "data": {
                        "repository": {
                            "pullRequests": {
                                "nodes": [
                                    {
                                        "number": 9,
                                        "headRefName": "feature",
                                        "state": "OPEN",
                                    }
                                ]
                            }
                        }
                    }
                }
            )

        async def get(self, url, headers=None):
            # Return a generic open PR list if called; we only care that
            # GraphQL was attempted with the inferred URL and final host matches.
            return DummyResp(
                [{"html_url": "https://github.mycorp.com/o/r/pull/3", "number": 3}]
            )

    # Simulate GHES with REST base available; host used for HTML URL
    monkeypatch.setenv("GH_HOST", "github.mycorp.com")
    monkeypatch.setenv("GITHUB_API_URL", "https://github.mycorp.com/api/v3")
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("DEBUG_GITHUB_PR_RESOLVER", "1")
    monkeypatch.setattr(
        "git_pr_resolver.httpx.AsyncClient", lambda *a, **k: FakeClient(*a, **k)
    )

    url = await resolve_pr_url("o", "r", branch="feature", select_strategy="branch")
    assert posted["called"] is True
    assert url.startswith("https://github.mycorp.com/")
