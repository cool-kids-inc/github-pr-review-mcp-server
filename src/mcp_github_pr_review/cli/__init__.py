"""Command-line interface for GitHub PR Review MCP server."""

from __future__ import annotations

import importlib.metadata
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

# Initialize Typer app and Rich console
app = typer.Typer(
    name="mcp-github-pr",
    help="GitHub PR Review MCP Server - CLI for configuration and management",
    add_completion=True,
    no_args_is_help=True,
)
console = Console()

# Import and register command groups
from . import agents, config, doctor, quickstart, server  # noqa: E402

app.add_typer(config.app, name="config")
app.add_typer(agents.app, name="agents")
app.add_typer(server.app, name="server")
app.add_typer(doctor.app, name="doctor")
app.add_typer(quickstart.app, name="quickstart")


def version_callback(show_version: bool) -> None:
    """Show version and exit."""
    if show_version:
        try:
            version = importlib.metadata.version("mcp-github-pr-review")
            console.print(f"mcp-github-pr version {version}")
        except importlib.metadata.PackageNotFoundError:
            console.print(
                "mcp-github-pr version: [yellow]unknown[/yellow] (development)"
            )
        raise typer.Exit(0)


@app.callback()
def main(
    version: bool | None = typer.Option(
        None,
        "--version",
        "-v",
        help="Show version and exit",
        callback=version_callback,
        is_eager=True,
    ),
) -> None:
    """
    GitHub PR Review MCP Server CLI.

    A Model Context Protocol server that fetches and formats GitHub PR review
    comments with resolution status and diff context.

    Use --help on any command for detailed usage information.
    """
    pass


def cli_main() -> None:
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    cli_main()
