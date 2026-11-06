"""Warnings for a folder's Home card (design §3): things to look at before any apply."""

import sqlite3
from collections.abc import Iterable
from pathlib import Path

from g1r import conversion, hasheous, matching, scanner

WARN = "warn"
BAD = "bad"
# A hint, not a problem: shown small, with a link to where it is acted on.
INFO = "info"
LOOKUPS_PAGE = "/settings/lookups"


def changes(conn: sqlite3.Connection, label: str) -> list[int]:
    """The folder's change counter and the DATs' (table `folder_change`, kept by triggers)."""
    found = dict(
        conn.execute(
            "SELECT folder_label, n FROM folder_change WHERE folder_label IN (?, '')", (label,)
        ).fetchall()
    )
    return [found.get(label, 0), found.get("", 0)]


def _dat_changed(scan: sqlite3.Row | None, dat: sqlite3.Row | None) -> bool:
    """The last scan finished with another DAT than the active one."""
    return (
        scan is not None
        and scan["status"] == "done"
        and dat is not None
        and bool(scan["dat_sha1"])
        and scan["dat_sha1"] != dat["sha1"]
    )


def needs(
    last: sqlite3.Row | None,
    scanned: sqlite3.Row | None,
    dat: sqlite3.Row | None,
    converted_at: str | None,
    unscanned: int = 0,
) -> str | None:
    """What the set waits for (Home's "Needs scanning" badge, one for both): a check
    (`scanner.CHECK`) before any run or after a failed one; a scan (`scanner.IDENTIFY`) when
    it was never scanned, the last scan failed, the active DAT changed since, a conversion
    ended after the scan began (its outputs are identified by a scan), or a check listed ROM
    files no scan has read yet (`unscanned`: new or changed ones). None while a run is under
    way, or when nothing is due. `last`: the latest run of either kind; `scanned`: the latest
    scan."""
    if last is None:
        return scanner.CHECK
    if last["status"] == "running":
        return None
    if last["status"] == "failed":
        return scanner.CHECK if last["kind"] == scanner.CHECK else scanner.IDENTIFY
    if scanned is None or scanned["status"] == "failed" or _dat_changed(scanned, dat):
        return scanner.IDENTIFY
    if converted_at is not None and converted_at >= scanned["started_at"]:
        return scanner.IDENTIFY
    if unscanned:
        return scanner.IDENTIFY
    return None


def warnings(
    conn: sqlite3.Connection,
    label: str,
    *,
    location: str | None,
    platform_short: str,
    scan: sqlite3.Row | None,
    dat: sqlite3.Row | None,
    unmatched: int = 0,
    hasheous_offered: bool = False,
    unreadable_updates: int = 0,
) -> list[dict]:
    """`hasheous_offered`: Hasheous is switched off, so it is not looking files up.
    `unreadable_updates`: updates (Switch) whose version could not be read, without
    prod.keys."""
    found: list[dict] = []

    def add(level: str, text: str, link: dict | None = None) -> None:
        found.append({"level": level, "text": text, "link": link})

    if location is not None and not Path(location).is_dir():
        add(BAD, f"The folder {location} no longer exists.")
    if scan is not None and scan["status"] == "failed":
        add(BAD, f"The last scan failed: {scan['message']}")
    if _dat_changed(scan, dat):
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
    # Only files still in the folder and unmatched: the answer stays stored after a file is
    # matched by hand or moved to discarded/, and those leave nothing to look at.
    elsewhere = conn.execute(
        """SELECT COUNT(*) FROM lookup_result l
           JOIN folder_file f USING (folder_label, rel_path)
           WHERE l.folder_label = ? AND l.service = ? AND l.status = ? AND f.place = 'folder'
             AND NOT EXISTS (SELECT 1 FROM identity i
                             WHERE i.folder_label = l.folder_label AND i.rel_path = l.rel_path)""",
        (label, hasheous.SERVICE, hasheous.OTHER_PLATFORM),
    ).fetchone()[0]
    if elsewhere:
        add(
            WARN,
            f"Hasheous knows {_files(elsewhere)} for another platform.",
            {"to": f"/folders/{label}/matching?view=unmatched", "text": "Show them"},
        )
    last = conn.execute(
        "SELECT kind, status, message FROM apply_run WHERE folder_label = ? "
        "ORDER BY id DESC LIMIT 1",
        (label,),
    ).fetchone()
    if last is not None and last["status"] == "failed":
        add(BAD, f"The last {last['kind']} failed: {last['message']}")
    if unmatched and hasheous_offered:
        add(
            INFO,
            f"Unmatched: {_files(unmatched)}. Hasheous may identify some.",
            {"to": LOOKUPS_PAGE, "text": "Switch on Hasheous"},
        )
    if unreadable_updates:
        add(
            INFO,
            f"{_updates(unreadable_updates)} without a readable version.",
            {"to": f"/folders/{label}/updates", "text": "Add prod.keys"},
        )
    return found


def _updates(n: int) -> str:
    return f"{n} update" if n == 1 else f"{n} updates"


def _files(n: int) -> str:
    return f"{n} file" if n == 1 else f"{n} files"


def progress(
    rom_paths: Iterable[str],
    games: list[matching.GameRow],
    conversion_rows: list[conversion.ConversionRow],
    unmatched_paths: Iterable[str],
) -> dict[str, int]:
    """ROM files with nothing left to do, and the rest, split by what is left.

    A file is left to match when it is unmatched or belongs to a game still undecided or
    with a move proposed, and left to convert when it waits for a conversion (or a look at
    a flagged one). A file can be left for both, so the two may add up to more than
    `to_process`.
    """
    to_match = set(unmatched_paths)
    for game in games:
        if game.has_proposals or game.status == matching.STATUS_UNDECIDED:
            to_match.update(r.version.rel_path for r in game.rows)
    to_convert: set[str] = set()
    for row in conversion_rows:
        if row.status in conversion.CONVERTING or row.status == conversion.FLAGGED:
            to_convert.update([row.rel_path, *row.parts])
    roms = set(rom_paths)
    to_process = len(roms & (to_match | to_convert))
    return {
        "processed": len(roms) - to_process,
        "to_process": to_process,
        "to_match": len(roms & to_match),
        "to_convert": len(roms & to_convert),
    }
