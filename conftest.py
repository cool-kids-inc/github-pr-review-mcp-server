import faulthandler
import os
import signal
import sys
import threading

import httpx
import pytest

# Enable faulthandler to dump tracebacks on hard hangs
faulthandler.enable(file=sys.stderr)


# Shared mock classes for testing
class DummyResp:
    """Mock HTTP response object for testing."""

    def __init__(self, json_data, status_code=200):
        self._json = json_data
        self.status_code = status_code
        self.headers = {}

    def json(self):
        """Return the mock JSON data."""
        return self._json

    def raise_for_status(self):
        """Raise HTTPStatusError for non-2xx status codes."""
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=None)


class FakeClient:
    """Mock HTTP client for testing API interactions."""

    def __init__(self, *args, **kwargs):
        # Ensure our code passed follow_redirects=True
        assert kwargs.get("follow_redirects", False) is True

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc, tb):
        """Async context manager exit."""
        return False

    async def get(self, url, headers=None):
        """Mock GET request that returns a list of PRs."""
        return DummyResp(
            [
                {
                    "number": 456,
                    "html_url": "https://github.com/owner/repo/pull/456",
                }
            ]
        )


def _get_timeout_seconds() -> int:
    try:
        return int(
            os.getenv(
                "PYTEST_PER_TEST_TIMEOUT",
                os.getenv("PYTEST_TIMEOUT", "5"),
            )
        )
    except Exception:
        return 5


@pytest.fixture(autouse=True)
def per_test_timeout(request: pytest.FixtureRequest):
    """
    Enforce a per-test timeout without external plugins.
    - Uses SIGALRM on Unix main thread to fail fast after N seconds.
    - Falls back to faulthandler-only on platforms without SIGALRM.
    Configure via env var PYTEST_PER_TEST_TIMEOUT (seconds), default 5.
    """
    timeout = _get_timeout_seconds()
    if timeout <= 0:
        # Disabled
        yield
        return

    # If pytest-timeout plugin is present, let it enforce the fail-fast;
    # we only add diagnostics.
    has_pytest_timeout = request.config.pluginmanager.hasplugin("timeout")

    if has_pytest_timeout:
        # Always provide diagnostic stack dumps if a test stalls
        faulthandler.dump_traceback_later(timeout, repeat=False)
        try:
            yield
        finally:
            faulthandler.cancel_dump_traceback_later()
    else:
        # Fallback enforcement without plugin: Use SIGALRM on POSIX main thread
        use_alarm = hasattr(signal, "SIGALRM") and (
            threading.current_thread() is threading.main_thread()
        )
        if use_alarm:

            def _on_timeout(signum, frame):  # noqa: ARG001 - pytest hooks signature
                # Dump all thread stacks then fail this test
                faulthandler.dump_traceback(file=sys.stderr)
                pytest.fail(f"Test timed out after {timeout}s", pytrace=False)

            old_handler = signal.getsignal(signal.SIGALRM)
            signal.signal(signal.SIGALRM, _on_timeout)
            # Start timer
            signal.setitimer(signal.ITIMER_REAL, float(timeout))
            try:
                yield
            finally:
                # Cancel timer and restore
                signal.setitimer(signal.ITIMER_REAL, 0.0)
                signal.signal(signal.SIGALRM, old_handler)
        else:
            # Non-POSIX fallback: diagnostics only
            faulthandler.dump_traceback_later(timeout, repeat=False)
            try:
                yield
            finally:
                faulthandler.cancel_dump_traceback_later()
