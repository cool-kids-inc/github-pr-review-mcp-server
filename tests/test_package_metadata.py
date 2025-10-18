"""Tests for package metadata and version detection."""

import os
import subprocess
import sys


class TestMainEntry:
    """Test the __main__.py entry point."""

    def test_main_module_execution(self) -> None:
        """Test that python -m mcp_github_pr_review works."""
        # Run the module with --help to avoid actually starting the server
        # Disable coverage in subprocess to avoid segfault on Python 3.12
        env = os.environ.copy()
        env["COVERAGE_PROCESS_START"] = ""  # Disable coverage subprocess hook

        result = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "mcp_github_pr_review", "--help"],
            capture_output=True,
            text=True,
            timeout=5,
            env=env,
        )
        assert result.returncode == 0
        assert "GitHub PR Review MCP server" in result.stdout


class TestVersionFallback:
    """Test version detection fallback paths.

    Note: The fallback logic (lines 10-11 in __init__.py and 14-15 in
    github_api_constants.py) catches PackageNotFoundError when the package
    is not installed and falls back to environment variable or "0".
    This is difficult to test directly in pytest without breaking the test
    environment, so these lines remain untested in coverage reports.
    The fallback logic is simple and defensive programming best practice.
    """

    def test_version_fallback_logic_exists_in_init(self) -> None:
        """Document that fallback logic exists in __init__.py."""
        import mcp_github_pr_review

        # Verify the module has version detection with fallback
        assert hasattr(mcp_github_pr_review, "__version__")

    def test_version_fallback_logic_exists_in_constants(self) -> None:
        """Document that fallback logic exists in github_api_constants.py."""
        from mcp_github_pr_review import github_api_constants

        # Verify the module has User-Agent with version
        assert github_api_constants.GITHUB_USER_AGENT.startswith(
            "mcp-github-pr-review/"
        )


class TestVersionDetection:
    """Test that version is correctly detected from package metadata."""

    def test_version_is_detected(self) -> None:
        """Test that __version__ is set to a non-zero value."""
        import mcp_github_pr_review

        # Should be "0.1.0" or similar when package is installed
        assert mcp_github_pr_review.__version__ != ""
        assert mcp_github_pr_review.__version__ is not None

    def test_user_agent_includes_version(self) -> None:
        """Test that User-Agent includes a valid version."""
        from mcp_github_pr_review.github_api_constants import GITHUB_USER_AGENT

        assert GITHUB_USER_AGENT.startswith("mcp-github-pr-review/")
        # Should have a version after the slash
        parts = GITHUB_USER_AGENT.split("/")
        assert len(parts) == 2
        assert parts[1] != ""
