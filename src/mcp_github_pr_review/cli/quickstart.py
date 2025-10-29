"""Interactive quickstart and setup commands."""

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
    name="quickstart",
    help="Interactive first-time setup wizard",
    no_args_is_help=False,
)
console = Console()


@app.callback(invoke_without_command=True)
def quickstart(ctx: typer.Context) -> None:
    """
    Interactive first-time setup wizard.

    Combines init, validation, and agent snippet generation in one flow.
    Perfect for new users to get started quickly.
    """
    if ctx.invoked_subcommand is None:
        console.print("[yellow]quickstart - Not yet implemented[/yellow]")
        console.print("\nThis interactive wizard will guide you through:")
        console.print("  1. Creating configuration files")
        console.print("  2. Setting up GitHub token")
        console.print("  3. Validating connectivity")
        console.print("  4. Generating agent snippets")
        console.print("  5. Testing the server")
