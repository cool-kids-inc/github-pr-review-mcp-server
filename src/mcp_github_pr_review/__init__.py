"""GitHub PR Review MCP server package."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version

from .server import create_server  # noqa: F401

try:
    __version__ = _version("mcp-github-pr-review")
except PackageNotFoundError:  # dev/editable fallback
    __version__ = "0"

__all__ = ["create_server", "__version__"]
