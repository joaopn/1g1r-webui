"""New file names from a naming template (a set's Rename tab).

A file identified well enough (`rename.methods`: by checksum, title ID or the user's own
assignment) is proposed the name its template builds from that identity, in the same
folder, with its own extension. Nothing is proposed when the name is already right, taken by
another file, or cannot be built; the row says why. A renamed file keeps the name it had
before its first rename in `rename_origin`, which a revert gives back.
"""

import re
import sqlite3
from dataclasses import dataclass
from pathlib import PurePosixPath

from g1r import scanner, titles
from g1r.config import RenameConfig, Settings

KEEP = "keep"

# A row's status.
TO_RENAME = "rename"
NAMED = "named"
SKIPPED = "skipped"


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


def new_stem(settings: Settings, template: str, game: str, method: str) -> tuple[str | None, str]:
    """The new name without its extension, or None and why it cannot be built."""
    config = settings.rename
    form = config.templates[template].format
    if form is None:
        return None, "names are kept"
    tokens = {"game": game, "title": without_tags(config, game)}
    if settings.title_ids is not None and method == scanner.METHOD_TITLE_ID:
        title = titles.from_name(game, settings.title_ids)
        if title is None:
            return None, "no title ID in its identity"
        tokens = {
            "game": title.name,
            "title": without_tags(config, title.name),
            "title_id": titles.hex_id(title.title_id, settings.title_ids),
            "version": title.version,
        }
    needed = set(re.findall(r"{(\w+)}", form))
    if "title_id" in needed and "title_id" not in tokens:
        return None, "no title ID"
    if "version" in needed and tokens.get("version") is None:
        return None, "version unknown (prod.keys read it)"
    return safe(config, form.format(**tokens)).strip(), ""


def rows(
    settings: Settings,
    conn: sqlite3.Connection,
    label: str,
    template: str,
    waiting: frozenset[str] = frozenset(),
    parts: frozenset[str] = frozenset(),
) -> list[RenameRow]:
    """Every ROM file of the folder with what the template proposes for it. `waiting`: files
    a conversion is proposed for, and `parts` (cue sheets, tracks): renamed once converted."""
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
    claimed: dict[str, str] = {}
    result = []
    for f in files:
        rel = f["rel_path"]
        path = PurePosixPath(rel)
        found = identities.get(rel, [])
        game, method = found[0] if len(found) == 1 else (None, None)
        row = RenameRow(rel, f["size"], game, method, SKIPPED, original=renamed.get(rel))
        result.append(row)
        if rel in waiting or path.suffix.lower().lstrip(".") in parts:
            row.reason = "convert first"
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
        stem, why = new_stem(settings, template, game, method)
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


def counts(found: list[RenameRow]) -> dict:
    return {
        "files": len(found),
        "proposed": sum(1 for r in found if r.status == TO_RENAME),
        "named": sum(1 for r in found if r.status == NAMED),
        "skipped": sum(1 for r in found if r.status == SKIPPED),
        "renamed": sum(1 for r in found if r.original is not None),
    }
