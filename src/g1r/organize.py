"""Game folders of a title-ID set (the Updates & DLC tab, optional): every file of a game in
a folder named after the game, its updates and DLC in subfolders of it, as RomM lays out a
game of several files.

Only files identified by their title ID are moved; a file keeps its name. A moved file
keeps the folder it was in before its first move in `folder_origin`, which a revert gives
back. None of it counts toward a set being done.
"""

import re
import sqlite3
from dataclasses import dataclass
from pathlib import PurePosixPath

from g1r import renaming, scanner, titles
from g1r.config import Settings

# A row's status.
TO_MOVE = "move"
IN_PLACE = "in place"
SKIPPED = "skipped"


@dataclass
class OrganizeRow:
    rel_path: str
    size: int
    # The game's folder and the file's kind (titles.BASE, UPDATE, DLC), when known.
    game: str | None
    role: str | None
    status: str
    # The proposed path (TO_MOVE), or None.
    new_path: str | None = None
    # Why nothing is proposed (SKIPPED).
    reason: str = ""
    # The folder it was in before its first move ('' = the set's folder), when moved.
    original_dir: str | None = None


def origins(conn: sqlite3.Connection, label: str) -> dict[str, str]:
    """Moved files of the folder: their path now -> the folder they came from."""
    return {
        r["rel_path"]: r["original_dir"]
        for r in conn.execute(
            "SELECT rel_path, original_dir FROM folder_origin WHERE folder_label = ?", (label,)
        )
    }


def folder_name(settings: Settings, name: str) -> str:
    """A game's name as a folder name."""
    config = settings.organize
    return re.sub(config.clean_pattern, config.clean_with, name).strip(config.strip)


def rows(
    settings: Settings,
    conn: sqlite3.Connection,
    label: str,
    pending: dict[str, str] | None = None,
    game_name: renaming.GameName | None = None,
) -> list[OrganizeRow]:
    """Every ROM file of a title-ID folder with where its game's folder would put it.
    `pending`: files with another operation pending, by why (moved once that is done);
    `game_name`: a game's name by its base title ID (titledb)."""
    ids = settings.title_ids
    pending = pending or {}
    files = conn.execute(
        "SELECT rel_path, size FROM folder_file WHERE folder_label = ? AND place = 'folder' "
        "AND kind IN ('rom', 'archive') ORDER BY rel_path",
        (label,),
    ).fetchall()
    identities: dict[str, list[tuple[str, str]]] = {}
    for r in conn.execute(
        "SELECT rel_path, game_name, method FROM identity WHERE folder_label = ?", (label,)
    ):
        identities.setdefault(r["rel_path"], []).append((r["game_name"], r["method"]))
    taken = {
        r["rel_path"].casefold(): r["rel_path"]
        for r in conn.execute(
            "SELECT rel_path FROM folder_file WHERE folder_label = ? AND place = 'folder'",
            (label,),
        )
    }
    moved = origins(conn, label)
    name_of = renaming.game_names(settings, identities, game_name)
    claimed: dict[str, str] = {}
    result = []
    for f in files:
        rel = f["rel_path"]
        row = OrganizeRow(rel, f["size"], None, None, SKIPPED, original_dir=moved.get(rel))
        result.append(row)
        found = identities.get(rel, [])
        title = (
            titles.from_name(found[0][0], ids)
            if ids is not None and len(found) == 1 and found[0][1] == scanner.METHOD_TITLE_ID
            else None
        )
        if title is None:
            row.reason = "not identified by its title ID"
            continue
        row.role = title.role(ids)
        game = name_of(titles.hex_id(title.app_id(ids), ids))
        if not game:
            row.reason = "its game's name is unknown"
            continue
        row.game = folder_name(settings, game)
        if not row.game:
            row.reason = "the folder name would be empty"
            continue
        if rel in pending:
            row.reason = pending[rel]
            continue
        subfolder = settings.organize.subfolders.get(row.role, "")
        new = str(PurePosixPath(row.game, subfolder, PurePosixPath(rel).name))
        if new == rel:
            row.status = IN_PLACE
            continue
        other = taken.get(new.casefold()) or claimed.get(new.casefold())
        if other is not None and other != rel:
            row.reason = f"{new} is taken by {other}"
            continue
        claimed[new.casefold()] = rel
        row.status = TO_MOVE
        row.new_path = new
    return result


def back(found: list[OrganizeRow], conn: sqlite3.Connection, label: str) -> list[tuple[str, str]]:
    """The moved files of `found` and the path each goes back to: its name in the folder it
    came from. A file whose old place is taken stays."""
    taken = {
        r["rel_path"].casefold()
        for r in conn.execute(
            "SELECT rel_path FROM folder_file WHERE folder_label = ? AND place = 'folder'",
            (label,),
        )
    }
    result = []
    for r in found:
        if r.original_dir is None:
            continue
        new = str(PurePosixPath(r.original_dir, PurePosixPath(r.rel_path).name))
        if new.casefold() in taken:
            continue
        taken.add(new.casefold())
        result.append((r.rel_path, new))
    return result


def counts(found: list[OrganizeRow]) -> dict:
    return {
        "files": len(found),
        "proposed": sum(1 for r in found if r.status == TO_MOVE),
        "in_place": sum(1 for r in found if r.status == IN_PLACE),
        "skipped": sum(1 for r in found if r.status == SKIPPED),
        "moved": sum(1 for r in found if r.original_dir is not None),
    }
