"""Command-line entry point for the GitHub PR Review Spec MCP server."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from .server import ReviewSpecGenerator


def _positive_int(value: str) -> int:
    """
    Validate and convert a string to a positive integer.
    
    Parameters:
        value (str): String to parse as an integer.
    
    Returns:
        int: The parsed integer greater than zero.
    
    Raises:
        argparse.ArgumentTypeError: If `value` cannot be parsed as an integer or if the parsed integer is not greater than zero.
    """
    try:
        ivalue = int(value)
    except ValueError as exc:  # pragma: no cover - argparse handles messaging
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if ivalue <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return ivalue


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """
    Parse command-line arguments for the MCP GitHub PR Review Spec server.
    
    Parameters:
        argv (list[str] | None): Optional list of argument strings to parse. If None, the program's arguments are parsed.
    
    Returns:
        argparse.Namespace: Parsed arguments with fields:
            - env_file (Path | None): Path to a .env file to load, if provided.
            - max_pages (int | None): Override for PR_FETCH_MAX_PAGES.
            - max_comments (int | None): Override for PR_FETCH_MAX_COMMENTS.
            - per_page (int | None): Override for HTTP_PER_PAGE.
            - max_retries (int | None): Override for HTTP_MAX_RETRIES.
    """
    parser = argparse.ArgumentParser(
        prog="mcp-github-pr-review-spec-maker",
        description="Run the GitHub PR Review Spec MCP server over stdio.",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        help="Optional path to a .env file to load before starting the server.",
    )
    parser.add_argument(
        "--max-pages",
        type=_positive_int,
        help="Override PR_FETCH_MAX_PAGES for this process.",
    )
    parser.add_argument(
        "--max-comments",
        type=_positive_int,
        help="Override PR_FETCH_MAX_COMMENTS for this process.",
    )
    parser.add_argument(
        "--per-page",
        type=_positive_int,
        help="Override HTTP_PER_PAGE for this process.",
    )
    parser.add_argument(
        "--max-retries",
        type=_positive_int,
        help="Override HTTP_MAX_RETRIES for this process.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """
    Run the CLI entrypoint: load environment variables (optionally from a file), apply any CLI-provided overrides, start the ReviewSpecGenerator server, and return an appropriate exit code.
    
    Parameters:
        argv (list[str] | None): Command-line arguments to parse; if None, defaults to typical CLI invocation (parse_args will use sys.argv).
    
    Returns:
        int: Process exit code — `0` on normal completion, `130` if interrupted by KeyboardInterrupt; other exceptions are re-raised.
    """
    args = parse_args(argv)

    if args.env_file:
        load_dotenv(args.env_file, override=True)
    else:
        load_dotenv(override=False)

    env_overrides = {
        "PR_FETCH_MAX_PAGES": args.max_pages,
        "PR_FETCH_MAX_COMMENTS": args.max_comments,
        "HTTP_PER_PAGE": args.per_page,
        "HTTP_MAX_RETRIES": args.max_retries,
    }
    for key, value in env_overrides.items():
        if value is not None:
            os.environ[key] = str(value)

    server = ReviewSpecGenerator()
    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        return 130
    except Exception:  # pragma: no cover - surfaces unexpected errors
        print("Unexpected server error", file=sys.stderr)
        raise
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())