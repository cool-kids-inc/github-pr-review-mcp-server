from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from git_pr_resolver import parse_remote_url
from mcp_server import (
    ReviewSpecGenerator,
    fetch_pr_comments,
    generate_markdown,
    get_pr_info,
)


@pytest.fixture
def server():
    """Provides a ReviewSpecGenerator instance for tests."""
    return ReviewSpecGenerator()


def test_get_pr_info_valid():
    url = "https://github.com/owner/repo/pull/123"
    owner, repo, pull_number = get_pr_info(url)
    assert owner == "owner"
    assert repo == "repo"
    assert pull_number == "123"


def test_get_pr_info_invalid():
    with pytest.raises(ValueError):
        get_pr_info("https://github.com/owner/repo/pull")
    with pytest.raises(ValueError):
        get_pr_info("not a url")
    with pytest.raises(ValueError):
        get_pr_info("https://github.com/owner/repo/pull/123/files")


@pytest.mark.asyncio
@patch("mcp_server.fetch_pr_comments")
async def test_fetch_pr_review_comments_success(mock_fetch_comments, server):
    mock_fetch_comments.return_value = [{"id": 1, "body": "Test comment"}]

    comments = await server.fetch_pr_review_comments(
        pr_url="https://github.com/owner/repo/pull/1"
    )

    assert len(comments) == 1
    assert comments[0]["body"] == "Test comment"
    mock_fetch_comments.assert_called_once_with(
        "owner",
        "repo",
        1,
        per_page=None,
        max_pages=None,
        max_comments=None,
        max_retries=None,
    )


@pytest.mark.asyncio
async def test_fetch_pr_review_comments_invalid_url(server):
    comments = await server.fetch_pr_review_comments(pr_url="invalid-url")
    assert len(comments) == 1
    assert "error" in comments[0]
    assert "Invalid PR URL format" in comments[0]["error"]


def test_generate_markdown():
    comments = [
        {
            "user": {"login": "user1"},
            "path": "file1.py",
            "line": 10,
            "body": "Comment 1",
            "diff_hunk": "diff1",
        },
        {
            "user": {"login": "user2"},
            "path": "file2.py",
            "line": 20,
            "body": "Comment 2",
        },
    ]
    markdown = generate_markdown(comments)
    assert "user1" in markdown
    assert "file1.py" in markdown
    assert "diff1" in markdown
    assert "user2" in markdown
    assert "file2.py" in markdown


def test_generate_markdown_handles_backticks():
    comments = [
        {
            "user": {"login": "user"},
            "path": "file.py",
            "line": 1,
            "body": "here are backticks ``` inside",
        }
    ]
    markdown = generate_markdown(comments)
    # Expect at least a 4-backtick fence to encapsulate the body with triple backticks
    assert "````" in markdown


def test_parse_remote_url_https():
    host, owner, repo = parse_remote_url("https://github.com/foo/bar.git")
    assert host == "github.com"
    assert owner == "foo"
    assert repo == "bar"


def test_parse_remote_url_ssh():
    host, owner, repo = parse_remote_url("git@github.com:foo/bar.git")
    assert host == "github.com"
    assert owner == "foo"
    assert repo == "bar"


@pytest.mark.asyncio
async def test_auto_resolution_happy_path(server, monkeypatch):
    # Simulate dulwich Repo state for branch + remote discovery
    class FakeConfig:
        def get(self, section, key):
            # Return origin remote URL
            if section == (b"remote", b"origin") and key == b"url":
                return b"https://github.com/owner/repo.git"
            raise KeyError

        def sections(self):
            return [(b"remote", b"origin")]

    class FakeRefs:
        def read_ref(self, ref):
            # Simulate normal HEAD pointing at a branch
            return b"refs/heads/feature-branch"

    class FakeRepo:
        def get_config(self):
            return FakeConfig()

        @property
        def refs(self):
            return FakeRefs()

    # Patch dulwich Repo.discover to return our fake repo
    monkeypatch.setattr("git_pr_resolver.Repo.discover", lambda path: FakeRepo())

    # Avoid real network for comments fetch; return empty list
    async def _fake_fetch_comments(*args, **kwargs):
        return []

    monkeypatch.setattr("mcp_server.fetch_pr_comments", _fake_fetch_comments)

    # Mock GitHub API responses
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
            self.calls = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None):
            self.calls.append(url)
            # First try branch match -> return single PR
            if "head=owner:feature-branch" in url:
                return DummyResp(
                    [
                        {
                            "html_url": "https://github.com/owner/repo/pull/42",
                            "number": 42,
                        }
                    ]
                )
            # Fallback shouldn't be used
            return DummyResp([], status_code=200)

    def _client_ctor(*a, **k):
        # ensure follow_redirects is enabled by our MCP resolver
        assert k.get("follow_redirects", False) is True
        return FakeClient()

    monkeypatch.setattr("git_pr_resolver.httpx.AsyncClient", _client_ctor)

    comments = await server.fetch_pr_review_comments(
        pr_url=None,
        per_page=1,
        select_strategy="branch",
    )
    # We didn't mock comment fetching; URL parsing path is bypassed by resolver.
    # Here, just assert it returned a list (empty when not mocked further).
    assert isinstance(comments, list)


@pytest.mark.asyncio
async def test_create_review_spec_file(server):
    comments = [
        {"user": {"login": "user1"}, "path": "file1.py", "line": 10, "body": "Test"}
    ]

    # Ensure clean state
    out_dir = Path.cwd() / "review_specs"
    out_file = out_dir / "test.md"
    if out_file.exists():
        out_file.unlink()

    result = await server.create_review_spec_file(comments=comments, filename="test.md")

    # Expect success message mentioning the full output path
    assert "Successfully created spec file:" in result
    assert str(out_file.resolve()) in result
    assert out_file.exists()

    content = out_file.read_text(encoding="utf-8")
    assert "user1" in content
    assert "file1.py" in content

    # Cleanup
    out_file.unlink()
    try:
        out_dir.rmdir()
    except OSError:
        pass


@pytest.mark.asyncio
async def test_resolve_open_pr_url_tool(monkeypatch, server):
    # Mock git detection
    class Ctx:
        owner = "o"
        repo = "r"
        branch = "b"

    monkeypatch.setattr("mcp_server.git_detect_repo_branch", lambda: Ctx())

    # Mock resolver to return a specific URL
    async def _fake_resolve(owner, repo, branch, select_strategy, host=None):  # noqa: ARG001
        assert owner == "o" and repo == "r" and branch == "b"
        return "https://github.com/o/r/pull/99"

    monkeypatch.setattr("mcp_server.resolve_pr_url", _fake_resolve)

    resp = await server.handle_call_tool("resolve_open_pr_url", {})
    assert resp[0].text == "https://github.com/o/r/pull/99"


@pytest.mark.asyncio
async def test_create_review_spec_file_invalid_filename(server):
    comments = [
        {"user": {"login": "user1"}, "path": "file1.py", "line": 10, "body": "Test"}
    ]
    result = await server.create_review_spec_file(
        comments=comments, filename="../evil.md"
    )
    assert "Invalid filename" in result


@pytest.mark.asyncio
async def test_create_review_spec_file_default_name(server):
    comments = [
        {"user": {"login": "user1"}, "path": "file1.py", "line": 10, "body": "Test"}
    ]

    out_dir = Path.cwd() / "review_specs"
    before = set(out_dir.iterdir()) if out_dir.exists() else set()

    result = await server.create_review_spec_file(comments=comments)
    assert "Successfully created spec file:" in result

    after = set(out_dir.iterdir())
    new_files = list(after - before)
    # Expect exactly one new file
    assert len(new_files) == 1
    created = new_files[0]
    assert created.name.startswith("spec-") and created.name.endswith(".md")
    # Cleanup
    created.unlink()
    try:
        out_dir.rmdir()
    except OSError:
        pass


@pytest.mark.asyncio
async def test_fetch_pr_comments_page_cap(monkeypatch):
    # Simulate infinite next pages with 2 comments per page;
    # expect stop at MAX_PAGES (50)
    class DummyResp:
        def __init__(self, status_code=200):
            self.status_code = status_code
            self.headers = {"Link": '<https://next>; rel="next"'}

        def json(self):
            return [{"id": 1}, {"id": 2}]

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("error", request=None, response=None)

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None):
            self.calls += 1
            return DummyResp(200)

    fake = FakeClient()
    monkeypatch.setattr("mcp_server.httpx.AsyncClient", lambda *a, **k: fake)

    comments = await fetch_pr_comments("o", "r", 1)
    # Expect 50 pages * 2 comments per page = 100 comments
    assert len(comments) == 100
    assert fake.calls == 50


@pytest.mark.asyncio
async def test_fetch_pr_comments_comment_cap(monkeypatch):
    # Simulate 100 comments per page; expect stop at MAX_COMMENTS (2000) after 20 pages
    class DummyResp:
        def __init__(self, status_code=200):
            self.status_code = status_code
            self.headers = {"Link": '<https://next>; rel="next"'}

        def json(self):
            return [{"id": i} for i in range(100)]

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("error", request=None, response=None)

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None):
            self.calls += 1
            return DummyResp(200)

    fake = FakeClient()
    monkeypatch.setattr("mcp_server.httpx.AsyncClient", lambda *a, **k: fake)

    comments = await fetch_pr_comments("o", "r", 2)
    assert len(comments) == 2000
    assert fake.calls == 20


@pytest.mark.asyncio
async def test_fetch_pr_comments_token_fallback(monkeypatch):
    # First call with Bearer returns 401; fallback to 'token ' then returns 200
    class DummyResp:
        def __init__(self, status_code=200, link_next=None):
            self.status_code = status_code
            self.headers = {}
            if link_next:
                self.headers["Link"] = link_next

        def json(self):
            return [{"id": 1}]

        def raise_for_status(self):
            if self.status_code >= 400 and self.status_code != 401:
                raise httpx.HTTPStatusError("error", request=None, response=None)

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.calls = 0
            self.auth_history = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None):
            self.calls += 1
            self.auth_history.append(headers.get("Authorization"))
            if self.calls == 1:
                return DummyResp(401, link_next=None)
            return DummyResp(200, link_next=None)

    fake = FakeClient()
    monkeypatch.setattr("mcp_server.httpx.AsyncClient", lambda *a, **k: fake)

    # Ensure token is present in env for function to use
    monkeypatch.setenv("GITHUB_TOKEN", "x123")

    comments = await fetch_pr_comments("o", "r", 3)
    assert len(comments) == 1
    assert fake.calls == 2
    # First attempt uses Bearer, second uses token scheme
    assert fake.auth_history[0].startswith("Bearer ")
    assert fake.auth_history[1].startswith("token ")


@pytest.mark.asyncio
async def test_fetch_pr_comments_retries_on_5xx(monkeypatch):
    # Two 500s then a 200; should return after 3 attempts
    class DummyResp:
        def __init__(self, status_code=200, link_next=None):
            self.status_code = status_code
            self.headers = {}
            if link_next:
                self.headers["Link"] = link_next

        def json(self):
            return [{"id": 1}]

        def raise_for_status(self):
            if self.status_code >= 400 and not (500 <= self.status_code < 600):
                raise httpx.HTTPStatusError("error", request=None, response=None)

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None):
            self.calls += 1
            if self.calls <= 2:
                return DummyResp(500)
            return DummyResp(200)

    fake = FakeClient()
    monkeypatch.setattr("mcp_server.httpx.AsyncClient", lambda *a, **k: fake)

    comments = await fetch_pr_comments("o", "r", 4)
    assert len(comments) == 1
    assert fake.calls == 3


@pytest.mark.asyncio
async def test_fetch_pr_comments_retries_on_request_error(monkeypatch):
    # First request raises RequestError, second succeeds
    class DummyResp:
        def __init__(self):
            self.status_code = 200
            self.headers = {}

        def json(self):
            return [{"id": 1}]

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None):
            self.calls += 1
            if self.calls == 1:
                raise httpx.RequestError("boom", request=None)
            return DummyResp()

    fake = FakeClient()
    monkeypatch.setattr("mcp_server.httpx.AsyncClient", lambda *a, **k: fake)

    await fetch_pr_comments("o", "r", 5)


@pytest.mark.asyncio
async def test_fetch_pr_comments_overrides_and_clamping(monkeypatch):
    # Verify per-call overrides are accepted and clamped to safe ranges
    captured_urls = []

    class DummyResp:
        def __init__(self, link_next=None):
            self.status_code = 200
            self.headers = {}
            if link_next:
                self.headers["Link"] = link_next

        def json(self):
            return [{"id": 1}]

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None):
            captured_urls.append(url)
            self.calls += 1
            # Only one page
            return DummyResp(link_next=None)

    monkeypatch.setattr("mcp_server.httpx.AsyncClient", lambda *a, **k: FakeClient())

    # per_page > 100 should clamp to 100; max_retries>10 clamps to 10;
    # others just ensure no error
    comments = await fetch_pr_comments(
        "o",
        "r",
        8,
        per_page=1000,
        max_pages=9999,
        max_comments=999999,
        max_retries=999,
    )
    assert isinstance(comments, list)
    assert captured_urls and "per_page=100" in captured_urls[0]


@pytest.mark.asyncio
async def test_handle_call_tool_param_validation(server):
    # per_page too low
    with pytest.raises(ValueError):
        await server.handle_call_tool(
            "fetch_pr_review_comments",
            {"pr_url": "https://github.com/owner/repo/pull/1", "per_page": 0},
        )
    # max_comments too low (min 100)
    with pytest.raises(ValueError):
        await server.handle_call_tool(
            "fetch_pr_review_comments",
            {"pr_url": "https://github.com/owner/repo/pull/1", "max_comments": 50},
        )
    # wrong type
    with pytest.raises(ValueError):
        await server.handle_call_tool(
            "fetch_pr_review_comments",
            {"pr_url": "https://github.com/owner/repo/pull/1", "max_retries": "3"},
        )


@pytest.mark.asyncio
async def test_fetch_pr_comments_respects_env_page_cap(monkeypatch):
    class DummyResp:
        def __init__(self):
            self.status_code = 200
            self.headers = {"Link": '<https://next>; rel="next"'}

        def json(self):
            return [{"id": 1}]

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None):
            self.calls += 1
            return DummyResp()

    fake = FakeClient()
    monkeypatch.setattr("mcp_server.httpx.AsyncClient", lambda *a, **k: fake)
    monkeypatch.setenv("PR_FETCH_MAX_PAGES", "3")

    comments = await fetch_pr_comments("o", "r", 6)
    assert len(comments) == 3
    assert fake.calls == 3


@pytest.mark.asyncio
async def test_fetch_pr_comments_respects_env_retry_cap(monkeypatch):
    class DummyResp:
        def __init__(self, status):
            self.status_code = status
            self.headers = {}

        def json(self):
            return []

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("error", request=None, response=None)

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None):
            self.calls += 1
            return DummyResp(500)

    fake = FakeClient()
    monkeypatch.setattr("mcp_server.httpx.AsyncClient", lambda *a, **k: fake)
    monkeypatch.setenv("HTTP_MAX_RETRIES", "1")

    comments = await fetch_pr_comments("o", "r", 7)
    # One retry then fail -> returns None, 2 calls total
    assert comments is None or isinstance(comments, list) and len(comments) == 0
    assert fake.calls == 2
