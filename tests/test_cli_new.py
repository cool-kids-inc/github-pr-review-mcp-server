"""Tests for the new Typer-based CLI interface."""

from __future__ import annotations

import pytest

# Check if CLI dependencies are available
pytest.importorskip("typer")
pytest.importorskip("rich")

from typer.testing import CliRunner  # noqa: E402

from mcp_github_pr_review.cli import app  # noqa: E402

runner = CliRunner()


class TestCLIBasics:
    """Test basic CLI functionality."""

    def test_cli_help(self) -> None:
        """Test that --help works."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "GitHub PR Review MCP Server" in result.stdout
        assert "config" in result.stdout
        assert "agents" in result.stdout
        assert "server" in result.stdout
        assert "doctor" in result.stdout
        assert "quickstart" in result.stdout

    def test_cli_version_short(self) -> None:
        """Test that -v shows version."""
        result = runner.invoke(app, ["-v"])
        assert result.exit_code == 0
        assert "mcp-github-pr version" in result.stdout

    def test_cli_version_long(self) -> None:
        """Test that --version shows version."""
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "mcp-github-pr version" in result.stdout

    def test_cli_no_args(self) -> None:
        """Test that running with no args shows help."""
        result = runner.invoke(app, [])
        # Typer exits with 2 when no_args_is_help=True and no args provided
        assert result.exit_code in (0, 2)
        assert "Usage:" in result.stdout


class TestConfigCommands:
    """Test config command group."""

    def test_config_help(self) -> None:
        """Test config --help."""
        result = runner.invoke(app, ["config", "--help"])
        assert result.exit_code == 0
        assert "Manage configuration files" in result.stdout

    def test_config_init_placeholder(self) -> None:
        """Test config init placeholder."""
        result = runner.invoke(app, ["config", "init"])
        assert result.exit_code == 0
        assert "Not yet implemented" in result.stdout

    def test_config_show_placeholder(self) -> None:
        """Test config show placeholder."""
        result = runner.invoke(app, ["config", "show"])
        assert result.exit_code == 0
        assert "Not yet implemented" in result.stdout

    def test_config_validate_placeholder(self) -> None:
        """Test config validate placeholder."""
        result = runner.invoke(app, ["config", "validate"])
        assert result.exit_code == 0
        assert "Not yet implemented" in result.stdout

    def test_config_migrate_placeholder(self) -> None:
        """Test config migrate placeholder."""
        result = runner.invoke(app, ["config", "migrate"])
        assert result.exit_code == 0
        assert "Not yet implemented" in result.stdout

    def test_config_edit_placeholder(self) -> None:
        """Test config edit placeholder."""
        result = runner.invoke(app, ["config", "edit"])
        assert result.exit_code == 0
        assert "Not yet implemented" in result.stdout

    def test_config_reset_placeholder(self) -> None:
        """Test config reset placeholder."""
        result = runner.invoke(app, ["config", "reset"])
        assert result.exit_code == 0
        assert "Not yet implemented" in result.stdout


class TestAgentsCommands:
    """Test agents command group."""

    def test_agents_help(self) -> None:
        """Test agents --help."""
        result = runner.invoke(app, ["agents", "--help"])
        assert result.exit_code == 0
        assert "Manage agent client integrations" in result.stdout

    def test_agents_list_placeholder(self) -> None:
        """Test agents list placeholder."""
        result = runner.invoke(app, ["agents", "list"])
        assert result.exit_code == 0
        assert "Not yet implemented" in result.stdout

    def test_agents_snippet_placeholder(self) -> None:
        """Test agents snippet placeholder."""
        result = runner.invoke(app, ["agents", "snippet"])
        assert result.exit_code == 0
        assert "Not yet implemented" in result.stdout

    def test_agents_verify_placeholder(self) -> None:
        """Test agents verify placeholder."""
        result = runner.invoke(app, ["agents", "verify"])
        assert result.exit_code == 0
        assert "Not yet implemented" in result.stdout


class TestServerCommands:
    """Test server command group."""

    def test_server_help(self) -> None:
        """Test server --help."""
        result = runner.invoke(app, ["server", "--help"])
        assert result.exit_code == 0
        assert "Manage MCP server lifecycle" in result.stdout

    def test_server_run_placeholder(self) -> None:
        """Test server run placeholder."""
        result = runner.invoke(app, ["server", "run"])
        assert result.exit_code == 0
        assert "Not yet implemented" in result.stdout

    def test_server_debug_placeholder(self) -> None:
        """Test server debug placeholder."""
        result = runner.invoke(app, ["server", "debug"])
        assert result.exit_code == 0
        assert "Not yet implemented" in result.stdout

    def test_server_logs_placeholder(self) -> None:
        """Test server logs placeholder."""
        result = runner.invoke(app, ["server", "logs"])
        assert result.exit_code == 0
        assert "Not yet implemented" in result.stdout


class TestDoctorCommand:
    """Test doctor command."""

    def test_doctor_help(self) -> None:
        """Test doctor --help."""
        result = runner.invoke(app, ["doctor", "--help"])
        assert result.exit_code == 0
        assert "comprehensive health checks" in result.stdout

    def test_doctor_placeholder(self) -> None:
        """Test doctor placeholder."""
        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 0
        assert "Not yet implemented" in result.stdout

    def test_doctor_ci_flag(self) -> None:
        """Test doctor --ci flag."""
        result = runner.invoke(app, ["doctor", "--ci"])
        assert result.exit_code == 0
        # Should still show placeholder
        assert "Not yet implemented" in result.stdout

    def test_doctor_json_flag(self) -> None:
        """Test doctor --json flag."""
        result = runner.invoke(app, ["doctor", "--json"])
        assert result.exit_code == 0
        # Should still show placeholder
        assert "Not yet implemented" in result.stdout


class TestQuickstartCommand:
    """Test quickstart command."""

    def test_quickstart_help(self) -> None:
        """Test quickstart --help."""
        result = runner.invoke(app, ["quickstart", "--help"])
        assert result.exit_code == 0
        assert "first-time setup wizard" in result.stdout

    def test_quickstart_placeholder(self) -> None:
        """Test quickstart placeholder."""
        result = runner.invoke(app, ["quickstart"])
        assert result.exit_code == 0
        assert "Not yet implemented" in result.stdout
