"""Compatibility wrapper for the legacy module path."""

import warnings

warnings.warn(
    "mcp_server is deprecated; import from mcp_github_pr_review.server instead.",
    DeprecationWarning,
    stacklevel=2,
)

from mcp_github_pr_review.server import *  # noqa: F401,F403

if __name__ == "__main__":  # pragma: no cover
    from mcp_github_pr_review.cli import main

    raise SystemExit(main())
