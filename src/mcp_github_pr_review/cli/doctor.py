"""Health check and diagnostic commands."""

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
    name="doctor",
    help="Run comprehensive health checks",
    no_args_is_help=False,
)
console = Console()


@app.callback(invoke_without_command=True)
def doctor(
    ctx: typer.Context,
    ci: bool = typer.Option(False, "--ci", help="CI mode: treat warnings as errors"),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
) -> None:
    """
    Run comprehensive health checks on the MCP server setup.

    Checks:
    - Python version (>= 3.10)
    - uv binary availability
    - GitHub token validity
    - GitHub API connectivity
    - Token scopes
    - Config file validity
    - MCP server module
    - Git repository detection
    """
    if ctx.invoked_subcommand is None:
        console.print("[yellow]doctor - Not yet implemented[/yellow]")
        console.print("\nThis will perform comprehensive health checks:")
        console.print("  - Python version")
        console.print("  - uv binary")
        console.print("  - GitHub token")
        console.print("  - GitHub API connectivity")
        console.print("  - Token scopes")
        console.print("  - Configuration validity")
        console.print("  - MCP server smoke test")
        console.print("  - Git repository detection")
