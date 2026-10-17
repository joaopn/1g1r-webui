"""Moving one file without ever overwriting or losing it (design §8).

Same disk: hard-link the destination, then unlink the source, so an existing destination
makes the move fail instead of being replaced (a plain rename would replace it). Another
disk: copy to a temporary name beside the destination while hashing, compare size and
SHA1, link the temporary name into place, then remove it and the source.
"""

import errno
import hashlib
import os
import shutil
from pathlib import Path

from g1r.config import ApplyConfig

# Filesystems without hard links answer with one of these; the move then renames after a
# fresh check that the destination is free.
NO_LINKS = {errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EMLINK}


class MoveError(RuntimeError):
    """The file was not moved; the message names why. The source is still in place."""


def temp_path(config: ApplyConfig, destination: Path) -> Path:
    return destination.with_name(destination.name + config.temp_suffix)


def sha1_of(config: ApplyConfig, path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        while chunk := handle.read(config.copy_chunk_bytes):
            digest.update(chunk)
    return digest.hexdigest()


def same_file(config: ApplyConfig, a: Path, b: Path) -> bool:
    """Same inode, or the same size and content."""
    sa, sb = a.stat(), b.stat()
    if (sa.st_dev, sa.st_ino) == (sb.st_dev, sb.st_ino):
        return True
    return sa.st_size == sb.st_size and sha1_of(config, a) == sha1_of(config, b)


def same_device(a: Path, b: Path) -> bool:
    return a.stat().st_dev == b.stat().st_dev


def fsync_dir(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def place(existing: Path, destination: Path) -> None:
    """Give `existing` the name `destination` too, never replacing a file already there."""
    try:
        os.link(existing, destination)
    except FileExistsError as exc:
        raise MoveError(f"{destination} already exists") from exc
    except OSError as exc:
        if exc.errno not in NO_LINKS:
            raise MoveError(f"cannot create {destination}: {exc.strerror}") from exc
        if os.path.lexists(destination):
            raise MoveError(f"{destination} already exists") from exc
        os.rename(existing, destination)
        return
    os.unlink(existing)


def _copy(config: ApplyConfig, source: Path, temp: Path) -> str:
    digest = hashlib.sha1()
    with source.open("rb") as src, temp.open("xb") as dst:
        while chunk := src.read(config.copy_chunk_bytes):
            digest.update(chunk)
            dst.write(chunk)
        dst.flush()
        os.fsync(dst.fileno())
    shutil.copystat(source, temp)
    return digest.hexdigest()


def move(config: ApplyConfig, source: Path, destination: Path) -> os.stat_result:
    """Move source to destination; return the destination's stat. Raises MoveError."""
    if not source.is_file() or source.is_symlink():
        raise MoveError(f"{source} is not a regular file")
    if os.path.lexists(destination):
        raise MoveError(f"{destination} already exists")
    size = source.stat().st_size
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise MoveError(f"cannot create {destination.parent}: {exc.strerror}") from exc
    if same_device(source, destination.parent):
        place(source, destination)
    else:
        temp = temp_path(config, destination)
        try:
            expected = _copy(config, source, temp)
            if temp.stat().st_size != size or sha1_of(config, temp) != expected:
                raise MoveError(f"the copy of {source} does not match it")
            place(temp, destination)
        except FileExistsError as exc:
            raise MoveError(f"{temp} already exists") from exc
        except OSError as exc:
            temp.unlink(missing_ok=True)
            raise MoveError(f"copying {source} failed: {exc.strerror}") from exc
        except MoveError:
            temp.unlink(missing_ok=True)
            raise
        source.unlink()
    fsync_dir(destination.parent)
    moved = destination.stat()
    if moved.st_size != size:
        raise MoveError(f"{destination} has the wrong size after the move")
    return moved
