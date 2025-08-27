import faulthandler
import os
import signal
import sys
import threading

import pytest

# Enable faulthandler to dump tracebacks on hard hangs
faulthandler.enable(file=sys.stderr)


def _get_timeout_seconds() -> int:
    try:
        return int(os.getenv("PYTEST_PER_TEST_TIMEOUT", os.getenv("PYTEST_TIMEOUT", "5")))
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

    # If pytest-timeout plugin is present, let it enforce the fail-fast; we only add diagnostics.
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
        use_alarm = hasattr(signal, "SIGALRM") and threading.current_thread() is threading.main_thread()
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
