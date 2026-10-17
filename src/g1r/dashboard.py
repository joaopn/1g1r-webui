"""Warnings for a folder's Home card (design §3): things to look at before any apply."""

import sqlite3
from pathlib import Path

from g1r import hasheous

WARN = "warn"
BAD = "bad"


def warnings(
    conn: sqlite3.Connection,
    label: str,
    *,
    location: str | None,
    platform_short: str,
    scan: sqlite3.Row | None,
    dat: sqlite3.Row | None,
) -> list[dict]:
    found: list[dict] = []

    def add(level: str, text: str) -> None:
        found.append({"level": level, "text": text})

    if location is not None and not Path(location).is_dir():
        add(BAD, f"The folder {location} no longer exists.")
    if scan is not None and scan["status"] == "failed":
        add(BAD, f"The last scan failed: {scan['message']}")
    if scan is not None and scan["status"] == "done" and dat is not None and scan["dat_sha1"]:
        if scan["dat_sha1"] != dat["sha1"]:
            add(WARN, "The active DAT changed since the last scan. Rescan to use it.")

    foreign = conn.execute(
        "SELECT COUNT(*) FROM folder_file WHERE folder_label = ? AND kind = 'other' "
        "AND place = 'folder'",
        (label,),
    ).fetchone()[0]
    if foreign:
        add(
            WARN,
            f"Not {platform_short} ROMs or archives: {_files(foreign)}. "
            "A folder holds one platform.",
        )
    elsewhere = conn.execute(
        "SELECT COUNT(*) FROM lookup_result WHERE folder_label = ? AND service = ? AND status = ?",
        (label, hasheous.SERVICE, hasheous.OTHER_PLATFORM),
    ).fetchone()[0]
    if elsewhere:
        add(WARN, f"Hasheous knows {_files(elsewhere)} for another platform.")
    last = conn.execute(
        "SELECT kind, status, message FROM apply_run WHERE folder_label = ? "
        "ORDER BY id DESC LIMIT 1",
        (label,),
    ).fetchone()
    if last is not None and last["status"] == "failed":
        add(BAD, f"The last {last['kind']} failed: {last['message']}")
    return found


def _files(n: int) -> str:
    return f"{n} file" if n == 1 else f"{n} files"
