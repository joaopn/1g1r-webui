"""What sits in discarded/<label>/, grouped by reason (design §8): the listing, and tidying
up the directories emptying it leaves behind.

The layout is discarded/<label>/<reason>/<original relative path>. A file outside a known
reason directory is still listed, under the directory it is in, so nothing there is hidden.
"""

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from g1r.config import Settings
from g1r.conversion import REASON_ORIGINALS
from g1r.journal import REASON_DUPLICATES, REASON_MANUAL, REASON_UPDATES
from g1r.matching import REASON_DISCARDED

# Files directly in discarded/<label>/, outside any reason directory.
REASON_NONE = ""
TIMESTAMP = "%Y-%m-%dT%H:%M:%SZ"

REASONS = {
    REASON_DISCARDED: ("1G1R", "versions 1G1R did not keep"),
    REASON_DUPLICATES: ("Duplicates", "copies of a file the folder still holds"),
    REASON_UPDATES: ("Updates", "game updates 1G1R did not keep (game + DLC)"),
    REASON_ORIGINALS: ("Originals", "files a conversion replaced"),
    REASON_MANUAL: ("Moved by you", "unmatched, flagged or unsupported files you moved out"),
}


@dataclass(frozen=True)
class DiscardedFile:
    rel_path: str
    size: int
    # The file's own mtime as an ISO UTC timestamp; a move keeps it, so not when it came here.
    modified: str
    # Where Restore puts it back, and whether something is already there.
    restore_to: str | None
    occupied: bool
    # The apply operation that moved it here; only those can be restored by the app.
    operation_id: int | None = None


@dataclass
class Reason:
    id: str
    label: str
    description: str
    known: bool
    files: list[DiscardedFile] = field(default_factory=list)

    @property
    def bytes(self) -> int:
        return sum(f.size for f in self.files)


def folder_root(settings: Settings, label: str) -> Path:
    return settings.paths.discarded_root / label


def _walk(root: Path) -> list[tuple[str, os.stat_result]]:
    """Regular files under root (symlinks are not followed), as (posix relative path, stat)."""
    found = []
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir(follow_symlinks=False):
                stack.append(Path(entry.path))
            elif entry.is_file(follow_symlinks=False):
                rel = Path(entry.path).relative_to(root).as_posix()
                found.append((rel, entry.stat(follow_symlinks=False)))
    return found


def listing(
    settings: Settings,
    label: str,
    folder_location: str | None,
    operations: dict[str, int] | None = None,
) -> list[Reason]:
    """Every file in discarded/<label>/, known reasons first in their fixed order.

    `operations` maps a discarded file's absolute path to the apply operation that put it
    there.
    """
    operations = operations or {}
    root = folder_root(settings, label)
    reasons: dict[str, Reason] = {}
    for rel, stat in _walk(root):
        head, sep, rest = rel.partition("/")
        reason_id, original = (head, rest) if sep else (REASON_NONE, rel)
        reason = reasons.get(reason_id)
        if reason is None:
            label_, description = REASONS.get(
                reason_id,
                (reason_id or "Not in a reason folder", "not put here by this app"),
            )
            reason = Reason(reason_id, label_, description, reason_id in REASONS)
            reasons[reason_id] = reason
        restore_to = str(Path(folder_location) / original) if folder_location else None
        reason.files.append(
            DiscardedFile(
                original,
                stat.st_size,
                datetime.fromtimestamp(stat.st_mtime, UTC).strftime(TIMESTAMP),
                restore_to,
                restore_to is not None and os.path.lexists(restore_to),
                operations.get(str(root / rel)),
            )
        )
    order = list(REASONS)
    for reason in reasons.values():
        reason.files.sort(key=lambda f: f.rel_path.casefold())
    return sorted(
        reasons.values(),
        key=lambda r: (order.index(r.id) if r.known else len(order), r.id),
    )


def files_under(settings: Settings, label: str) -> list[tuple[str, os.stat_result]]:
    """Every regular file in discarded/<label>/, relative to it."""
    return _walk(folder_root(settings, label))


def prune_empty(root: Path) -> None:
    """Remove the empty directories under root (root itself stays)."""
    for directory, _, _ in os.walk(root, topdown=False):
        if Path(directory) != root:
            try:
                os.rmdir(directory)
            except OSError:
                pass  # not empty, or already gone


def totals(settings: Settings, label: str) -> dict:
    files = _walk(folder_root(settings, label))
    return {"files": len(files), "bytes": sum(stat.st_size for _, stat in files)}
