"""Agent integration management commands."""

from __future__ import annotations

import sys

try:
    import typer
    from rich.console import Console
except ImportError as e:
    print(
        "CLI dependencies not installed. Install with: uv sync --extra cli",
        file=sys.stderr,
    )
    raise SystemExit(1) from e

app = typer.Typer(
    name="agents",
    help="Manage agent client integrations",
    no_args_is_help=True,
)
console = Console()


@app.command(name="list")
def list_agents() -> None:
    """Show supported agent clients with integration status."""
    console.print("[yellow]agents list - Not yet implemented[/yellow]")
    console.print("This will show available agents: Claude CLI/Desktop, Codex, Gemini")


@app.command()
def snippet() -> None:
    """Generate configuration snippet for an agent."""
    console.print("[yellow]agents snippet - Not yet implemented[/yellow]")
    console.print("Usage: mcp-github-pr agents snippet <agent-name>")
    console.print("Example: mcp-github-pr agents snippet claude-cli")


@app.command()
def verify() -> None:
    """Test if specified agent can reach the MCP server."""
    console.print("[yellow]agents verify - Not yet implemented[/yellow]")
    console.print("Usage: mcp-github-pr agents verify <agent-name>")
    console.print("This will test connectivity between agent and MCP server.")
