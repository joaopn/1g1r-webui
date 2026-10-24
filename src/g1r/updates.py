"""The Updates & DLC tab of a title-ID folder (Switch): each game's updates, newest first,
then its DLC.

1G1R never acts on updates or DLC; the Matching table lists base files only. Here the
updates older than a game's newest are proposed for discarded/<label>/updates/, unless the
user keeps them (older updates can matter, e.g. for mods); DLC are listed and always kept. A
version is only what the file's content metadata says; when an update of a game with several
has no version read, nothing of that game is proposed.
"""

import sqlite3
from dataclasses import dataclass, field

from g1r import titledb, titles
from g1r.config import Settings
from g1r.grouping import TITLE_KEY_PREFIX
from g1r.matching import REASON_UPDATES, STATUS_LEFT, GameRow, discard_path

STATUS_NEWEST = "newest"
STATUS_OLDER = "older"
STATUS_KEPT = "kept"
STATUS_UNKNOWN = "version unknown"
STATUS_LEFT_ALONE = "left alone"
STATUS_DISCARDED = "discarded"
STATUS_DLC = "dlc"


@dataclass
class UpdateRow:
    group_key: str
    game: str
    rel_path: str
    # titles.UPDATE or titles.DLC.
    role: str
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
    # The newest update titledb knows for the game: its version, which update it is, and
    # its release date (None without titledb, or when it knows no update).
    latest_version: int | None = None
    latest_release: int | None = None
    latest_date: str | None = None
    # The game's newest update here, and titledb knows a newer one.
    newer: bool = False
    # What the file says of itself (its content archives against titledb's list).
    notes: list[str] = field(default_factory=list)


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


def rows(
    settings: Settings,
    label: str,
    games: list[GameRow],
    kept: set[str],
    latest: dict[str, titledb.Latest] | None = None,
) -> list[UpdateRow]:
    """Every update of these games (matching.game_rows of the folder), by game, newest first
    and those without a version last, then the game's DLC. `latest`: titledb's newest update
    per base title ID."""
    config = settings.title_ids
    latest = latest or {}
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
            known_latest = (
                latest.get(titles.hex_id(title.app_id(config), config))
                if title and config
                else None
            )
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
                    titles.UPDATE,
                    titles.hex_id(title.title_id, config) if title and config else "",
                    version,
                    version // config.version_step if config and version is not None else None,
                    row.version.title_display,
                    row.size,
                    status,
                    reason,
                    operation,
                    row.discarded,
                    known_latest.version if known_latest else None,
                    known_latest.version // config.version_step if known_latest else None,
                    known_latest.date if known_latest else None,
                    status == STATUS_NEWEST
                    and version is not None
                    and known_latest is not None
                    and known_latest.version > version,
                    list(row.notes),
                )
            )
        for row in game.rows:
            if row.version.role != titles.DLC:
                continue
            title = titles.from_name(row.version.game_name, config) if config else None
            result.append(
                UpdateRow(
                    game.group.key,
                    game.group.name,
                    row.version.rel_path,
                    titles.DLC,
                    titles.hex_id(title.title_id, config) if title and config else "",
                    row.version.title_version,
                    None,
                    row.version.title_display,
                    row.size,
                    STATUS_DLC,
                    "DLC is always kept",
                    None,
                    row.discarded,
                    notes=list(row.notes),
                )
            )
    result.sort(
        key=lambda r: (
            r.game.lower(),
            r.role != titles.UPDATE,
            r.version is None,
            -(r.version or 0),
            r.rel_path,
        )
    )
    return result


@dataclass
class GameEntry:
    """One game of the set on the Updates & DLC tab, whether or not it has updates or DLC."""

    group_key: str
    game: str
    # Its newest update here: the version shown to players and the version number (None
    # without an update, or when not read).
    display_version: str | None
    version: int | None
    # titledb knows a newer update than its newest here (a game without an update: titledb
    # knows one).
    newer: bool
    latest_release: int | None
    latest_date: str | None
    updates: int
    dlc: int
    to_discard: int
    # The bytes of its updates and DLC still in the folder.
    size: int
    # On titledb's newest update (or titledb knows none for it); None: cannot be told (no
    # titledb, or its newest update's version is not read).
    latest: bool | None


def games(
    settings: Settings,
    game_rows: list[GameRow],
    rows: list[UpdateRow],
    latest: dict[str, titledb.Latest] | None = None,
) -> list[GameEntry]:
    """Every title-ID game of the set (matching.game_rows), by name, with what `rows` (its
    updates and DLC) hold and whether it is on titledb's newest update (`latest`: titledb's
    newest update per base title ID; empty without titledb)."""
    config = settings.title_ids
    latest = latest or {}
    by_game: dict[str, list[UpdateRow]] = {}
    for row in rows:
        by_game.setdefault(row.group_key, []).append(row)
    result = []
    for game in game_rows:
        mine = [r for r in by_game.get(game.group.key, []) if r.status != STATUS_DISCARDED]
        updates = [r for r in mine if r.role == titles.UPDATE]
        newest = next((r for r in updates if r.status == STATUS_NEWEST), None)
        # The version it is on: its newest update's, the base game's (0) without one; None
        # while an update's version is not read.
        here = newest.version if newest else (None if updates else 0)
        base = game.group.key.removeprefix(TITLE_KEY_PREFIX)
        released = latest.get(base) if config else None
        newer = released is not None and here is not None and released.version > here
        on_latest = None if not latest or here is None else not newer
        result.append(
            GameEntry(
                game.group.key,
                game.group.name,
                newest.display_version if newest else None,
                newest.version if newest else None,
                newer,
                released.version // config.version_step if released and config else None,
                released.date if released else None,
                len(updates),
                len(mine) - len(updates),
                sum(1 for r in updates if r.operation),
                sum(r.size or 0 for r in mine),
                on_latest,
            )
        )
    result.sort(key=lambda g: (g.game.lower(), g.group_key))
    return result


def unreadable(rows: list[UpdateRow]) -> int:
    """Updates in the folder whose version could not be read (prod.keys read it)."""
    return sum(
        1
        for r in rows
        if r.role == titles.UPDATE and r.version is None and r.status != STATUS_DISCARDED
    )
