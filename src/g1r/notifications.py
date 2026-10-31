"""The notifications panel: the latest scans and runs of every folder, newest first."""

import sqlite3

from g1r import journal

SCAN = "scan"
# A Check files run (scan.kind 'check'): listed as a scan, titled apart.
CHECK = "check"
RUN = "run"
TABLES = {SCAN: "scan", RUN: "apply_run"}

# What a run was, from its kind and scope (a 1G1R apply's scope is a group key or '').
CONVERSION = "conversion"
APPLY_1G1R = "1g1r"
# Renames to a template, and their reverts (a restore of scope rename).
RENAME = "rename"
RENAME_BACK = "rename-back"
# Files moved to their game's folders, and back (a restore of scope organize).
ORGANIZE = "organize"
ORGANIZE_BACK = "organize-back"
TITLES = {
    SCAN: "Scan",
    CHECK: "Check files",
    CONVERSION: "Conversion",
    APPLY_1G1R: "1G1R apply",
    journal.SCOPE_UNMATCHED: "Unmatched files",
    journal.SCOPE_EMPTY: "Empty discarded/",
    journal.SCOPE_SET_ASIDE: "Moved to discarded/",
    journal.SCOPE_UPDATES: "Older updates",
    journal.RESTORE: "Restore",
    RENAME: "Rename",
    RENAME_BACK: "Names given back",
    ORGANIZE: "Game folders",
    ORGANIZE_BACK: "Folders given back",
}


def _run_kind(row: sqlite3.Row) -> str:
    if row["scope"] == journal.SCOPE_RENAME:
        return RENAME_BACK if row["kind"] == journal.RESTORE else RENAME
    if row["scope"] == journal.SCOPE_ORGANIZE:
        return ORGANIZE_BACK if row["kind"] == journal.RESTORE else ORGANIZE
    if row["kind"] == journal.RESTORE:
        return journal.RESTORE
    if row["scope"] == journal.CONVERT:
        return CONVERSION
    if row["scope"] in (
        journal.SCOPE_UNMATCHED,
        journal.SCOPE_EMPTY,
        journal.SCOPE_SET_ASIDE,
        journal.SCOPE_UPDATES,
    ):
        return row["scope"]
    return APPLY_1G1R


def _scan_item(row: sqlite3.Row) -> dict:
    return {
        "id": f"{SCAN}-{row['id']}",
        "kind": CHECK if row["kind"] == CHECK else SCAN,
        "title": TITLES[CHECK if row["kind"] == CHECK else SCAN],
        "folder_label": row["folder_label"],
        "status": row["status"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "message": row["message"] or "",
        "stage": row["stage"],
        "done": row["files_done"],
        "total": row["files_total"],
        "failed": 0,
    }


def _run_item(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    run = journal.progress(conn, row["id"]) or {}
    kind = _run_kind(row)
    return {
        "id": f"{RUN}-{row['id']}",
        "kind": kind,
        "title": TITLES[kind],
        "folder_label": row["folder_label"],
        "status": row["status"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "message": row["message"],
        "stage": None,
        "done": run.get("done"),
        "total": row["total"],
        "failed": len(run.get("failed", [])),
    }


def feed(conn: sqlite3.Connection, limit: int) -> list[dict]:
    """The `limit` latest scans and runs not cleared, newest start first."""
    scans = conn.execute(
        "SELECT * FROM scan WHERE dismissed = 0 ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    runs = conn.execute(
        "SELECT * FROM apply_run WHERE dismissed = 0 ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    items = [_scan_item(r) for r in scans] + [_run_item(conn, r) for r in runs]
    # Ids break ties between rows started in the same second.
    items.sort(key=lambda i: (i["started_at"], int(i["id"].split("-")[1])), reverse=True)
    return items[:limit]


def parse_id(item_id: str) -> tuple[str, int] | None:
    table, _, number = item_id.partition("-")
    if table not in TABLES or not number.isdigit():
        return None
    return TABLES[table], int(number)


def clear(conn: sqlite3.Connection, item_id: str | None = None) -> int:
    """Dismiss one finished item, or every finished one; a running one stays listed."""
    if item_id is not None:
        parsed = parse_id(item_id)
        if parsed is None:
            return 0
        table, number = parsed
        return conn.execute(
            f"UPDATE {table} SET dismissed = 1 WHERE id = ? AND dismissed = 0 AND status != ?",
            (number, journal.RUNNING),
        ).rowcount
    return sum(
        conn.execute(
            f"UPDATE {table} SET dismissed = 1 WHERE dismissed = 0 AND status != ?",
            (journal.RUNNING,),
        ).rowcount
        for table in TABLES.values()
    )
