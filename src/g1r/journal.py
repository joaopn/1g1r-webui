"""Apply and restore, journalled (design §8).

A plan is a list of moves built from the reviewed proposals. Its token fingerprints every
move with the file's size and mtime as scanned, so applying refuses when the plan changed
after review. Each move is written to the journal as 'started' and committed before the
file is touched; start-up recovery settles any move a restart cut off.
"""

import hashlib
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from g1r import moves
from g1r.config import ApplyConfig

# The discarded/ subfolder of 1G1R moves (matching.REASON_DISCARDED names the same one).
REASON_1G1R = "1g1r"

PLACE_FOLDER = "folder"
PLACE_DISCARDED = "discarded"

APPLY = "apply"
RESTORE = "restore"

RUNNING = "running"
DONE = "done"
FAILED = "failed"

STARTED = "started"
RESTORED = "restored"


class PlanError(RuntimeError):
    """The plan cannot run; the message (and per-file problems) are shown to the user."""

    def __init__(self, message: str, problems: list[tuple[str, str]] | None = None):
        super().__init__(message)
        self.problems = problems or []


@dataclass(frozen=True)
class Move:
    rel_path: str
    group_key: str
    reason: str
    source: Path
    destination: Path
    size: int
    mtime_ns: int
    # Restore only: the apply operation this move undoes.
    undoes: int | None = None


def token(plan: list[Move]) -> str:
    digest = hashlib.sha1()
    for m in plan:
        digest.update(f"{m.source}\0{m.destination}\0{m.size}\0{m.mtime_ns}\n".encode())
    return digest.hexdigest()


def busy(conn: sqlite3.Connection, label: str) -> str | None:
    """Why the folder cannot start an apply or a scan now, or None."""
    if conn.execute(
        "SELECT 1 FROM scan WHERE folder_label = ? AND status = 'running'", (label,)
    ).fetchone():
        return "a scan of this folder is already running"
    if conn.execute(
        "SELECT 1 FROM apply_run WHERE folder_label = ? AND status = ?", (label, RUNNING)
    ).fetchone():
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
                    REASON_1G1R,
                    root / f["rel_path"],
                    Path(row.operation),
                    f["size"],
                    f["mtime_ns"],
                )
            )
    plan.sort(key=lambda m: m.rel_path)
    return plan


def active_discards(conn: sqlite3.Connection, label: str) -> list[sqlite3.Row]:
    """Apply operations whose file is in discarded/ now (moved and not restored)."""
    return conn.execute(
        "SELECT o.* FROM operation o JOIN apply_run r ON r.id = o.run_id "
        "WHERE o.folder_label = ? AND r.kind = ? AND o.state = ? ORDER BY o.rel_path",
        (label, APPLY, DONE),
    ).fetchall()


def plan_restore(
    conn: sqlite3.Connection,
    label: str,
    *,
    operation_ids: list[int] | None = None,
    group_key: str | None = None,
) -> list[Move]:
    plan = []
    for op in active_discards(conn, label):
        if operation_ids is not None and op["id"] not in operation_ids:
            continue
        if group_key is not None and op["group_key"] != group_key:
            continue
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
            )
        )
    if operation_ids is not None and len(plan) != len(set(operation_ids)):
        raise PlanError("some of these files are not in discarded/ (already restored?)")
    return plan


# Preflight ------------------------------------------------------------------------


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def preflight(plan: list[Move], source_root: Path, destination_root: Path) -> list[tuple[str, str]]:
    """Every reason the plan must not run, per file. Empty means it may run."""
    problems = []
    for m in plan:
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
        if os.path.lexists(m.destination):
            problems.append((m.rel_path, f"{m.destination} already exists"))
        elif not _inside(m.destination, destination_root):
            problems.append((m.rel_path, f"{m.destination} is outside {destination_root}"))
    return problems


# Running --------------------------------------------------------------------------


def start_run(conn: sqlite3.Connection, label: str, kind: str, scope: str, total: int) -> int:
    return conn.execute(
        "INSERT INTO apply_run (folder_label, kind, scope, status, total) VALUES (?, ?, ?, ?, ?)",
        (label, kind, scope, RUNNING, total),
    ).lastrowid


def _finish_run(conn: sqlite3.Connection, run_id: int, status: str, message: str) -> None:
    conn.execute(
        "UPDATE apply_run SET status = ?, message = ?, "
        "finished_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
        (status, message, run_id),
    )


def _set_state(conn, op_id: int, state: str, error: str = "", moved=None) -> None:
    conn.execute(
        "UPDATE operation SET state = ?, error = ?, moved_mtime_ns = COALESCE(?, moved_mtime_ns), "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
        (state, error, moved.st_mtime_ns if moved else None, op_id),
    )


def _settle(conn, kind: str, label: str, op_id: int, m: Move, moved) -> None:
    """The file is at its destination: record it and update where the table finds it."""
    conn.execute("BEGIN")
    try:
        _set_state(conn, op_id, DONE, moved=moved)
        place = PLACE_DISCARDED if kind == APPLY else PLACE_FOLDER
        conn.execute(
            "UPDATE folder_file SET place = ? WHERE folder_label = ? AND rel_path = ?",
            (place, label, m.rel_path),
        )
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


def run(
    config: ApplyConfig, conn: sqlite3.Connection, run_id: int, label: str, plan: list[Move]
) -> None:
    """Carry out a planned run; stops at the first failure, leaving that file in place."""
    try:
        _run(config, conn, run_id, label, plan)
    except Exception as exc:  # a background run must never stay 'running'
        _finish_run(conn, run_id, FAILED, f"unexpected error: {exc!r}")
        raise


def _run(config, conn, run_id: int, label: str, plan: list[Move]) -> None:
    kind = conn.execute("SELECT kind FROM apply_run WHERE id = ?", (run_id,)).fetchone()[0]
    done = 0
    for m in plan:
        op_id = conn.execute(
            "INSERT INTO operation (run_id, folder_label, rel_path, group_key, reason, source, "
            "destination, size, mtime_ns, state) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                label,
                m.rel_path,
                m.group_key,
                m.reason,
                str(m.source),
                str(m.destination),
                m.size,
                m.mtime_ns,
                STARTED,
            ),
        ).lastrowid
        try:
            moved = moves.move(config, m.source, m.destination)
        except (moves.MoveError, OSError) as exc:
            _set_state(conn, op_id, FAILED, str(exc))
            _finish_run(conn, run_id, FAILED, f"stopped after {done} of {len(plan)} files: {exc}")
            return
        _settle(conn, kind, label, op_id, m, moved)
        done += 1
    verb = "moved to discarded/" if kind == APPLY else "restored"
    _finish_run(conn, run_id, DONE, f"{done} {'file' if done == 1 else 'files'} {verb}")


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
        "SELECT rel_path, error FROM operation WHERE run_id = ? AND state = ?", (run_id, FAILED)
    ).fetchall()
    return {
        **dict(run_row),
        "done": states.get(DONE, 0) + states.get(RESTORED, 0),
        "failed": [dict(r) for r in failed],
    }


def latest_run(conn: sqlite3.Connection, label: str) -> dict | None:
    row = conn.execute(
        "SELECT id FROM apply_run WHERE folder_label = ? ORDER BY id DESC LIMIT 1", (label,)
    ).fetchone()
    return progress(conn, row[0]) if row else None


def failed_operations(conn: sqlite3.Connection, label: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM operation WHERE folder_label = ? AND state = ? ORDER BY id",
        (label, FAILED),
    ).fetchall()


# Start-up recovery ----------------------------------------------------------------


def recover(config: ApplyConfig, conn: sqlite3.Connection) -> int:
    """Settle every move a restart cut off; return how many there were."""
    pending = conn.execute(
        "SELECT o.*, r.kind FROM operation o JOIN apply_run r ON r.id = o.run_id WHERE o.state = ?",
        (STARTED,),
    ).fetchall()
    for op in pending:
        source, destination = Path(op["source"]), Path(op["destination"])
        moves.temp_path(config, destination).unlink(missing_ok=True)
        m = Move(
            op["rel_path"],
            op["group_key"],
            op["reason"],
            source,
            destination,
            op["size"],
            op["mtime_ns"],
            undoes=_undone_by_restore(conn, op),
        )
        has_source, has_destination = source.exists(), destination.exists()
        if has_destination and not has_source:
            _settle(conn, op["kind"], op["folder_label"], op["id"], m, destination.stat())
        elif has_source and not has_destination:
            _set_state(conn, op["id"], FAILED, "interrupted before the move; nothing changed")
        elif has_source and has_destination and moves.same_file(config, source, destination):
            source.unlink()
            _settle(conn, op["kind"], op["folder_label"], op["id"], m, destination.stat())
        elif has_source:
            _set_state(
                conn,
                op["id"],
                FAILED,
                f"interrupted with different files at {source} and {destination}; "
                "both left in place",
            )
        else:
            _set_state(conn, op["id"], FAILED, f"neither {source} nor {destination} exists")
    for run_row in conn.execute("SELECT id FROM apply_run WHERE status = ?", (RUNNING,)).fetchall():
        _finish_run(conn, run_row[0], FAILED, "interrupted by a restart; settled at start-up")
    return len(pending)


def _undone_by_restore(conn: sqlite3.Connection, op: sqlite3.Row) -> int | None:
    """For a restore cut off by a restart: the apply operation it was undoing."""
    if op["kind"] != RESTORE:
        return None
    row = conn.execute(
        "SELECT id FROM operation WHERE folder_label = ? AND rel_path = ? AND state = ? "
        "AND destination = ? AND id < ? ORDER BY id DESC LIMIT 1",
        (op["folder_label"], op["rel_path"], DONE, op["source"], op["id"]),
    ).fetchone()
    return row[0] if row else None
