"""Compatibility wrapper for the legacy module path."""

from mcp_github_pr_review_spec_maker.server import *  # noqa: F401,F403

if __name__ == "__main__":  # pragma: no cover
    from mcp_github_pr_review_spec_maker.cli import main

    raise SystemExit(main())
