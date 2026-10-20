"""Warnings for a folder's Home card (design §3): things to look at before any apply."""

import sqlite3
from collections.abc import Iterable
from pathlib import Path

from g1r import conversion, hasheous, matching

WARN = "warn"
BAD = "bad"
# A hint, not a problem: shown small, with a link to where it is acted on.
INFO = "info"
LOOKUPS_PAGE = "/settings/lookups"


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
) -> list[dict]:
    """`hasheous_offered`: Hasheous is switched off, so it is not looking files up."""
    found: list[dict] = []

    def add(level: str, text: str, link: dict | None = None) -> None:
        found.append({"level": level, "text": text, "link": link})

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
    if unmatched and hasheous_offered:
        add(
            INFO,
            f"Unmatched: {_files(unmatched)}. Hasheous may identify some.",
            {"to": LOOKUPS_PAGE, "text": "Switch on Hasheous"},
        )
    return found


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
