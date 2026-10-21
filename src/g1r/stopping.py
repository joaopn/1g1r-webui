"""Stopping a conversion run part way (maintainer, 2026-10-21: "Done rom work is kept,
in-flight has its generated files deleted").

The journal arms a step's thread with the run's stop event while the step converts. Long
loops call `check()` between chunks, and external tools run through `run()`, which kills the
tool when the stop comes. Either raises `Stopped`, a MoveError, so the converter deletes what
the step wrote, as it does for any failure. Without an armed event both behave as before.
"""

import subprocess
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

from g1r.moves import MoveError

_armed = threading.local()


class Stopped(MoveError):
    """The run was stopped while this step worked; what it wrote is removed."""


@contextmanager
def armed(event: threading.Event | None, poll_seconds: float) -> Iterator[None]:
    """Within the block, this thread's step stops when `event` is set."""
    _armed.event, _armed.poll_seconds = event, poll_seconds
    try:
        yield
    finally:
        _armed.event = None


def _event() -> threading.Event | None:
    return getattr(_armed, "event", None)


def check() -> None:
    event = _event()
    if event is not None and event.is_set():
        raise Stopped("stopped before it finished")


def run(command: list[str], timeout: float, **popen) -> subprocess.CompletedProcess:
    """`subprocess.run(command, timeout=timeout, check=False, **popen)`, except that the
    tool is killed and `Stopped` raised when the armed event is set while it runs."""
    event = _event()
    if event is None:
        return subprocess.run(command, timeout=timeout, check=False, **popen)
    check()
    deadline = time.monotonic() + timeout
    with subprocess.Popen(command, **popen) as process:
        while True:
            try:
                out, err = process.communicate(timeout=_armed.poll_seconds)
            except subprocess.TimeoutExpired:
                if not event.is_set() and time.monotonic() < deadline:
                    continue
                process.kill()
                process.communicate()
                if event.is_set():
                    raise Stopped("stopped before it finished") from None
                raise subprocess.TimeoutExpired(command, timeout) from None
            return subprocess.CompletedProcess(command, process.returncode, out, err)
