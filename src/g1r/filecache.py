"""What a scan read from each file, kept for the next scan.

Reading archives, headers and checksums is most of a scan's time, and none of it depends
on the DAT, so a quick scan reuses it for every file whose size and mtime are unchanged.
igir keeps its own cache, one file per folder. A full scan reads everything again (and
stores what it read), and deletes the folder's igir cache.

A step's name includes a fingerprint of the settings its result depends on, so changing
a header rule or a hashing limit reads the files again rather than trusting old results.
"""

import hashlib
import json
import sqlite3
from collections.abc import Callable
from typing import Any, Protocol

from pydantic import BaseModel


class Stat(Protocol):
    rel_path: str
    size: int
    mtime_ns: int


def step(name: str, *depends: Any) -> str:
    """A cache step: `name`, plus a fingerprint of the settings its result depends on."""
    if not depends:
        return name
    parts = [d.model_dump(mode="json") if isinstance(d, BaseModel) else d for d in depends]
    data = json.dumps(parts, sort_keys=True, default=_plain).encode()
    return f"{name}:{hashlib.sha1(data).hexdigest()}"


def _plain(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, set | frozenset):
        return sorted(value)
    raise TypeError(f"not part of a cache fingerprint: {value!r}")


class FileCache:
    """Per-file results for one folder. `get` returns a stored value when the file is
    unchanged, else computes it; `save` writes what was computed. Values are JSON."""

    def __init__(self, conn: sqlite3.Connection | None, label: str, reuse: bool = True):
        self.label = label
        self.stored: dict[tuple[str, str], tuple[int, int, str]] = {}
        self.computed: dict[tuple[str, str], tuple[int, int, str]] = {}
        if conn is not None and reuse:
            for rel_path, name, size, mtime_ns, value in conn.execute(
                "SELECT rel_path, step, size, mtime_ns, value FROM file_cache "
                "WHERE folder_label = ?",
                (label,),
            ):
                self.stored[(rel_path, name)] = (size, mtime_ns, value)

    def get(self, file: Stat, name: str, compute: Callable[[], Any]) -> Any:
        key = (file.rel_path, name)
        row = self.stored.get(key)
        if row is not None:
            size, mtime_ns, value = row
            if size == file.size and mtime_ns == file.mtime_ns:
                return json.loads(value)
        value = compute()
        self.computed[key] = (file.size, file.mtime_ns, json.dumps(value))
        return value

    def save(self, conn: sqlite3.Connection, present: set[str]) -> None:
        """Store what was computed, and drop the rows of files no longer in the folder."""
        gone = {rel for (rel, _) in self.stored} - present
        conn.executemany(
            "DELETE FROM file_cache WHERE folder_label = ? AND rel_path = ?",
            [(self.label, rel) for rel in gone],
        )
        conn.executemany(
            "INSERT OR REPLACE INTO file_cache VALUES (?, ?, ?, ?, ?, ?)",
            [
                (self.label, rel, name, size, mtime, value)
                for (rel, name), (size, mtime, value) in self.computed.items()
            ],
        )


def forget(conn: sqlite3.Connection, label: str) -> None:
    """A set left the library: its files' results go with it."""
    conn.execute("DELETE FROM file_cache WHERE folder_label = ?", (label,))
