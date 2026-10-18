"""Files only the app's user may read: console keys and service credentials."""

import os
from pathlib import Path


def write_private(path: Path, data: bytes, mode: int) -> None:
    """Write `data` to `path` with `mode`, replacing it whole (never a half-written file)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".new")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
