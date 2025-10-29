"""Configuration management commands."""

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
    name="config",
    help="Manage configuration files and settings",
    no_args_is_help=True,
)
console = Console()


@app.command()
def init() -> None:
    """Initialize configuration files with guided prompts."""
    console.print("[yellow]config init - Not yet implemented[/yellow]")
    console.print("This will create config.toml and .env files with proper structure.")


@app.command(name="set")
def set_value() -> None:
    """Set a configuration value."""
    console.print("[yellow]config set - Not yet implemented[/yellow]")
    console.print("Usage: mcp-github-pr config set <key> <value>")


@app.command()
def unset() -> None:
    """Unset a configuration value."""
    console.print("[yellow]config unset - Not yet implemented[/yellow]")
    console.print("Usage: mcp-github-pr config unset <key>")


@app.command()
def show() -> None:
    """Display current configuration with secrets masked."""
    console.print("[yellow]config show - Not yet implemented[/yellow]")
    console.print("This will display effective configuration from all sources.")


@app.command()
def validate() -> None:
    """Validate GitHub token and configuration."""
    console.print("[yellow]config validate - Not yet implemented[/yellow]")
    console.print(
        "This will check token format, API connectivity, and required scopes."
    )


@app.command()
def migrate() -> None:
    """Migrate from legacy .env-only setup to new TOML + .env structure."""
    console.print("[yellow]config migrate - Not yet implemented[/yellow]")
    console.print(
        "This will migrate existing .env configuration with automatic backup."
    )


@app.command()
def edit() -> None:
    """Open config file in $EDITOR for manual editing."""
    console.print("[yellow]config edit - Not yet implemented[/yellow]")
    console.print("This will open config.toml in your default editor.")


@app.command()
def reset() -> None:
    """Reset configuration to defaults with confirmation prompt."""
    console.print("[yellow]config reset - Not yet implemented[/yellow]")
    console.print("This will reset all settings to default values.")
