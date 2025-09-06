import logging
import os
import re
import shlex
import sys
from dataclasses import dataclass

import httpx
from dulwich import porcelain
from dulwich.config import StackedConfig
from dulwich.errors import NotGitRepository
from dulwich.repo import Repo

logger = logging.getLogger(__name__)


def validate_repo_params(owner: str, repo: str, branch: str | None) -> None:
    """Validate repo parameters against injection and malformed input."""
    # Pattern allows alphanumeric, dots, underscores, and hyphens, length 1-100
    pattern = re.compile(r"^[a-zA-Z0-9._-]{1,100}$")

    for param, name in [(owner, "owner"), (repo, "repo")]:
        if not param or not pattern.match(param):
            raise ValueError(f"Invalid {name}: must be 1-100 characters and contain only alphanumeric, '.', '_', or '-'")

    # Branch names can also contain slashes (for feature branches like feature/xyz)
    if branch:
        branch_pattern = re.compile(r"^[a-zA-Z0-9._/-]+$")
        if not branch_pattern.match(branch):
            raise ValueError("Invalid branch name: contains illegal characters")


@dataclass
class GitContext:
    host: str
    owner: str
    repo: str
    branch: str


REMOTE_REGEXES = [
    # SSH: git@github.com:owner/repo.git
    re.compile(
        r"^(?:git@)(?P<host>[^:]+):(?P<owner>[^/]+)/(?P<repo>[^/.]+)(?:\.git)?$"
    ),
    # HTTPS: https://github.com/owner/repo(.git)
    re.compile(
        r"^https?://(?P<host>[^/]+)/(?P<owner>[^/]+)/(?P<repo>[^/.]+)(?:\.git)?/?$"
    ),
]


def parse_remote_url(url: str) -> tuple[str, str, str]:
    for rx in REMOTE_REGEXES:
        m = rx.match(url)
        if m:
            host = m.group("host")
            owner = m.group("owner")
            repo = m.group("repo")
            return host, owner, repo
    raise ValueError(f"Unsupported remote URL: {url}")


def _get_repo(cwd: str | None = None) -> Repo:
    path = cwd or os.getcwd()
    try:
        return Repo.discover(path)
    except NotGitRepository as e:
        raise ValueError("Not a git repository (dulwich discover failed)") from e


def git_detect_repo_branch(cwd: str | None = None) -> GitContext:
    # Env overrides are useful in CI/agents
    env_owner = os.getenv("MCP_PR_OWNER")
    env_repo = os.getenv("MCP_PR_REPO")
    env_branch = os.getenv("MCP_PR_BRANCH")
    if env_owner and env_repo and env_branch:
        host = os.getenv("GH_HOST", "github.com")
        return GitContext(host=host, owner=env_owner, repo=env_repo, branch=env_branch)

    # Discover via dulwich when not overridden
    repo_obj = _get_repo(cwd)

    # Remote URL: prefer 'origin'
    cfg: StackedConfig = repo_obj.get_config()
    remote_url_b: bytes | None = None
    try:
        remote_url_b = cfg.get((b"remote", b"origin"), b"url")
    except KeyError:
        # Fallback: first remote
        for sect in cfg.sections():
            if sect and sect[0] == b"remote" and len(sect) > 1:
                try:
                    remote_url_b = cfg.get(sect, b"url")
                    break
                except KeyError:
                    continue
    if not remote_url_b:
        raise ValueError("No git remote configured")
    remote_url = remote_url_b.decode("utf-8", errors="ignore")
    host, owner, repo = parse_remote_url(remote_url)

    # Current branch
    head_ref = repo_obj.refs.read_ref(b"HEAD")
    branch = None
    if head_ref and head_ref.startswith(b"refs/heads/"):
        branch = head_ref.split(b"/", 2)[-1].decode("utf-8", errors="ignore")
    else:
        # Detached HEAD: attempt porcelain.active_branch
        try:
            branch = porcelain.active_branch(repo_obj).decode("utf-8", errors="ignore")
        except (KeyError, ValueError, AttributeError) as e:
            logger.debug("Branch detection failed: %s", e)
            branch = None
    if not branch:
        raise ValueError("Unable to determine current branch")

    return GitContext(host=host, owner=owner, repo=repo, branch=branch)


def api_base_for_host(host: str) -> str:
    # Explicit override takes precedence (e.g., GHES custom URL)
    explicit = os.getenv("GITHUB_API_URL")
    if explicit:
        return explicit.rstrip("/")
    if host.lower() == "github.com":
        return "https://api.github.com"
    # GitHub Enterprise default pattern
    return f"https://{host}/api/v3"


async def resolve_pr_url(
    owner: str,
    repo: str,
    branch: str | None = None,
    *,
    select_strategy: str = "branch",
    host: str | None = None,
    token: str | None = None,
) -> str:
    """Resolve a PR HTML URL for an open PR.

    Strategies:
      - branch: pick PR with head.ref == branch; error if none
      - latest: most recently updated open PR
      - first: numerically smallest PR among open PRs
      - error: require exact branch match only
    """
    if select_strategy not in {"branch", "latest", "first", "error"}:
        raise ValueError("Invalid select_strategy")

    actual_host = host or os.getenv("GH_HOST", "github.com")
    api_base = api_base_for_host(actual_host)
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "mcp-pr-review-spec-maker/1.0",
    }
    token = token or os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    timeout = httpx.Timeout(timeout=20.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        pr_candidates = []
        # Prefer branch match first when strategy allows
        if branch and select_strategy in {"branch", "error"}:
            # First try GraphQL for headRefName match (more reliable across forks)
            try:
                pr_num = await _graphql_find_pr_number(
                    client, actual_host, headers, owner, repo, branch
                )
                if pr_num is not None:
                    return _html_pr_url(actual_host, owner, repo, pr_num)
            except Exception as e:  # noqa: BLE001
                # Fall back to REST below; optionally log for debugging
                if os.getenv("DEBUG_GITHUB_PR_RESOLVER"):
                    print(f"GraphQL lookup failed: {e}", file=sys.stderr)

            # Fallback REST: filter by head=owner:branch
            head_param = f"{owner}:{branch}"
            url = (
                f"{api_base}/repos/{owner}/{repo}/pulls"
                f"?state=open&head={shlex.quote(head_param)}"
            )
            r = await client.get(url, headers=headers)
            # If unauthorized or rate-limited, surface as a clear error
            r.raise_for_status()
            data = r.json()
            if data:
                pr = data[0]
                return pr.get("html_url") or pr.get("url")
            if select_strategy == "error":
                raise ValueError(
                    f"No open PR found for branch '{branch}' in {owner}/{repo}"
                )

        # Fallback list of open PRs
        url = (
            f"{api_base}/repos/{owner}/{repo}/pulls"
            "?state=open&sort=updated&direction=desc"
        )
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        pr_candidates = r.json() or []

        if not pr_candidates:
            branch_info = f" (current branch: {branch})" if branch else ""
            raise ValueError(f"No open PRs found for {owner}/{repo}{branch_info}")

        if select_strategy == "branch" and branch:
            for pr in pr_candidates:
                if pr.get("head", {}).get("ref") == branch:
                    return pr.get("html_url") or pr.get("url")
            raise ValueError(
                f"No open PR found for branch '{branch}' in {owner}/{repo}"
            )

        if select_strategy == "latest":
            pr = pr_candidates[0]
            return pr.get("html_url") or pr.get("url")

        if select_strategy == "first":
            # Choose numerically smallest PR number
            pr = min(pr_candidates, key=lambda p: int(p.get("number", 1 << 30)))
            return pr.get("html_url") or pr.get("url")


def _graphql_url_for_host(host: str) -> str:
    # Explicit override takes precedence when it targets the same host.
    # In some CI environments (e.g., GitHub Actions), GITHUB_GRAPHQL_URL may be
    # set for github.com. Ignore it for non-matching enterprise hosts.
    explicit = os.getenv("GITHUB_GRAPHQL_URL")
    if explicit:
        from urllib.parse import urlparse

        parsed = urlparse(explicit)
        api_host = (parsed.netloc or "").lower()

        def _hosts_match(target_host: str, env_api_host: str) -> bool:
            # Treat api.github.com and github.com as equivalent for dotcom
            if target_host.lower() == "github.com":
                return env_api_host in {"api.github.com", "github.com"}
            return env_api_host == target_host.lower()

        if api_host and _hosts_match(host, api_host):
            return explicit.rstrip("/")
    # If an explicit REST base is set, try to infer GraphQL endpoint
    explicit_rest = os.getenv("GITHUB_API_URL")
    if explicit_rest:
        # Common forms:
        #  - https://ghe.example/api/v3 -> https://ghe.example/api/graphql
        #  - https://ghe.example/api     -> https://ghe.example/api/graphql
        base = explicit_rest.rstrip("/")
        if base.endswith("/api/v3"):
            return base[: -len("/api/v3")] + "/api/graphql"
        if base.endswith("/api"):
            return base + "/graphql"
        # Fallback: append /graphql
        return base + "/graphql"
    # GitHub.com and GHES defaults
    if host.lower() == "github.com":
        return "https://api.github.com/graphql"
    return f"https://{host}/api/graphql"


def _html_pr_url(host: str, owner: str, repo: str, number: int) -> str:
    return f"https://{host}/{owner}/{repo}/pull/{number}"


async def _graphql_find_pr_number(
    client: httpx.AsyncClient,
    host: str,
    headers: dict,
    owner: str,
    repo: str,
    branch: str,
) -> int | None:
    # Validate input parameters before building GraphQL query
    validate_repo_params(owner, repo, branch)

    # Build GraphQL request
    graphql_url = _graphql_url_for_host(host)
    # Ensure we have auth for GraphQL; otherwise likely 401
    if "Authorization" not in headers:
        # Attempt token from env
        token = os.getenv("GITHUB_TOKEN")
        if token:
            headers = {**headers, "Authorization": f"Bearer {token}"}
    query = {
        "query": (
            "query($owner: String!, $repo: String!, $branchName: String!) {"
            "  repository(owner: $owner, name: $repo) {"
            "    pullRequests(first: 10, states: [OPEN], headRefName: $branchName) {"
            "      nodes { number headRefName state }"
            "    }"
            "  }"
            "}"
        ),
        "variables": {"owner": owner, "repo": repo, "branchName": branch},
    }
    resp = await client.post(graphql_url, json=query, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        return None
    if data.get("errors"):
        return None
    nodes = (
        data.get("data", {})
        .get("repository", {})
        .get("pullRequests", {})
        .get("nodes", [])
    )
    # The query already filters by headRefName and OPEN state; pick first match
    if nodes:
        try:
            return int(nodes[0].get("number"))
        except Exception:
            return None
    return None
