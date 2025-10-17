"""GitHub API constants shared across modules."""

import os
from importlib.metadata import PackageNotFoundError, version

# GitHub API headers (modern, versioned format)
GITHUB_ACCEPT_HEADER = "application/vnd.github+json"
GITHUB_API_VERSION = "2022-11-28"

# Dynamic User-Agent with package version
_UA_NAME = "mcp-github-pr-review"
try:
    _pkg_ver = version("mcp_github_pr_review")
except PackageNotFoundError:
    _pkg_ver = os.getenv("PACKAGE_VERSION", "0")
GITHUB_USER_AGENT = f"{_UA_NAME}/{_pkg_ver}"
