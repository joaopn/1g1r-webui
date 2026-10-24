"""The Updates tab of a title-ID folder (Switch): each game's updates, newest first.

1G1R keeps every update. Here the updates older than a game's newest are proposed for
discarded/<label>/updates/, unless the user keeps them (older updates can matter, e.g. for
mods). A version is only what the file's content metadata says; when an update of a game
with several has no version read, nothing of that game is proposed.
"""

import sqlite3
from dataclasses import dataclass

from g1r import titles
from g1r.config import Settings
from g1r.matching import REASON_UPDATES, STATUS_LEFT, GameRow, discard_path

STATUS_NEWEST = "newest"
STATUS_OLDER = "older"
STATUS_KEPT = "kept"
STATUS_UNKNOWN = "version unknown"
STATUS_LEFT_ALONE = "left alone"
STATUS_DISCARDED = "discarded"


@dataclass
class UpdateRow:
    group_key: str
    game: str
    rel_path: str
    title_id: str
    version: int | None
    # Which update it is (the version in update steps: 1 for the first update).
    release: int | None
    # The version shown to players ("1.0.2"), read with prod.keys.
    display_version: str | None
    size: int | None
    status: str
    reason: str
    # The proposed move into discarded/updates/, None when the file stays.
    operation: str | None
    # Set once a move took it to discarded/: the journal operation's id (restore).
    discarded: int | None


def keeps(conn: sqlite3.Connection, label: str) -> set[str]:
    return {
        r[0]
        for r in conn.execute("SELECT rel_path FROM update_keep WHERE folder_label = ?", (label,))
    }


def set_keep(conn: sqlite3.Connection, label: str, rel_paths: list[str], keep: bool) -> None:
    if keep:
        conn.executemany(
            "INSERT OR IGNORE INTO update_keep (folder_label, rel_path) VALUES (?, ?)",
            [(label, r) for r in rel_paths],
        )
    else:
        conn.executemany(
            "DELETE FROM update_keep WHERE folder_label = ? AND rel_path = ?",
            [(label, r) for r in rel_paths],
        )


def rows(settings: Settings, label: str, games: list[GameRow], kept: set[str]) -> list[UpdateRow]:
    """Every update of these games (matching.game_rows of the folder): by game, newest first,
    those without a version last."""
    config = settings.title_ids
    result = []
    for game in games:
        updates = [r for r in game.rows if r.version.role == titles.UPDATE]
        present = [r for r in updates if not r.discarded]
        versions = [r.version.title_version for r in present]
        # A lone update is the newest whatever its version says.
        known = len(present) == 1 or all(v is not None for v in versions)
        newest = max(versions, key=lambda v: v or 0) if versions and known else None
        for row in updates:
            version = row.version.title_version
            title = titles.from_name(row.version.game_name, config) if config else None
            operation = None
            if row.discarded:
                status, reason = STATUS_DISCARDED, "in discarded/updates/"
            elif game.status == STATUS_LEFT:
                status, reason = STATUS_LEFT_ALONE, game.reason
            elif not known:
                status, reason = (
                    STATUS_UNKNOWN,
                    (
                        "no readable version (add prod.keys): nothing of this game is proposed"
                        if version is None
                        else "another update of this game has no readable version"
                    ),
                )
            elif version == newest or len(present) == 1:
                status, reason = STATUS_NEWEST, "the newest update of this game"
            elif row.version.rel_path in kept:
                status, reason = STATUS_KEPT, "you keep this older update"
            else:
                status, reason = STATUS_OLDER, "a newer update of this game is in the folder"
                operation = discard_path(settings, label, row.version.rel_path, REASON_UPDATES)
            result.append(
                UpdateRow(
                    game.group.key,
                    game.group.name,
                    row.version.rel_path,
                    titles.hex_id(title.title_id, config) if title and config else "",
                    version,
                    version // config.version_step if config and version is not None else None,
                    row.version.title_display,
                    row.size,
                    status,
                    reason,
                    operation,
                    row.discarded,
                )
            )
    result.sort(key=lambda r: (r.game.lower(), r.version is None, -(r.version or 0), r.rel_path))
    return result
