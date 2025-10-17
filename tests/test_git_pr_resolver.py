import httpx
import pytest
from conftest import (
    DummyResp,
    FakeClient,
    assert_auth_header_present,
    create_mock_response,
)

from mcp_github_pr_review.git_pr_resolver import (
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
    # Ensure no global override interferes with default behavior
    monkeypatch.delenv("GITHUB_API_URL", raising=False)
    assert api_base_for_host("github.mycorp.com") == "https://github.mycorp.com/api/v3"

    # When override is present and host matches, it should take precedence
    monkeypatch.setenv("GITHUB_API_URL", "https://ghe.example/api/v3/")
    assert api_base_for_host("ghe.example") == "https://ghe.example/api/v3"

    # When override is present but host doesn't match, use default pattern
    assert api_base_for_host("other.host") == "https://other.host/api/v3"


def test_git_detect_repo_branch_env_override(monkeypatch):
    monkeypatch.setenv("MCP_PR_OWNER", "o")
    monkeypatch.setenv("MCP_PR_REPO", "r")
    monkeypatch.setenv("MCP_PR_BRANCH", "b")
    ctx = git_detect_repo_branch()
    assert ctx.owner == "o" and ctx.repo == "r" and ctx.branch == "b"


@pytest.mark.asyncio
async def test_resolve_pr_url_branch_strategy(monkeypatch):
    class BranchStrategyFakeClient(FakeClient):
        async def get(self, url, headers=None):
            if "head=o:branch" in url:
                return DummyResp(
                    [{"html_url": "https://github.com/o/r/pull/1", "number": 1}]
                )
            return DummyResp([])

    monkeypatch.setattr(
        "mcp_github_pr_review.git_pr_resolver.httpx.AsyncClient",
        lambda *a, **k: BranchStrategyFakeClient(*a, **k),
    )

    url = await resolve_pr_url("o", "r", branch="branch", select_strategy="branch")
    assert url.endswith("/pull/1")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "branch_name, encoded_branch_part",
    [
        ("feature/fix", "feature%2Ffix"),
        ("bug#123", "bug%23123"),
        ("a+b", "a%2Bb"),
        ("a b", "a%20b"),
    ],
)
async def test_resolve_pr_url_encodes_head_param(
    monkeypatch, mock_http_client, branch_name, encoded_branch_part
) -> None:
    async def fake_graphql(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(
        "mcp_github_pr_review.git_pr_resolver._graphql_find_pr_number", fake_graphql
    )
    mock_http_client.add_get_response(
        create_mock_response([{"html_url": "https://github.com/o/r/pull/99"}])
    )
    url = await resolve_pr_url("o", "r", branch=branch_name, select_strategy="branch")
    assert url.endswith("/pull/99")

    assert mock_http_client.get_calls, "GET request was not made"
    requested_url = mock_http_client.get_calls[0][0]
    assert f"head=o:{branch_name}" not in requested_url
    assert f"head=o:{encoded_branch_part}" in requested_url


@pytest.mark.asyncio
async def test_resolve_pr_url_uses_follow_redirects(monkeypatch):
    # This test only needs to verify the follow_redirects assertion
    # The shared FakeClient already includes this check
    monkeypatch.setattr(
        "mcp_github_pr_review.git_pr_resolver.httpx.AsyncClient",
        lambda *a, **k: FakeClient(*a, **k),
    )

    # The test passes if no assertion error is raised during client creation
    # We can call resolve_pr_url to trigger the client creation
    result = await resolve_pr_url("owner", "repo", select_strategy="latest")
    assert result.endswith("/pull/456")


def test_parse_remote_url_edge_cases() -> None:
    """Test edge cases for remote URL parsing with various Git URL formats.

    Tests different URL formats that might be encountered in real-world
    scenarios, including URLs with trailing slashes.
    """
    # Test cases that should parse successfully: (input_url, expected_result)
    success_cases = [
        (
            "https://github.com/owner/repo/",
            ("github.com", "owner", "repo"),
        ),  # URL with trailing slash
        (
            "https://github.com/owner/my.repo.name",
            ("github.com", "owner", "my.repo.name"),
        ),  # Repository name with dots
        (
            "  https://github.com/owner/repo.git  \n",
            ("github.com", "owner", "repo"),
        ),  # Surrounding whitespace and newline
        (
            "\tgit@github.com:owner/repo.git\t",
            ("github.com", "owner", "repo"),
        ),  # SSH URL with surrounding tabs
    ]

    for url, expected in success_cases:
        result = parse_remote_url(url)
        assert result == expected, (
            f"Failed to parse {url} correctly: got {result}, expected {expected}"
        )


def test_parse_remote_url_unsupported_formats() -> None:
    """Test that unsupported URL formats raise appropriate exceptions."""
    # Test cases that should raise ValueError: (input_url, expected_exception)
    failure_cases = [
        "ssh://git@github.com/owner/repo.git",  # ssh:// prefix not supported
        "git://github.com/owner/repo.git",  # git:// protocol not supported
        "invalid-url",  # Completely invalid format
    ]

    for url in failure_cases:
        with pytest.raises(ValueError, match="Unsupported remote URL"):
            parse_remote_url(url)


@pytest.mark.asyncio
async def test_resolve_pr_url_no_branch(monkeypatch) -> None:
    """Test PR resolution without specifying a branch using latest strategy.

    Verifies that the resolve_pr_url function can successfully find and return
    a PR URL when no specific branch is provided, using the 'latest' selection
    strategy to find the most recent open PR.
    """

    # Patch the httpx.AsyncClient to use our shared mock
    monkeypatch.setattr(
        "mcp_github_pr_review.git_pr_resolver.httpx.AsyncClient",
        lambda *a, **k: FakeClient(*a, **k),
    )

    # Test that latest strategy works when no branch is specified
    result = await resolve_pr_url("owner", "repo", select_strategy="latest")
    assert "pull/456" in result, f"Expected PR URL to contain 'pull/456', got: {result}"


def test_api_base_for_host_host_matching(monkeypatch) -> None:
    """Test that GITHUB_API_URL only applies when host matches.

    Verifies the host-matching logic prevents incorrect routing in multi-host
    environments (e.g., working with both github.com and GHES).
    """
    # Test 1: GITHUB_API_URL with github.com should match github.com
    monkeypatch.setenv("GITHUB_API_URL", "https://github.com/custom")
    assert api_base_for_host("github.com") == "https://github.com/custom"

    # Test 2: GITHUB_API_URL with api.github.com should match github.com
    # (api.github.com and github.com are treated as equivalent)
    monkeypatch.setenv("GITHUB_API_URL", "https://api.github.com/custom")
    assert api_base_for_host("github.com") == "https://api.github.com/custom"

    # Test 3: GITHUB_API_URL set for GHES shouldn't affect github.com calls
    monkeypatch.setenv("GITHUB_API_URL", "https://ghe.mycorp.com/api/v3")
    assert api_base_for_host("github.com") == "https://api.github.com"

    # Test 4: GITHUB_API_URL set for GHES should only match that GHES host
    assert api_base_for_host("ghe.mycorp.com") == "https://ghe.mycorp.com/api/v3"

    # Test 5: Different GHES host should use default pattern
    assert api_base_for_host("other.ghes.com") == "https://other.ghes.com/api/v3"


def test_api_base_for_host_edge_cases(monkeypatch) -> None:
    """Test edge cases for API base URL construction with various host formats.

    Verifies that the api_base_for_host function correctly constructs API base URLs
    for different types of GitHub Enterprise and custom Git hosting environments.
    """
    # Ensure no environment variable override interferes with our tests
    monkeypatch.delenv("GITHUB_API_URL", raising=False)

    # Test various enterprise and custom Git hosting hostnames
    test_hosts = [
        "github.enterprise.com",  # Standard GitHub Enterprise
        "git.mycompany.com",  # Custom company Git server
        "source.internal.com",  # Internal Git hosting
    ]

    for host in test_hosts:
        result = api_base_for_host(host)

        # Verify the constructed URL has the expected components
        assert result.startswith("https://"), f"API URL should use HTTPS: {result}"
        assert "/api/v3" in result, f"API URL should include /api/v3 path: {result}"
        assert host in result, f"API URL should contain the hostname: {result}"


@pytest.mark.asyncio
async def test_resolve_pr_url_uses_auth_header(
    mock_http_client, github_token: str
) -> None:
    """resolve_pr_url should send Authorization header when token is set."""
    mock_http_client.add_get_response(
        create_mock_response(
            [
                {
                    "number": 1,
                    "html_url": "https://github.com/owner/repo/pull/1",
                }
            ]
        )
    )

    url = await resolve_pr_url("owner", "repo", select_strategy="latest")
    assert url == "https://github.com/owner/repo/pull/1"

    assert_auth_header_present(mock_http_client, github_token)


# Test error conditions and edge cases that are currently not covered


def test_get_repo_not_git_repository(monkeypatch, temp_dir):
    """Test _get_repo raises ValueError when not in a git repository."""
    from mcp_github_pr_review.git_pr_resolver import _get_repo

    # Test with a directory that is not a git repository
    with pytest.raises(ValueError, match="Not a git repository"):
        _get_repo(str(temp_dir))


@pytest.mark.asyncio
async def test_resolve_pr_url_invalid_strategy():
    """Test resolve_pr_url raises ValueError for invalid selection strategy."""
    with pytest.raises(ValueError, match="Invalid select_strategy"):
        await resolve_pr_url("owner", "repo", select_strategy="invalid")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "strategy,branch,should_error",
    [
        ("error", "feature-branch", False),  # Should work with branch
        ("error", None, True),  # Should error without branch
        ("branch", None, True),  # Should error without branch
    ],
)
async def test_resolve_pr_url_branch_requirements(
    monkeypatch, strategy, branch, should_error
):
    """Test that certain strategies require branch parameter."""
    monkeypatch.setattr(
        "mcp_github_pr_review.git_pr_resolver.httpx.AsyncClient",
        lambda *a, **k: FakeClient(*a, **k),
    )

    if should_error:
        with pytest.raises(ValueError):
            await resolve_pr_url(
                "owner", "repo", branch=branch, select_strategy=strategy
            )
    else:
        # Should not raise an error
        try:
            await resolve_pr_url(
                "owner", "repo", branch=branch, select_strategy=strategy
            )
        except ValueError as e:
            # Allow specific branch not found errors, but not parameter errors
            if "requires a branch name" in str(e):
                pytest.fail(
                    f"Unexpected error for {strategy} with branch {branch}: {e}"
                )


@pytest.mark.asyncio
async def test_resolve_pr_url_no_open_prs(monkeypatch):
    """Test resolve_pr_url behavior when no open PRs are found."""

    class NoOpenPRsClient(FakeClient):
        async def get(self, url, headers=None):
            return DummyResp([])  # Empty list simulates no open PRs

    monkeypatch.setattr(
        "mcp_github_pr_review.git_pr_resolver.httpx.AsyncClient",
        lambda *a, **k: NoOpenPRsClient(*a, **k),
    )

    with pytest.raises(ValueError, match="No open PRs found"):
        await resolve_pr_url("owner", "repo", select_strategy="latest")


@pytest.mark.asyncio
async def test_resolve_pr_url_fallback_url_builder(monkeypatch):
    """Test fallback URL builder when html_url/url are missing from API response."""

    class NoUrlFieldsClient(FakeClient):
        async def get(self, url, headers=None):
            return DummyResp([{"number": 42}])  # Missing html_url and url fields

    monkeypatch.setattr(
        "mcp_github_pr_review.git_pr_resolver.httpx.AsyncClient",
        lambda *a, **k: NoUrlFieldsClient(*a, **k),
    )

    url = await resolve_pr_url("owner", "repo", select_strategy="latest")
    assert "pull/42" in url
    assert "github.com/owner/repo" in url


@pytest.mark.asyncio
async def test_resolve_pr_url_fallback_url_builder_invalid_number(monkeypatch):
    """Test fallback URL builder handles invalid PR numbers gracefully."""

    class InvalidNumberClient(FakeClient):
        async def get(self, url, headers=None):
            return DummyResp([{"number": "not-a-number"}])

    monkeypatch.setattr(
        "mcp_github_pr_review.git_pr_resolver.httpx.AsyncClient",
        lambda *a, **k: InvalidNumberClient(*a, **k),
    )

    url = await resolve_pr_url("owner", "repo", select_strategy="latest")
    assert "pull/unknown" in url


@pytest.mark.asyncio
async def test_resolve_pr_url_first_strategy_selects_lowest_number(monkeypatch):
    """Test 'first' strategy selects PR with lowest number."""

    class MultiPRClient(FakeClient):
        async def get(self, url, headers=None):
            return DummyResp(
                [
                    {"number": 100, "html_url": "https://github.com/o/r/pull/100"},
                    {"number": 50, "html_url": "https://github.com/o/r/pull/50"},
                    {"number": 200, "html_url": "https://github.com/o/r/pull/200"},
                ]
            )

    monkeypatch.setattr(
        "mcp_github_pr_review.git_pr_resolver.httpx.AsyncClient",
        lambda *a, **k: MultiPRClient(*a, **k),
    )

    url = await resolve_pr_url("owner", "repo", select_strategy="first")
    assert "pull/50" in url


def test_git_detect_repo_branch_fallback_remote_logic(monkeypatch):
    """Test git_detect_repo_branch fallback remote selection logic."""
    from unittest.mock import Mock

    from mcp_github_pr_review.git_pr_resolver import git_detect_repo_branch

    # Ensure no env overrides
    for var in ["MCP_PR_OWNER", "MCP_PR_REPO", "MCP_PR_BRANCH"]:
        monkeypatch.delenv(var, raising=False)

    # Create a mock repo that simulates fallback remote behavior
    mock_repo = Mock()
    mock_config = Mock()

    # Simulate that origin remote is not found (KeyError)
    def config_get(section, key):
        if section == (b"remote", b"origin") and key == b"url":
            raise KeyError("origin not found")
        elif section == (b"remote", b"upstream") and key == b"url":
            return b"https://github.com/test/repo.git"
        raise KeyError("key not found")

    # Simulate config.sections() returning upstream remote
    mock_config.get.side_effect = config_get
    mock_config.sections.return_value = [(b"remote", b"upstream")]
    mock_repo.get_config.return_value = mock_config

    # Mock branch detection
    mock_repo.refs.read_ref.return_value = b"refs/heads/test-branch"

    # Mock _get_repo to return our mock
    monkeypatch.setattr(
        "mcp_github_pr_review.git_pr_resolver._get_repo", lambda cwd: mock_repo
    )

    # This should succeed using the fallback remote
    ctx = git_detect_repo_branch()
    assert ctx.owner == "test" and ctx.repo == "repo" and ctx.branch == "test-branch"


def test_git_detect_repo_branch_no_remote_configured(monkeypatch):
    """Test git_detect_repo_branch raises error when no remotes configured."""
    from unittest.mock import Mock

    from mcp_github_pr_review.git_pr_resolver import git_detect_repo_branch

    # Ensure no env overrides
    for var in ["MCP_PR_OWNER", "MCP_PR_REPO", "MCP_PR_BRANCH"]:
        monkeypatch.delenv(var, raising=False)

    # Create a mock repo with no remotes
    mock_repo = Mock()
    mock_config = Mock()
    mock_config.get.side_effect = KeyError("no remotes")
    mock_config.sections.return_value = []  # No remote sections
    mock_repo.get_config.return_value = mock_config

    monkeypatch.setattr(
        "mcp_github_pr_review.git_pr_resolver._get_repo", lambda cwd: mock_repo
    )

    with pytest.raises(ValueError, match="No git remote configured"):
        git_detect_repo_branch()


def test_git_detect_repo_branch_detached_head_fallback(monkeypatch):
    """Test git_detect_repo_branch handles detached HEAD using active_branch."""
    from unittest.mock import Mock

    from mcp_github_pr_review.git_pr_resolver import git_detect_repo_branch

    # Ensure no env overrides
    for var in ["MCP_PR_OWNER", "MCP_PR_REPO", "MCP_PR_BRANCH"]:
        monkeypatch.delenv(var, raising=False)

    # Mock repo with origin remote
    mock_repo = Mock()
    mock_config = Mock()
    mock_config.get.return_value = b"https://github.com/test/repo.git"
    mock_repo.get_config.return_value = mock_config

    # Simulate detached HEAD (not starting with refs/heads/)
    mock_repo.refs.read_ref.return_value = b"abc123"  # Raw commit hash

    # Mock porcelain.active_branch to return a branch name
    def mock_active_branch(repo):
        return b"feature-branch"

    monkeypatch.setattr(
        "mcp_github_pr_review.git_pr_resolver.porcelain.active_branch",
        mock_active_branch,
    )
    monkeypatch.setattr(
        "mcp_github_pr_review.git_pr_resolver._get_repo", lambda cwd: mock_repo
    )

    ctx = git_detect_repo_branch()
    assert ctx.owner == "test" and ctx.repo == "repo" and ctx.branch == "feature-branch"


def test_git_detect_repo_branch_detached_head_no_branch(monkeypatch):
    """Test git_detect_repo_branch raises error when can't determine branch."""
    from unittest.mock import Mock

    from mcp_github_pr_review.git_pr_resolver import git_detect_repo_branch

    # Ensure no env overrides
    for var in ["MCP_PR_OWNER", "MCP_PR_REPO", "MCP_PR_BRANCH"]:
        monkeypatch.delenv(var, raising=False)

    # Mock repo with origin remote
    mock_repo = Mock()
    mock_config = Mock()
    mock_config.get.return_value = b"https://github.com/test/repo.git"
    mock_repo.get_config.return_value = mock_config

    # Simulate detached HEAD
    mock_repo.refs.read_ref.return_value = b"abc123"  # Raw commit hash

    # Mock porcelain.active_branch to fail
    def mock_active_branch_fail(repo):
        raise ValueError("Cannot determine active branch")

    monkeypatch.setattr(
        "mcp_github_pr_review.git_pr_resolver.porcelain.active_branch",
        mock_active_branch_fail,
    )
    monkeypatch.setattr(
        "mcp_github_pr_review.git_pr_resolver._get_repo", lambda cwd: mock_repo
    )

    with pytest.raises(ValueError, match="Unable to determine current branch"):
        git_detect_repo_branch()


@pytest.mark.asyncio
async def test_graphql_find_pr_number_error_handling(monkeypatch):
    """Test _graphql_find_pr_number handles various error conditions."""
    from mcp_github_pr_review.git_pr_resolver import _graphql_find_pr_number

    class ErrorClient:
        async def post(self, url, json=None, headers=None):
            # Test different error response formats
            return DummyResp({"errors": ["GraphQL error"]})

    client = ErrorClient()
    result = await _graphql_find_pr_number(
        client,
        "github.com",
        {"Authorization": "Bearer token"},
        "owner",
        "repo",
        "branch",
    )
    assert result is None


@pytest.mark.asyncio
async def test_graphql_find_pr_number_malformed_response(monkeypatch):
    """Test _graphql_find_pr_number handles malformed GraphQL responses."""
    from mcp_github_pr_review.git_pr_resolver import _graphql_find_pr_number

    test_cases = [
        "not a dict",  # Non-dict response
        {},  # Missing data field
        {"data": "not a dict"},  # data is not dict
        {"data": {"repository": "not a dict"}},  # repository is not dict
        {
            "data": {"repository": {"pullRequests": "not a dict"}}
        },  # pullRequests is not dict
        {
            "data": {"repository": {"pullRequests": {"nodes": "not-a-list"}}}
        },  # nodes is not a list
        {
            "data": {"repository": {"pullRequests": {"nodes": [{"number": "not-int"}]}}}
        },  # Invalid number
    ]

    for test_response in test_cases:

        class MalformedResponseClient:
            def __init__(self, response):
                self.response = response

            async def post(self, url, json=None, headers=None):
                return DummyResp(self.response)

        client = MalformedResponseClient(test_response)
        result = await _graphql_find_pr_number(
            client,
            "github.com",
            {"Authorization": "Bearer token"},
            "owner",
            "repo",
            "branch",
        )
        assert result is None, f"Expected None for malformed response: {test_response}"


def test_graphql_url_for_host_enterprise_patterns(monkeypatch):
    """Test graphql_url_for_host constructs correct URLs for enterprise."""
    from mcp_github_pr_review.git_pr_resolver import graphql_url_for_host

    # Clear environment variables to test default behavior
    monkeypatch.delenv("GITHUB_GRAPHQL_URL", raising=False)
    monkeypatch.delenv("GITHUB_API_URL", raising=False)

    test_cases = [
        # (host, expected_url)
        ("github.com", "https://api.github.com/graphql"),
        ("ghe.example.com", "https://ghe.example.com/api/graphql"),
        ("custom.git.host", "https://custom.git.host/api/graphql"),
    ]

    for host, expected in test_cases:
        result = graphql_url_for_host(host)
        assert result == expected, f"Expected {expected}, got {result} for host {host}"


def test_graphql_url_for_host_with_api_url_env(monkeypatch):
    """Test graphql_url_for_host respects GITHUB_API_URL environment variable."""
    from mcp_github_pr_review.git_pr_resolver import graphql_url_for_host

    test_cases = [
        ("https://ghe.example/api/v3", "https://ghe.example/api/graphql"),
        ("https://ghe.example/api", "https://ghe.example/api/graphql"),
        ("https://custom.domain/some/path", "https://custom.domain/some/path/graphql"),
    ]

    for api_url, expected_graphql in test_cases:
        monkeypatch.setenv("GITHUB_API_URL", api_url)
        monkeypatch.delenv("GITHUB_GRAPHQL_URL", raising=False)

        result = graphql_url_for_host("any-host")
        assert result == expected_graphql, (
            f"Expected {expected_graphql}, got {result} for API URL {api_url}"
        )


def test_graphql_url_for_host_with_explicit_graphql_url(monkeypatch):
    """Test graphql_url_for_host uses explicit GITHUB_GRAPHQL_URL when hosts match."""
    from mcp_github_pr_review.git_pr_resolver import graphql_url_for_host

    # Test github.com equivalence (api.github.com should be treated as github.com)
    monkeypatch.setenv("GITHUB_GRAPHQL_URL", "https://api.github.com/graphql")
    result = graphql_url_for_host("github.com")
    assert result == "https://api.github.com/graphql"

    # Test exact host match
    monkeypatch.setenv("GITHUB_GRAPHQL_URL", "https://ghe.example.com/api/graphql")
    result = graphql_url_for_host("ghe.example.com")
    assert result == "https://ghe.example.com/api/graphql"

    # Test host mismatch (should ignore explicit URL)
    monkeypatch.setenv("GITHUB_GRAPHQL_URL", "https://wrong.host.com/graphql")
    result = graphql_url_for_host("github.com")
    # Should fall back to default since hosts don't match
    assert result == "https://api.github.com/graphql"


def test_html_pr_url_construction():
    """Test _html_pr_url correctly constructs PR URLs."""
    from mcp_github_pr_review.git_pr_resolver import _html_pr_url

    test_cases = [
        ("github.com", "owner", "repo", 123, "https://github.com/owner/repo/pull/123"),
        (
            "ghe.example.com",
            "org",
            "project",
            456,
            "https://ghe.example.com/org/project/pull/456",
        ),
    ]

    for host, owner, repo, number, expected in test_cases:
        result = _html_pr_url(host, owner, repo, number)
        assert result == expected, f"Expected {expected}, got {result}"


@pytest.mark.asyncio
async def test_graphql_find_pr_number_missing_auth_adds_token(monkeypatch):
    """Test _graphql_find_pr_number adds token when Authorization header missing."""
    from mcp_github_pr_review.git_pr_resolver import _graphql_find_pr_number

    monkeypatch.setenv("GITHUB_TOKEN", "env-token")

    class TokenCheckClient:
        def __init__(self):
            self.headers_received = None

        async def post(self, url, json=None, headers=None):
            self.headers_received = headers
            return DummyResp({"data": {"repository": {"pullRequests": {"nodes": []}}}})

    client = TokenCheckClient()
    headers_without_auth = {"User-Agent": "test"}

    await _graphql_find_pr_number(
        client, "github.com", headers_without_auth, "owner", "repo", "branch"
    )

    # Verify that Authorization header was added
    assert client.headers_received.get("Authorization") == "Bearer env-token"


@pytest.mark.asyncio
async def test_resolve_pr_url_debug_logging(monkeypatch, debug_logging_enabled):
    """Test debug logging when GraphQL lookup fails."""
    import sys
    from io import StringIO

    # Capture stderr to verify debug logging
    captured_stderr = StringIO()
    original_stderr = sys.stderr
    sys.stderr = captured_stderr

    try:

        class GraphQLFailClient(FakeClient):
            async def post(self, url, json=None, headers=None):
                request = httpx.Request("POST", url)
                raise httpx.RequestError("GraphQL connection failed", request=request)

        monkeypatch.setattr(
            "mcp_github_pr_review.git_pr_resolver.httpx.AsyncClient",
            lambda *a, **k: GraphQLFailClient(*a, **k),
        )

        # This should fall back to REST API but log the GraphQL failure
        await resolve_pr_url(
            "owner", "repo", branch="test-branch", select_strategy="branch"
        )

        # Check that debug message was logged
        stderr_content = captured_stderr.getvalue()
        assert "GraphQL lookup failed" in stderr_content

    finally:
        sys.stderr = original_stderr
