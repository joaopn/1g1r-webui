"""Apply and restore, journalled (design §8).

A plan is a list of steps built from the reviewed proposals: moves, and for conversions an
output written, then its original moved to discarded/ or deleted. Its token fingerprints
every step with the file's size and mtime as scanned, so applying refuses when the plan
changed after review. Each step is written to the journal as 'started' and committed before
the file is touched; start-up recovery settles any step a restart cut off.
"""

import hashlib
import os
import shutil
import sqlite3
import threading
import zipfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from g1r import cards, conversion, moves, stopping
from g1r.config import ApplyConfig
from g1r.converter import CRC_FORMAT

# The discarded/ subfolder of 1G1R moves (matching.REASON_DISCARDED names the same one).
REASON_1G1R = "1g1r"
# Identical copies of a kept version (discarded.REASON_DUPLICATES names the same one).
REASON_DUPLICATES = "duplicates"
# A title-ID game's update (Switch), which 1G1R does not keep.
REASON_UPDATES = "updates"

PLACE_FOLDER = "folder"
PLACE_DISCARDED = "discarded"

APPLY = "apply"
RESTORE = "restore"

RUNNING = "running"
DONE = "done"
FAILED = "failed"

STARTED = "started"
RESTORED = "restored"

# What a step does (operation.action).
MOVE = "move"
CONVERT = "convert"
DELETE = "delete"
REMOVE = "remove"
# Run scopes besides 1G1R (a group key or '' for the folder).
SCOPE_UNMATCHED = "unmatched"
SCOPE_EMPTY = "empty"
SCOPE_SET_ASIDE = "set-aside"
# Files the user moved out (unmatched, flagged, unsupported) go to this discarded/ subfolder.
REASON_MANUAL = "manual"

# Steps that write a new name for the file and must find that name free.
WRITES = (MOVE, CONVERT)

# The per-file rows a conversion's output inherits from its original (same ROM data).
CARRIED = (
    "identity",
    "content_hash",
    "lookup_result",
    "suggestion",
    "manual_identity",
    "payload_hash",
    "file_note",
    "card_info",
)


# The hash rows of those: carried only by conversions that keep the ROM's bytes (a zip made
# or unmade, an archive repacked); a disc, a decryption or a byteswap writes other bytes,
# hashed again by the next scan.
HASH_ROWS = ("content_hash", "payload_hash")
SAME_BYTES = (conversion.RECIPE_WRAP, conversion.RECIPE_UNWRAP, conversion.RECIPE_REPACK)


class PlanError(RuntimeError):
    """The plan cannot run; the message (and per-file problems) are shown to the user."""

    def __init__(self, message: str, problems: list[tuple[str, str]] | None = None):
        super().__init__(message)
        self.problems = problems or []


@dataclass(frozen=True)
class Move:
    """One step of a plan; most are moves, hence the name."""

    rel_path: str
    group_key: str
    reason: str
    source: Path
    destination: Path | None
    size: int
    mtime_ns: int
    # Restore only: the apply operation this step undoes.
    undoes: int | None = None
    action: str = MOVE
    # Convert: the output's path in the folder. Remove: the original's, which gets its rows back.
    paired_rel: str | None = None
    # Unwrap, and a byteswap or decryption from an archive: the member read, as listed.
    member: str | None = None
    member_size: int | None = None
    member_crc32: str | None = None
    # This step finishes the convert step just before it (moves or deletes its original).
    follows: bool = False
    # Remove only: the convert operation whose output this removes. Delete of a file in
    # discarded/: the apply move that put it there (None if the app did not).
    step_of: int | None = None
    # The source is a file in discarded/ (emptying it), not in the folder.
    in_discarded: bool = False
    # Restore only: the conversion this original belongs to. Its output is removed only
    # when every one of its originals came back.
    back_for: int | None = None
    # Convert only: how (conversion.RECIPE_*), chdman's mode for a disc, an archive's members
    # as listed (name, size, CRC32) for a disc unpacked from it, and the bytes it needs free.
    recipe: str | None = None
    disc_mode: str | None = None
    inner: tuple = ()
    space: int | None = None
    # Byteswap only: the word length whose bytes are reversed, and the ROM's name in the
    # output zip (None: the output is the bare ROM).
    word_bytes: int | None = None
    output_member: str | None = None
    # Decrypt only: the card image format whose hashes prove the output.
    card_image: str | None = None


def token(plan: list[Move]) -> str:
    digest = hashlib.sha1()
    for m in plan:
        digest.update(
            f"{m.action}\0{m.source}\0{m.destination or ''}\0{m.size}\0{m.mtime_ns}\0"
            f"{m.member or ''}\0{m.recipe or ''}\n".encode()
        )
    return digest.hexdigest()


def running(conn: sqlite3.Connection, label: str) -> bool:
    """An apply or a restore (of any kind, conversions included) runs on the folder."""
    return (
        conn.execute(
            "SELECT 1 FROM apply_run WHERE folder_label = ? AND status = ?", (label, RUNNING)
        ).fetchone()
        is not None
    )


def busy(conn: sqlite3.Connection, label: str) -> str | None:
    """Why the folder cannot start an apply or a scan now, or None."""
    if conn.execute(
        "SELECT 1 FROM scan WHERE folder_label = ? AND status = 'running'", (label,)
    ).fetchone():
        return "a scan of this folder is already running"
    if running(conn, label):
        return "an apply or restore is running on this folder"
    return None


# Planning -------------------------------------------------------------------------


def plan_discards(conn: sqlite3.Connection, label: str, root: Path, games) -> list[Move]:
    """The proposed 1G1R moves of these games (matching.GameRow), as scanned."""
    scanned = {
        r["rel_path"]: r
        for r in conn.execute(
            "SELECT rel_path, size, mtime_ns FROM folder_file WHERE folder_label = ? AND place = ?",
            (label, PLACE_FOLDER),
        )
    }
    plan = []
    for game in games:
        for row in game.rows:
            f = scanned.get(row.version.rel_path)
            if not row.operation or f is None:
                continue
            plan.append(
                Move(
                    f["rel_path"],
                    game.group.key,
                    row.discard_reason,
                    root / f["rel_path"],
                    Path(row.operation),
                    f["size"],
                    f["mtime_ns"],
                )
            )
    plan.sort(key=lambda m: m.rel_path)
    return plan


def plan_conversions(
    conn: sqlite3.Connection,
    label: str,
    root: Path,
    rows: list[conversion.ConversionRow],
    discarded_root: Path | None = None,
) -> list[Move]:
    """Per proposed conversion: write the output, then move or delete each original (the
    file, and a cue sheet's track files with it)."""
    scanned = {
        r["rel_path"]: r
        for r in conn.execute(
            "SELECT rel_path, size, mtime_ns FROM folder_file WHERE folder_label = ? AND place = ?",
            (label, PLACE_FOLDER),
        )
    }
    plan = []
    for row in sorted(rows, key=lambda r: r.rel_path):
        f = scanned.get(row.rel_path)
        parts = [scanned.get(p) for p in row.parts]
        if row.status not in conversion.CONVERTING or not row.output or f is None or None in parts:
            continue
        member = next(
            (m for m in row.members if PurePosixPath(m["name"]).name == Path(row.output).name),
            None,
        )
        if row.recipe in (conversion.RECIPE_BYTESWAP, conversion.RECIPE_DECRYPT):
            member = row.source_member
        # Unwrap, and a byteswap or decryption from an archive, read one member as the scan
        # listed it.
        reads = (conversion.RECIPE_UNWRAP, conversion.RECIPE_BYTESWAP, conversion.RECIPE_DECRYPT)
        unwrap = member is not None and row.recipe in reads
        sources = [f, *parts]
        plan.append(
            Move(
                row.rel_path,
                "",
                conversion.REASON_ORIGINALS,
                root / row.rel_path,
                root / row.output,
                f["size"],
                f["mtime_ns"],
                action=CONVERT,
                paired_rel=row.output,
                member=member["name"] if unwrap else None,
                member_size=member["size"] if unwrap else None,
                member_crc32=member["crc32"] if unwrap else None,
                recipe=row.recipe,
                disc_mode=row.disc_mode,
                inner=tuple(
                    (m["name"], m.get("size"), m.get("crc32"))
                    for m in row.members
                    if row.recipe == conversion.RECIPE_ARCHIVE_DISC
                ),
                space=_conversion_space(row, sources, member),
                word_bytes=row.word_bytes,
                output_member=row.output_member,
                card_image=row.card_image,
            )
        )
        for source in sources:
            rel = source["rel_path"]
            sized = (source["size"], source["mtime_ns"])
            common = (rel, "", conversion.REASON_ORIGINALS, root / rel)
            if row.originals_to:
                destination = Path(
                    conversion.originals_path_under(row.originals_to, row.rel_path, rel)
                )
                plan.append(Move(*common, destination, *sized, follows=True))
            else:
                plan.append(Move(*common, None, *sized, action=DELETE, follows=True))
    return plan


def _conversion_space(row: conversion.ConversionRow, sources, member) -> int:
    """Bytes the conversion needs free: the output (at most its data's size), and for a
    disc the tracks extracted back for the check (plus, from an archive, the unpacked copy)."""
    total = sum(s["size"] for s in sources)
    if row.recipe in (conversion.RECIPE_UNWRAP, conversion.RECIPE_BYTESWAP) and member:
        return member["size"]
    if row.recipe == conversion.RECIPE_DECRYPT and member:
        # The unpacked copy and the output.
        return member["size"] + member["size"]
    if row.recipe in (conversion.RECIPE_ARCHIVE_DISC, conversion.RECIPE_REPACK):
        # The unpacked copy and the output (a disc: then the output and the tracks extracted
        # back; a zip: at most the unpacked size).
        unpacked = sum(m.get("size") or 0 for m in row.members)
        return unpacked + unpacked
    if row.recipe == conversion.RECIPE_DISC:
        return total + total
    return total


def plan_unmatched(
    conn: sqlite3.Connection,
    label: str,
    root: Path,
    discarded_root: Path,
    rel_paths: list[str],
    *,
    delete: bool,
    parts: frozenset[str] = frozenset(),
) -> list[Move]:
    """Move unmatched files to discarded/<label>/manual/, or delete them (guarded). Parts of
    a game (cue sheets, tracks) are not unmatched content: they wait for conversion."""
    unmatched = {
        r["rel_path"]: r
        for r in conn.execute(
            "SELECT f.rel_path, f.size, f.mtime_ns FROM folder_file f "
            "WHERE f.folder_label = ? AND f.kind IN ('rom', 'archive') AND f.place = ? "
            "AND NOT EXISTS (SELECT 1 FROM identity i "
            "WHERE i.folder_label = f.folder_label AND i.rel_path = f.rel_path)",
            (label, PLACE_FOLDER),
        )
        if PurePosixPath(r["rel_path"]).suffix.lower().lstrip(".") not in parts
    }
    missing = [rel for rel in rel_paths if rel not in unmatched]
    if missing:
        raise PlanError(
            "these files are not unmatched content (rescan?)",
            [(m, "not unmatched") for m in missing],
        )
    plan = []
    for rel in sorted(set(rel_paths)):
        f = unmatched[rel]
        if delete:
            plan.append(
                Move(
                    rel,
                    "",
                    REASON_MANUAL,
                    root / rel,
                    None,
                    f["size"],
                    f["mtime_ns"],
                    action=DELETE,
                )
            )
        else:
            plan.append(
                Move(
                    rel,
                    "",
                    REASON_MANUAL,
                    root / rel,
                    discarded_root / REASON_MANUAL / rel,
                    f["size"],
                    f["mtime_ns"],
                )
            )
    return plan


def plan_set_aside(
    conn: sqlite3.Connection,
    label: str,
    root: Path,
    discarded_root: Path,
    rel_paths: list[str],
    eligible: set[str],
) -> list[Move]:
    """Move flagged or unsupported files, or files a conversion failed on (`eligible`), to
    discarded/<label>/manual/."""
    scanned = {
        r["rel_path"]: r
        for r in conn.execute(
            "SELECT rel_path, size, mtime_ns FROM folder_file WHERE folder_label = ? AND place = ?",
            (label, PLACE_FOLDER),
        )
    }
    missing = [rel for rel in rel_paths if rel not in eligible or rel not in scanned]
    if missing:
        raise PlanError(
            "these files are not flagged, unsupported or failed to convert (rescan?)",
            [(m, "not flagged, unsupported or failed to convert") for m in missing],
        )
    plan = []
    for rel in sorted(set(rel_paths)):
        f = scanned[rel]
        plan.append(
            Move(
                rel,
                "",
                REASON_MANUAL,
                root / rel,
                discarded_root / REASON_MANUAL / rel,
                f["size"],
                f["mtime_ns"],
            )
        )
    return plan


def plan_empty(conn: sqlite3.Connection, label: str, discarded_root: Path, files) -> list[Move]:
    """Delete every file in discarded/<label>/ for good (guarded).

    `files` is (path relative to discarded_root, stat) for each file found there.
    """
    moved = {op["destination"]: op for op in active_discards(conn, label)}
    plan = []
    for rel, stat in sorted(files):
        path = discarded_root / rel
        op = moved.get(str(path))
        plan.append(
            Move(
                rel,
                "",
                PurePosixPath(rel).parts[0],
                path,
                None,
                stat.st_size,
                stat.st_mtime_ns,
                action=DELETE,
                paired_rel=op["rel_path"] if op else None,
                step_of=op["id"] if op else None,
                in_discarded=True,
            )
        )
    return plan


def irreversible(plan: list[Move]) -> list[Move]:
    return [m for m in plan if m.action == DELETE]


def active_discards(conn: sqlite3.Connection, label: str) -> list[sqlite3.Row]:
    """Apply moves whose file is in discarded/ now (moved, not restored, not emptied)."""
    return conn.execute(
        "SELECT o.* FROM operation o JOIN apply_run r ON r.id = o.run_id "
        "WHERE o.folder_label = ? AND r.kind = ? AND o.state = ? AND o.action = ? "
        "AND NOT EXISTS (SELECT 1 FROM operation d WHERE d.step_of = o.id "
        "AND d.action = ? AND d.state = ?) "
        "ORDER BY o.rel_path",
        (label, APPLY, DONE, MOVE, DELETE, DONE),
    ).fetchall()


def _root_of(op) -> Path:
    """The folder an operation's rel_path is relative to, from its source path."""
    source = Path(op["source"])
    return source.parents[len(PurePosixPath(op["rel_path"]).parts) - 1]


def plan_restore(
    conn: sqlite3.Connection,
    label: str,
    *,
    operation_ids: list[int] | None = None,
    group_key: str | None = None,
) -> list[Move]:
    """Moves back; restoring one original of a conversion restores all of its originals,
    then removes the output made from them."""
    active = active_discards(conn, label)
    chosen = [
        op
        for op in active
        if (operation_ids is None or op["id"] in operation_ids)
        and (group_key is None or op["group_key"] == group_key)
    ]
    if operation_ids is not None and len(chosen) != len(set(operation_ids)):
        raise PlanError("some of these files are not in discarded/ (already restored?)")
    conversions = {op["step_of"] for op in chosen if op["step_of"]}
    chosen_ids = {op["id"] for op in chosen}
    chosen += [op for op in active if op["step_of"] in conversions and op["id"] not in chosen_ids]
    plan = []
    for op in sorted(chosen, key=lambda o: (o["step_of"] or 0, o["id"])):
        plan.append(
            Move(
                op["rel_path"],
                op["group_key"],
                op["reason"],
                Path(op["destination"]),
                Path(op["source"]),
                op["size"],
                op["moved_mtime_ns"],
                undoes=op["id"],
                back_for=op["step_of"],
            )
        )
    for step_of in sorted(conversions):
        converted = conn.execute(
            "SELECT * FROM operation WHERE id = ? AND state = ?", (step_of, DONE)
        ).fetchone()
        if converted is None:
            continue
        # The originals are back, so the output made from them goes.
        output = Path(converted["destination"])
        plan.append(
            Move(
                str(output.relative_to(_root_of(converted)).as_posix()),
                "",
                conversion.REASON_ORIGINALS,
                output,
                None,
                converted["moved_size"],
                converted["moved_mtime_ns"],
                undoes=converted["id"],
                action=REMOVE,
                paired_rel=converted["rel_path"],
                step_of=converted["id"],
            )
        )
    return plan


# Preflight ------------------------------------------------------------------------


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _roots(m: Move, kind: str, folder: Path, discarded: Path) -> tuple[Path, Path]:
    """Where a step's source and destination must be."""
    if m.action == MOVE:
        return (folder, discarded) if kind == APPLY else (discarded, folder)
    if m.in_discarded:
        return discarded, discarded
    return folder, folder


def _space_needed(m: Move) -> int:
    if m.space is not None:
        return m.space
    return m.member_size if m.member is not None else m.size


def preflight(
    plan: list[Move], folder_root: Path, discarded_root: Path, kind: str = APPLY
) -> list[tuple[str, str]]:
    """Every reason the plan must not run, per file. Empty means it may run."""
    problems = []
    claimed: set[Path] = set()
    for m in plan:
        source_root, destination_root = _roots(m, kind, folder_root, discarded_root)
        if not os.path.lexists(m.source):
            problems.append((m.rel_path, f"{m.source} is missing"))
        elif m.source.is_symlink() or not m.source.is_file():
            problems.append((m.rel_path, f"{m.source} is not a regular file"))
        elif not _inside(m.source, source_root):
            problems.append((m.rel_path, f"{m.source} is outside {source_root}"))
        else:
            stat = m.source.stat()
            if (stat.st_size, stat.st_mtime_ns) != (m.size, m.mtime_ns):
                problems.append((m.rel_path, f"{m.source} changed since it was scanned"))
        if m.action not in WRITES:
            continue
        if os.path.lexists(m.destination):
            problems.append((m.rel_path, f"{m.destination} already exists"))
        elif not _inside(m.destination, destination_root):
            problems.append((m.rel_path, f"{m.destination} is outside {destination_root}"))
        elif m.destination in claimed:
            problems.append((m.rel_path, f"{m.destination} is also another file's destination"))
        claimed.add(m.destination)
        if m.action == CONVERT and m.member is not None and not m.member_crc32:
            problems.append((m.rel_path, f"the scan listed no CRC32 for {m.member}"))
    needed = sum(_space_needed(m) for m in plan if m.action == CONVERT)
    if needed and folder_root.is_dir():
        free = shutil.disk_usage(folder_root).free
        if free < needed:
            problems.append(("", f"the outputs need {needed} bytes; {folder_root} has {free} free"))
    return problems


# Running --------------------------------------------------------------------------


def is_conversion(kind: str, scope: str) -> bool:
    """A conversion run: one at a time across folders (the others start at once)."""
    return kind == APPLY and scope == CONVERT


def start_run(conn: sqlite3.Connection, label: str, kind: str, scope: str, total: int) -> int:
    return conn.execute(
        "INSERT INTO apply_run (folder_label, kind, scope, status, total) VALUES (?, ?, ?, ?, ?)",
        (label, kind, scope, RUNNING, total),
    ).lastrowid


def begin_run(conn: sqlite3.Connection, run_id: int) -> None:
    """The run's turn has come: it works on its files from now on (until then a conversion
    waits for another folder's)."""
    conn.execute(
        "UPDATE apply_run SET began_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
        (run_id,),
    )


def _finish_run(conn: sqlite3.Connection, run_id: int, status: str, message: str) -> None:
    conn.execute(
        "UPDATE apply_run SET status = ?, message = ?, "
        "finished_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
        (status, message, run_id),
    )


def _set_state(conn, op_id: int, state: str, error: str = "", moved=None) -> None:
    conn.execute(
        "UPDATE operation SET state = ?, error = ?, moved_mtime_ns = COALESCE(?, moved_mtime_ns), "
        "moved_size = COALESCE(?, moved_size), "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
        (
            state,
            error,
            moved.st_mtime_ns if moved else None,
            moved.st_size if moved else None,
            op_id,
        ),
    )


def carry_over(
    conn, label: str, old: str, new: str, moved, members: list[tuple], same_bytes: bool = True
) -> None:
    """Give a conversion's output (`new`) the scan rows of its original (`old`); its hash
    rows only when it holds the same ROM bytes (`same_bytes`)."""
    kind = "archive" if members else "rom"
    # A file of that name in discarded/ (an earlier conversion's original) loses its row, as
    # a rescan does when its path reappears: it is still listed in discarded/, and restoring
    # it refuses while the name is taken.
    conn.execute(
        "DELETE FROM folder_file WHERE folder_label = ? AND rel_path = ?",
        (label, new),
    )
    conn.execute(
        "INSERT INTO folder_file (folder_label, rel_path, size, mtime_ns, kind) "
        "VALUES (?, ?, ?, ?, ?)",
        (label, new, moved.st_size, moved.st_mtime_ns, kind),
    )
    for table in CARRIED:
        if table in HASH_ROWS and not same_bytes:
            continue
        columns = [
            c[1]
            for c in conn.execute(f"PRAGMA table_info({table})")
            if c[1] not in ("folder_label", "rel_path")
        ]
        listed = ", ".join(columns)
        conn.execute(
            f"INSERT OR IGNORE INTO {table} (folder_label, rel_path, {listed}) "
            f"SELECT folder_label, ?, {listed} FROM {table} "
            "WHERE folder_label = ? AND rel_path = ?",
            (new, label, old),
        )
    conn.executemany(
        "INSERT INTO archive_member VALUES (?, ?, ?, ?, ?)",
        [(label, new, *member) for member in members],
    )
    conn.execute(
        "UPDATE keep_choice SET rel_path = ? WHERE folder_label = ? AND rel_path = ?",
        (new, label, old),
    )


def _drop_output(conn, label: str, output: str, original: str) -> None:
    """A conversion's output was removed: its original takes its rows and picks back."""
    conn.execute(
        "UPDATE keep_choice SET rel_path = ? WHERE folder_label = ? AND rel_path = ?",
        (original, label, output),
    )
    conn.execute(
        "DELETE FROM manual_identity WHERE folder_label = ? AND rel_path = ?", (label, output)
    )
    conn.execute("DELETE FROM folder_file WHERE folder_label = ? AND rel_path = ?", (label, output))


def _wrapped_members(m: Move) -> list[tuple]:
    """The archive_member rows of a conversion's output (none for a bare ROM)."""
    if m.destination.suffix.lower() != conversion.ZIP_SUFFIX:
        return []
    with zipfile.ZipFile(m.destination) as z:
        return [
            (i.filename, i.file_size, format(i.CRC, CRC_FORMAT))
            for i in z.infolist()
            if not i.is_dir()
        ]


def _settle(conn, kind: str, label: str, op_id: int, m: Move, moved) -> None:
    """The step is done: record it and update where the table finds the files."""
    members = _wrapped_members(m) if m.action == CONVERT else []
    # Write lock first: runs of other folders write at the same time.
    conn.execute("BEGIN IMMEDIATE")
    try:
        _set_state(conn, op_id, DONE, moved=moved)
        if m.action == MOVE:
            place = PLACE_DISCARDED if kind == APPLY else PLACE_FOLDER
            conn.execute(
                "UPDATE folder_file SET place = ? WHERE folder_label = ? AND rel_path = ?",
                (place, label, m.rel_path),
            )
        elif m.action == CONVERT:
            carry_over(
                conn, label, m.rel_path, m.paired_rel, moved, members, m.recipe in SAME_BYTES
            )
            if m.recipe == conversion.RECIPE_DECRYPT:
                # The output is the decrypted image: only "trimmed" still holds for it.
                conn.execute(
                    "DELETE FROM file_note WHERE folder_label = ? AND rel_path = ? AND note = ?",
                    (label, m.paired_rel, cards.ENCRYPTED),
                )
                conn.execute(
                    "UPDATE card_info SET encrypted = 0, seed = 0 "
                    "WHERE folder_label = ? AND rel_path = ?",
                    (label, m.paired_rel),
                )
        elif m.action == DELETE and m.in_discarded:
            # Gone from discarded/: the table stops showing it as a discarded version.
            if m.paired_rel is not None:
                conn.execute(
                    "DELETE FROM folder_file WHERE folder_label = ? AND rel_path = ? AND place = ?",
                    (label, m.paired_rel, PLACE_DISCARDED),
                )
        elif m.action == DELETE:
            conn.execute(
                "DELETE FROM folder_file WHERE folder_label = ? AND rel_path = ? AND place = ?",
                (label, m.rel_path, PLACE_FOLDER),
            )
        elif m.action == REMOVE:
            _drop_output(conn, label, m.rel_path, m.paired_rel)
        if m.undoes is not None:
            conn.execute(
                "UPDATE operation SET state = ?, restored_by = ?, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
                (RESTORED, op_id, m.undoes),
            )
        conn.execute("COMMIT")
    except sqlite3.Error:
        conn.execute("ROLLBACK")
        raise


# Writes a conversion's output: (step) -> the output's stat. Raises moves.MoveError.
Convert = Callable[[Move], os.stat_result]


def _unchanged(m: Move) -> None:
    """Delete and remove re-check the file just before it goes; nothing can bring it back."""
    if not m.source.is_file() or m.source.is_symlink():
        raise moves.MoveError(f"{m.source} is not a regular file")
    stat = m.source.stat()
    if (stat.st_size, stat.st_mtime_ns) != (m.size, m.mtime_ns):
        raise moves.MoveError(f"{m.source} changed since the plan was made")


def _carry_out(config: ApplyConfig, convert: Convert | None, m: Move):
    if m.action == MOVE:
        return moves.move(config, m.source, m.destination)
    if m.action == CONVERT:
        if convert is None:
            raise moves.MoveError("this run cannot convert")
        return convert(m)
    _unchanged(m)
    m.source.unlink()
    moves.fsync_dir(m.source.parent)
    return None


def _files(n: int) -> str:
    return f"{n} {'file' if n == 1 else 'files'}"


def _summary(kind: str, plan: list[Move], finished: list[Move], failed: int, left: int = 0) -> str:
    """What the run did (the steps in `finished`), then how many files failed; a stopped
    conversion says so first, with the files it `left` as they were."""
    converted = sum(1 for m in finished if m.action == CONVERT)
    if left:
        done = f"stopped: {_files(converted)} converted, {left} not converted"
        return f"{done}; {failed} failed" if failed else done
    if plan and all(m.action == DELETE for m in plan):
        done = f"{_files(len(finished))} deleted"
    elif kind == APPLY and any(m.action == CONVERT for m in plan):
        done = f"{_files(converted)} converted"
    elif kind == RESTORE:
        done = f"{_files(sum(1 for m in finished if m.action == MOVE))} restored"
    else:
        done = f"{_files(len(finished))} moved to discarded/"
    return f"{done}; {failed} failed" if failed else done


def run(
    config: ApplyConfig,
    conn: sqlite3.Connection,
    run_id: int,
    label: str,
    plan: list[Move],
    convert: Convert | None = None,
    workers: int = 1,
    stop: threading.Event | None = None,
) -> None:
    """Carry out a planned run. A file that fails is left in place, its error recorded, and
    the run goes on with the others (maintainer, 2026-10-21: "run fully and report the
    errored roms"). A conversion run carries out `workers` conversions at a time, each with
    the steps that finish it. Only an unexpected error stops the run.

    Once `stop` is set, no file starts; a conversion under way is cut off and its output
    deleted (its original stays), and a file already converted finishes its steps (maintainer,
    2026-10-21: "Done rom work is kept, in-flight has its generated files deleted")."""
    try:
        _run(config, conn, run_id, label, plan, convert, workers, stop)
    except Exception as exc:  # a background run must never stay 'running'
        _finish_run(conn, run_id, FAILED, f"unexpected error: {exc!r}")
        raise


def _units(plan: list[Move]) -> list[list[Move]]:
    """The plan in pieces that run in order: a step and the steps that follow it."""
    units: list[list[Move]] = []
    for m in plan:
        if m.follows and units:
            units[-1].append(m)
        else:
            units.append([m])
    return units


def _run(config, conn, run_id: int, label: str, plan: list[Move], convert, workers, stop) -> None:
    kind = conn.execute("SELECT kind FROM apply_run WHERE id = ?", (run_id,)).fetchone()[0]
    # The connection is shared by the workers; the files are worked on outside the lock.
    lock = threading.Lock()
    finished: list[Move] = []
    failed = 0  # units (files) that failed
    stopped = False  # an unexpected error: nothing new starts
    left = 0  # files the user's stop left unconverted (not started, or cut off)
    # Restore: conversions with an original that did not come back keep their output.
    not_back: set[int] = set()

    def carry_unit(unit: list[Move]) -> None:
        nonlocal stopped
        try:
            carry_steps(unit)
        except Exception:  # a bug or a database error: run() records it
            with lock:
                stopped = True
            raise

    def carry_steps(unit: list[Move]) -> None:
        nonlocal failed, left
        converting = None  # the convert step the following steps finish
        with lock:
            if stop is not None and stop.is_set():
                left += sum(1 for m in unit if m.action == CONVERT)
                return
            if stopped:
                return  # nothing new starts; a started unit is finished below
        for m in unit:
            with lock:
                op_id = _start_step(conn, run_id, label, m, converting)
                kept = m.action == REMOVE and m.step_of in not_back
                if kept:
                    _set_state(conn, op_id, FAILED, "kept: not every original came back")
                    failed += 1
            if kept:
                return
            try:
                # Only a conversion is cut off; the steps after it finish what it began.
                with stopping.armed(
                    stop if m.action == CONVERT else None, config.stop_poll_seconds
                ):
                    moved = _carry_out(config, convert, m)
            except stopping.Stopped:
                # Cut off by the user's stop: its output is deleted, its original untouched,
                # so the step never happened and leaves no row.
                with lock:
                    conn.execute("DELETE FROM operation WHERE id = ?", (op_id,))
                    left += 1
                return
            except (moves.MoveError, OSError) as exc:
                with lock:
                    _set_state(conn, op_id, FAILED, str(exc))
                    failed += 1
                    if m.back_for is not None:
                        not_back.add(m.back_for)
                return
            with lock:
                _settle(conn, kind, label, op_id, m, moved)
                finished.append(m)
            if m.action == CONVERT:
                converting = op_id

    units = _units(plan)
    # Restores never convert, so they run in order: a remove after its originals.
    if workers > 1 and any(m.action == CONVERT for m in plan):
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="g1r-convert") as pool:
            for future in [pool.submit(carry_unit, unit) for unit in units]:
                future.result()
    else:
        for unit in units:
            carry_unit(unit)
    _finish_run(
        conn, run_id, FAILED if failed else DONE, _summary(kind, plan, finished, failed, left)
    )


def _start_step(conn, run_id: int, label: str, m: Move, converting: int | None) -> int:
    """Journal the step as started, before its file is touched."""
    return conn.execute(
        "INSERT INTO operation (run_id, folder_label, rel_path, group_key, reason, source, "
        "destination, size, mtime_ns, state, action, step_of) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            run_id,
            label,
            m.rel_path,
            m.group_key,
            m.reason,
            str(m.source),
            str(m.destination) if m.destination else "",
            m.size,
            m.mtime_ns,
            STARTED,
            m.action,
            converting if m.follows else m.step_of,
        ),
    ).lastrowid


def progress(conn: sqlite3.Connection, run_id: int) -> dict | None:
    run_row = conn.execute("SELECT * FROM apply_run WHERE id = ?", (run_id,)).fetchone()
    if run_row is None:
        return None
    states = dict(
        conn.execute(
            "SELECT state, COUNT(*) FROM operation WHERE run_id = ? GROUP BY state", (run_id,)
        ).fetchall()
    )
    failed = conn.execute(
        "SELECT rel_path, error, action FROM operation WHERE run_id = ? AND state = ?",
        (run_id, FAILED),
    ).fetchall()
    return {
        **dict(run_row),
        "stopping": bool(run_row["stopping"]),
        "done": states.get(DONE, 0) + states.get(RESTORED, 0),
        "failed": [dict(r) for r in failed],
        "waiting_for": waiting_for(conn, run_row),
    }


def waiting_for(conn: sqlite3.Connection, run_row: sqlite3.Row) -> str | None:
    """For a conversion not begun yet: the folder whose conversion it waits for ("" when that
    one has just ended and this one is about to begin). None for any other run."""
    if run_row["status"] != RUNNING or run_row["began_at"] is not None:
        return None
    if not is_conversion(run_row["kind"], run_row["scope"]):
        return None
    ahead = conn.execute(
        "SELECT folder_label FROM apply_run WHERE status = ? AND kind = ? AND scope = ? "
        "AND began_at IS NOT NULL AND id != ? ORDER BY id LIMIT 1",
        (RUNNING, APPLY, CONVERT, run_row["id"]),
    ).fetchone()
    return ahead["folder_label"] if ahead else ""


def latest_run(conn: sqlite3.Connection, label: str) -> dict | None:
    row = conn.execute(
        "SELECT id FROM apply_run WHERE folder_label = ? ORDER BY id DESC LIMIT 1", (label,)
    ).fetchone()
    return progress(conn, row[0]) if row else None


def last_conversion_end(conn: sqlite3.Connection, label: str) -> str | None:
    """When the folder's latest finished conversion run ended (its outputs are identified by
    the next scan), or None."""
    row = conn.execute(
        "SELECT finished_at FROM apply_run WHERE folder_label = ? AND kind = ? AND scope = ? "
        "AND finished_at IS NOT NULL ORDER BY id DESC LIMIT 1",
        (label, APPLY, CONVERT),
    ).fetchone()
    return row["finished_at"] if row else None


def failed_conversions(conn: sqlite3.Connection, label: str) -> set[str]:
    """The files the folder's latest finished conversion could not convert (they may be set
    aside to discarded/)."""
    rows = conn.execute(
        "SELECT o.rel_path FROM operation o WHERE o.action = ? AND o.state = ? AND o.run_id = "
        "(SELECT id FROM apply_run WHERE folder_label = ? AND kind = ? AND scope = ? "
        "AND finished_at IS NOT NULL ORDER BY id DESC LIMIT 1)",
        (CONVERT, FAILED, label, APPLY, CONVERT),
    )
    return {r["rel_path"] for r in rows}


def running_conversion(conn: sqlite3.Connection, label: str) -> dict | None:
    """The folder's conversion while it runs: steps finished (failed ones too) of the
    planned total, how many files failed so far, whether a stop was asked for, and the folder
    whose conversion it waits for while not begun (`waiting_for`). None when no conversion
    runs."""
    run_row = conn.execute(
        "SELECT * FROM apply_run WHERE folder_label = ? AND kind = ? "
        "AND scope = ? AND status = ? ORDER BY id DESC LIMIT 1",
        (label, APPLY, CONVERT, RUNNING),
    ).fetchone()
    if run_row is None:
        return None
    finished, failed = conn.execute(
        "SELECT COALESCE(SUM(state != ?), 0), COALESCE(SUM(state = ? AND action = ?), 0) "
        "FROM operation WHERE run_id = ?",
        (STARTED, FAILED, CONVERT, run_row["id"]),
    ).fetchone()
    return {
        "done": finished,
        "total": run_row["total"],
        "failed": failed,
        "stopping": bool(run_row["stopping"]),
        "waiting_for": waiting_for(conn, run_row),
    }


def ask_stop(conn: sqlite3.Connection, label: str) -> int | None:
    """Mark the folder's running conversion as stopping; its id, or None when none runs."""
    row = conn.execute(
        "SELECT id FROM apply_run WHERE folder_label = ? AND kind = ? AND scope = ? "
        "AND status = ? ORDER BY id DESC LIMIT 1",
        (label, APPLY, CONVERT, RUNNING),
    ).fetchone()
    if row is None:
        return None
    conn.execute("UPDATE apply_run SET stopping = 1 WHERE id = ?", (row["id"],))
    return row["id"]


def failed_operations(conn: sqlite3.Connection, label: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM operation WHERE folder_label = ? AND state = ? ORDER BY id",
        (label, FAILED),
    ).fetchall()


# Start-up recovery ----------------------------------------------------------------


def recover(config: ApplyConfig, conn: sqlite3.Connection) -> int:
    """Settle every step a restart cut off; return how many there were."""
    pending = conn.execute(
        "SELECT o.*, r.kind, r.scope FROM operation o JOIN apply_run r ON r.id = o.run_id "
        "WHERE o.state = ?",
        (STARTED,),
    ).fetchall()
    for op in pending:
        m = _step_of_row(conn, op)
        if m.destination is not None:
            moves.temp_path(config, m.destination).unlink(missing_ok=True)
            shutil.rmtree(moves.work_path(config, m.destination), ignore_errors=True)
        outcome = _recovered(config, m)
        if outcome is None:
            settled = m.destination.stat() if m.action in WRITES else None
            _settle(conn, op["kind"], op["folder_label"], op["id"], m, settled)
        else:
            _set_state(conn, op["id"], FAILED, outcome)
    for run_row in conn.execute("SELECT id FROM apply_run WHERE status = ?", (RUNNING,)).fetchall():
        _finish_run(conn, run_row[0], FAILED, "interrupted by a restart; settled at start-up")
    return len(pending)


def _step_of_row(conn: sqlite3.Connection, op: sqlite3.Row) -> Move:
    """Rebuild a journalled step, as far as settling it needs."""
    source = Path(op["source"])
    destination = Path(op["destination"]) if op["destination"] else None
    paired = undoes = None
    if op["action"] == CONVERT:
        paired = destination.relative_to(_root_of(op)).as_posix()
    elif op["action"] == REMOVE:
        undoes = op["step_of"]
        row = conn.execute("SELECT rel_path FROM operation WHERE id = ?", (undoes,)).fetchone()
        paired = row[0] if row else None
    elif op["action"] == MOVE:
        undoes = _undone_by_restore(conn, op)
    elif op["action"] == DELETE and op["scope"] == SCOPE_EMPTY and op["step_of"]:
        row = conn.execute(
            "SELECT rel_path FROM operation WHERE id = ?", (op["step_of"],)
        ).fetchone()
        paired = row[0] if row else None
    return Move(
        op["rel_path"],
        op["group_key"],
        op["reason"],
        source,
        destination,
        op["size"],
        op["mtime_ns"],
        undoes=undoes,
        action=op["action"],
        paired_rel=paired,
        in_discarded=op["scope"] == SCOPE_EMPTY,
    )


def _recovered(config: ApplyConfig, m: Move) -> str | None:
    """None when the step turns out finished (or is finished now); otherwise why it failed."""
    has_source = m.source.exists()
    if m.action == DELETE:
        # Deleting cannot be undone, so a cut-off delete keeps the file rather than finish.
        return None if not has_source else "interrupted before deleting; the file is still there"
    if m.action == REMOVE:
        if not has_source:
            return None
        try:
            _unchanged(m)
        except moves.MoveError as exc:
            return f"interrupted before {m.source} was removed, and it changed since: {exc}"
        m.source.unlink()
        return None
    has_destination = m.destination.exists()
    if m.action == CONVERT:
        # The output is only given its name once verified, so a named output is a good one.
        if has_destination:
            return None
        return "interrupted before the output was written; nothing changed"
    if has_destination and not has_source:
        return None
    if has_source and not has_destination:
        return "interrupted before the move; nothing changed"
    if has_source and has_destination and moves.same_file(config, m.source, m.destination):
        m.source.unlink()
        return None
    if has_source:
        return (
            f"interrupted with different files at {m.source} and {m.destination}; "
            "both left in place"
        )
    return f"neither {m.source} nor {m.destination} exists"


def _undone_by_restore(conn: sqlite3.Connection, op: sqlite3.Row) -> int | None:
    """For a restore cut off by a restart: the apply operation it was undoing."""
    if op["kind"] != RESTORE or op["action"] != MOVE:
        return None
    row = conn.execute(
        "SELECT id FROM operation WHERE folder_label = ? AND rel_path = ? AND state = ? "
        "AND action = 'move' AND destination = ? AND id < ? ORDER BY id DESC LIMIT 1",
        (op["folder_label"], op["rel_path"], DONE, op["source"], op["id"]),
    ).fetchone()
    return row[0] if row else None
