"""Tests for the CLI entry point."""

import argparse
import os
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from mcp_github_pr_review.cli import _positive_int, main, parse_args


class TestPositiveIntValidator:
    """Test the _positive_int validator function."""

    def test_valid_positive_integer(self) -> None:
        assert _positive_int("10") == 10
        assert _positive_int("1") == 1
        assert _positive_int("999") == 999

    def test_zero_raises_error(self) -> None:
        with pytest.raises(argparse.ArgumentTypeError, match="must be positive"):
            _positive_int("0")

    def test_negative_raises_error(self) -> None:
        with pytest.raises(argparse.ArgumentTypeError, match="must be positive"):
            _positive_int("-5")

    def test_non_integer_raises_error(self) -> None:
        with pytest.raises(argparse.ArgumentTypeError, match="must be an integer"):
            _positive_int("abc")

    def test_float_raises_error(self) -> None:
        with pytest.raises(argparse.ArgumentTypeError, match="must be an integer"):
            _positive_int("3.14")


class TestParseArgs:
    """Test the parse_args function."""

    def test_parse_args_no_arguments(self) -> None:
        args = parse_args([])
        assert args.env_file is None
        assert args.max_pages is None
        assert args.max_comments is None
        assert args.per_page is None
        assert args.max_retries is None

    def test_parse_args_with_env_file(self) -> None:
        args = parse_args(["--env-file", "/path/to/.env"])
        assert args.env_file == Path("/path/to/.env")

    def test_parse_args_with_max_pages(self) -> None:
        args = parse_args(["--max-pages", "10"])
        assert args.max_pages == 10

    def test_parse_args_with_max_comments(self) -> None:
        args = parse_args(["--max-comments", "500"])
        assert args.max_comments == 500

    def test_parse_args_with_per_page(self) -> None:
        args = parse_args(["--per-page", "50"])
        assert args.per_page == 50

    def test_parse_args_with_max_retries(self) -> None:
        args = parse_args(["--max-retries", "5"])
        assert args.max_retries == 5

    def test_parse_args_with_all_options(self) -> None:
        args = parse_args(
            [
                "--env-file",
                ".env.test",
                "--max-pages",
                "20",
                "--max-comments",
                "1000",
                "--per-page",
                "75",
                "--max-retries",
                "3",
            ]
        )
        assert args.env_file == Path(".env.test")
        assert args.max_pages == 20
        assert args.max_comments == 1000
        assert args.per_page == 75
        assert args.max_retries == 3

    def test_parse_args_invalid_max_pages(self) -> None:
        with pytest.raises(SystemExit):
            parse_args(["--max-pages", "-1"])

    def test_parse_args_invalid_max_comments(self) -> None:
        with pytest.raises(SystemExit):
            parse_args(["--max-comments", "0"])

    def test_parse_args_invalid_per_page(self) -> None:
        with pytest.raises(SystemExit):
            parse_args(["--per-page", "abc"])


class TestMain:
    """Test the main function."""

    @patch("mcp_github_pr_review.cli.PRReviewServer")
    @patch("mcp_github_pr_review.cli.load_dotenv")
    @patch("mcp_github_pr_review.cli.asyncio.run")
    def test_main_no_arguments(
        self, mock_asyncio_run: Mock, mock_load_dotenv: Mock, mock_server_class: Mock
    ) -> None:
        mock_server = MagicMock()
        mock_server_class.return_value = mock_server

        result = main([])

        assert result == 0
        mock_load_dotenv.assert_called_once_with(override=False)
        mock_server_class.assert_called_once()
        mock_asyncio_run.assert_called_once_with(mock_server.run())

    @patch("mcp_github_pr_review.cli.PRReviewServer")
    @patch("mcp_github_pr_review.cli.load_dotenv")
    @patch("mcp_github_pr_review.cli.asyncio.run")
    def test_main_with_env_file(
        self, mock_asyncio_run: Mock, mock_load_dotenv: Mock, mock_server_class: Mock
    ) -> None:
        mock_server = MagicMock()
        mock_server_class.return_value = mock_server

        result = main(["--env-file", "/custom/.env"])

        assert result == 0
        mock_load_dotenv.assert_called_once_with(Path("/custom/.env"), override=True)

    @patch("mcp_github_pr_review.cli.PRReviewServer")
    @patch("mcp_github_pr_review.cli.load_dotenv")
    @patch("mcp_github_pr_review.cli.asyncio.run")
    def test_main_with_environment_overrides(
        self,
        mock_asyncio_run: Mock,
        mock_load_dotenv: Mock,
        mock_server_class: Mock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mock_server = MagicMock()
        mock_server_class.return_value = mock_server

        # Clear environment before test
        for key in [
            "PR_FETCH_MAX_PAGES",
            "PR_FETCH_MAX_COMMENTS",
            "HTTP_PER_PAGE",
            "HTTP_MAX_RETRIES",
        ]:
            monkeypatch.delenv(key, raising=False)

        result = main(
            [
                "--max-pages",
                "15",
                "--max-comments",
                "750",
                "--per-page",
                "60",
                "--max-retries",
                "4",
            ]
        )

        assert result == 0
        assert os.environ["PR_FETCH_MAX_PAGES"] == "15"
        assert os.environ["PR_FETCH_MAX_COMMENTS"] == "750"
        assert os.environ["HTTP_PER_PAGE"] == "60"
        assert os.environ["HTTP_MAX_RETRIES"] == "4"

    @patch("mcp_github_pr_review.cli.PRReviewServer")
    @patch("mcp_github_pr_review.cli.load_dotenv")
    @patch("mcp_github_pr_review.cli.asyncio.run")
    def test_main_partial_overrides(
        self,
        mock_asyncio_run: Mock,
        mock_load_dotenv: Mock,
        mock_server_class: Mock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mock_server = MagicMock()
        mock_server_class.return_value = mock_server

        # Clear environment before test
        for key in ["PR_FETCH_MAX_PAGES", "HTTP_PER_PAGE"]:
            monkeypatch.delenv(key, raising=False)

        result = main(["--max-pages", "25"])

        assert result == 0
        assert os.environ["PR_FETCH_MAX_PAGES"] == "25"
        # Other env vars should not be set
        assert (
            "PR_FETCH_MAX_COMMENTS" not in os.environ
            or os.environ.get("PR_FETCH_MAX_COMMENTS") != "None"
        )

    @patch("mcp_github_pr_review.cli.PRReviewServer")
    @patch("mcp_github_pr_review.cli.load_dotenv")
    @patch("mcp_github_pr_review.cli.asyncio.run")
    def test_main_keyboard_interrupt_returns_130(
        self, mock_asyncio_run: Mock, mock_load_dotenv: Mock, mock_server_class: Mock
    ) -> None:
        mock_server = MagicMock()
        mock_server_class.return_value = mock_server
        mock_asyncio_run.side_effect = KeyboardInterrupt()

        result = main([])

        assert result == 130

    @patch("mcp_github_pr_review.cli.PRReviewServer")
    @patch("mcp_github_pr_review.cli.load_dotenv")
    @patch("mcp_github_pr_review.cli.asyncio.run")
    def test_main_unexpected_exception_prints_and_raises(
        self,
        mock_asyncio_run: Mock,
        mock_load_dotenv: Mock,
        mock_server_class: Mock,
        capsys: pytest.CaptureFixture,
    ) -> None:
        mock_server = MagicMock()
        mock_server_class.return_value = mock_server
        mock_asyncio_run.side_effect = RuntimeError("Unexpected error")

        with pytest.raises(RuntimeError, match="Unexpected error"):
            main([])

        captured = capsys.readouterr()
        assert "Unexpected server error" in captured.err

    @patch("mcp_github_pr_review.cli.PRReviewServer")
    @patch("mcp_github_pr_review.cli.load_dotenv")
    @patch("mcp_github_pr_review.cli.asyncio.run")
    def test_main_respects_existing_env_vars_when_no_override(
        self,
        mock_asyncio_run: Mock,
        mock_load_dotenv: Mock,
        mock_server_class: Mock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mock_server = MagicMock()
        mock_server_class.return_value = mock_server

        # Set existing environment variable
        monkeypatch.setenv("PR_FETCH_MAX_PAGES", "100")

        result = main([])

        assert result == 0
        # Should not override existing value when no CLI arg provided
        assert os.environ["PR_FETCH_MAX_PAGES"] == "100"
