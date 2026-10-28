"""New file names from a naming template (a set's Rename tab).

A file identified well enough (`rename.methods`: by checksum, title ID or the user's own
assignment) is proposed the name its template builds from that identity, in the same
folder, with its own extension. Nothing is proposed when the name is already right, taken by
another file, or cannot be built; the row says why. A renamed file keeps the name it had
before its first rename in `rename_origin`, which a revert gives back.
"""

import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath

from g1r import scanner, titles
from g1r.config import RenameConfig, Settings

KEEP = "keep"

# A row's status.
TO_RENAME = "rename"
NAMED = "named"
SKIPPED = "skipped"

# Why a file with another operation pending is not renamed yet.
CONVERT_FIRST = "convert first"
DISCARD_FIRST = "proposed for discarded/"


@dataclass
class RenameRow:
    rel_path: str
    size: int
    # The identified name the new one is built from (None: not identified).
    game: str | None
    method: str | None
    status: str
    # The proposed path (TO_RENAME), or None.
    new_path: str | None = None
    # Why nothing is proposed (SKIPPED).
    reason: str = ""
    # The file's name before its first rename, when the app renamed it.
    original: str | None = None


# A game's name by its title ID (hex), from titledb: a DLC's name carries its game's.
GameName = Callable[[str], str | None]


def origins(conn: sqlite3.Connection, label: str) -> dict[str, str]:
    """Renamed files of the folder: their path now -> their path before the first rename."""
    return {
        r["rel_path"]: r["original"]
        for r in conn.execute(
            "SELECT rel_path, original FROM rename_origin WHERE folder_label = ?", (label,)
        )
    }


def safe(config: RenameConfig, name: str) -> str:
    """The name with every character some filesystem refuses replaced."""
    for ch in config.unsafe_characters:
        name = name.replace(ch, config.replacement)
    return name


def without_tags(config: RenameConfig, name: str) -> str:
    """The name without its (...) and [...] tags, except those `clean_keeps` names (disc,
    side): "Final Fantasy VII (USA) (Disc 1)" -> "Final Fantasy VII (Disc 1)"."""

    def drop(found: re.Match) -> str:
        words = found[1].split()
        return found[0] if words and words[0] in config.clean_keeps else ""

    return re.sub(config.tag_pattern, drop, name).strip()


def cleaned(config: RenameConfig, template: str, name: str) -> str:
    """A name as the template writes it: its own cleaning (Switch's: one space for every
    run of what a file name cannot hold), else unsafe characters replaced."""
    chosen = config.templates[template]
    if chosen.clean_pattern is not None:
        return re.sub(chosen.clean_pattern, chosen.clean_with or "", name).strip()
    return safe(config, name).strip()


def new_stem(
    settings: Settings,
    template: str,
    game: str,
    method: str,
    game_name: GameName | None = None,
) -> tuple[str | None, str]:
    """The new name without its extension, or None and why it cannot be built. `game_name`
    names a DLC's game (its title ID's base)."""
    config = settings.rename
    chosen = config.templates[template]
    form = chosen.format
    if form is None:
        return None, "names are kept"
    tokens: dict = {"game": game, "title": without_tags(config, game)}
    ids = settings.title_ids
    if ids is not None and method == scanner.METHOD_TITLE_ID:
        title = titles.from_name(game, ids)
        if title is None:
            return None, "no title ID in its identity"
        tokens = {
            "game": title.name,
            "title": without_tags(config, title.name),
            "title_id": titles.hex_id(title.title_id, ids),
            "version": title.version,
        }
        if title.role(ids) == titles.DLC and chosen.dlc_format is not None:
            form = chosen.dlc_format
            base = game_name(titles.hex_id(title.app_id(ids), ids)) if game_name else None
            tokens["base"] = base
    needed = set(re.findall(r"{(\w+)}", form))
    if "title_id" in needed and "title_id" not in tokens:
        return None, "no title ID"
    if "version" in needed and tokens.get("version") is None:
        return None, "version unknown (prod.keys read it)"
    if "base" in needed and not tokens.get("base"):
        return None, "its game's name is unknown"
    names = {
        k: cleaned(config, template, v) if isinstance(v, str) else v for k, v in tokens.items()
    }
    return form.format(**names).strip(), ""


def rows(
    settings: Settings,
    conn: sqlite3.Connection,
    label: str,
    template: str,
    pending: dict[str, str] | None = None,
    parts: frozenset[str] = frozenset(),
    game_name: GameName | None = None,
) -> list[RenameRow]:
    """Every ROM file of the folder with what the template proposes for it. `pending`: files
    with another operation pending (a conversion, a move to discarded/), by why, and `parts`
    (cue sheets, tracks): renamed once that is done; the other files meanwhile."""
    pending = pending or {}
    config = settings.rename
    files = conn.execute(
        "SELECT rel_path, size FROM folder_file WHERE folder_label = ? AND place = 'folder' "
        "AND kind IN ('rom', 'archive') ORDER BY rel_path",
        (label,),
    ).fetchall()
    identities: dict[str, list[tuple[str, str]]] = {}
    for r in conn.execute(
        "SELECT rel_path, game_name, method FROM identity WHERE folder_label = ? "
        "ORDER BY game_name",
        (label,),
    ):
        identities.setdefault(r["rel_path"], []).append((r["game_name"], r["method"]))
    # Every name taken in the folder (any kind, discarded ones' old places excepted), by its
    # case-folded path: a new name must not be one of them.
    taken = {
        r["rel_path"].casefold(): r["rel_path"]
        for r in conn.execute(
            "SELECT rel_path FROM folder_file WHERE folder_label = ? AND place = 'folder'",
            (label,),
        )
    }
    renamed = origins(conn, label)
    base_name = _game_names(settings, identities, game_name)
    claimed: dict[str, str] = {}
    result = []
    for f in files:
        rel = f["rel_path"]
        path = PurePosixPath(rel)
        found = identities.get(rel, [])
        game, method = found[0] if len(found) == 1 else (None, None)
        row = RenameRow(rel, f["size"], game, method, SKIPPED, original=renamed.get(rel))
        result.append(row)
        if rel in pending:
            row.reason = pending[rel]
            continue
        if path.suffix.lower().lstrip(".") in parts:
            row.reason = CONVERT_FIRST
            continue
        if not found:
            row.reason = "not identified"
            continue
        if len(found) > 1:
            row.game = ", ".join(name for name, _ in found)
            row.reason = "several games in one file"
            continue
        if method not in config.methods:
            row.reason = "identified by name only: not renamed"
            continue
        stem, why = new_stem(settings, template, game, method, base_name)
        if stem is None:
            row.reason = why
            continue
        if not stem:
            row.reason = "the new name would be empty"
            continue
        name = stem + path.suffix.lower()
        if len(name.encode()) > config.max_name_bytes:
            row.reason = "the new name is too long"
            continue
        new = str(path.with_name(name))
        if new == rel:
            row.status = NAMED
            continue
        other = taken.get(new.casefold()) or claimed.get(new.casefold())
        if other is not None and other != rel:
            row.reason = f"the name is taken by {PurePosixPath(other).name}"
            continue
        claimed[new.casefold()] = rel
        row.status = TO_RENAME
        row.new_path = new
    return result


def _game_names(settings: Settings, identities: dict, game_name: GameName | None) -> GameName:
    """A game's name by its title ID: titledb's, else the name of the folder's base file of
    that game."""
    ids = settings.title_ids
    here: dict[str, str] = {}
    if ids is not None:
        for found in identities.values():
            for name, method in found:
                title = titles.from_name(name, ids) if method == scanner.METHOD_TITLE_ID else None
                if title is not None and title.role(ids) == titles.BASE:
                    here.setdefault(titles.hex_id(title.title_id, ids), title.name)

    def name(title_id: str) -> str | None:
        return (game_name(title_id) if game_name else None) or here.get(title_id)

    return name


def counts(found: list[RenameRow]) -> dict:
    return {
        "files": len(found),
        "proposed": sum(1 for r in found if r.status == TO_RENAME),
        "named": sum(1 for r in found if r.status == NAMED),
        "skipped": sum(1 for r in found if r.status == SKIPPED),
        "renamed": sum(1 for r in found if r.original is not None),
    }
