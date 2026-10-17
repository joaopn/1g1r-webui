"""The conversion part: what each file of a folder would become under its platform's target.

Proposals only: nothing here touches a file. Every proposal is lossless by construction
(wrap a ROM in a zip, or take it out of one) and names the check that would prove it.
"""

import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from g1r.config import PLAIN, Settings, TargetConfig

REASON_ORIGINALS = "originals"

DONE = "done"
ACCEPTED = "accepted"
WRAP = "wrap"
UNWRAP = "unwrap"
FLAGGED = "flagged"
STATUSES = (WRAP, UNWRAP, FLAGGED, ACCEPTED, DONE)
CONVERTING = (WRAP, UNWRAP)
# The only archive the app writes; other targets are listed but never produced here.
ZIP = "zip"
ZIP_SUFFIX = f".{ZIP}"


@dataclass
class ConversionRow:
    rel_path: str
    size: int
    container: str
    members: list[dict] = field(default_factory=list)
    status: str = DONE
    output: str | None = None
    originals_to: str | None = None
    reversible: bool = True
    verify: str | None = None
    note: str = ""


def container_of(rel_path: str, kind: str) -> str:
    return PurePosixPath(rel_path).suffix.lower().lstrip(".") if kind == "archive" else PLAIN


def originals_path(settings: Settings, label: str, rel_path: str) -> str:
    return str(PurePosixPath(settings.paths.discarded_root, label, REASON_ORIGINALS, rel_path))


def rows(
    settings: Settings,
    conn: sqlite3.Connection,
    label: str,
    platform: str,
    target: TargetConfig,
    *,
    delete_originals: bool,
) -> list[ConversionRow]:
    rom_extensions = {e.lower() for e in settings.platforms.profiles[platform].rom_extensions}
    files = conn.execute(
        "SELECT rel_path, size, kind FROM folder_file WHERE folder_label = ? "
        "AND kind IN ('rom', 'archive') AND place = 'folder' ORDER BY rel_path",
        (label,),
    ).fetchall()
    members: dict[str, list[dict]] = {}
    for m in conn.execute(
        "SELECT rel_path, member, size, crc32 FROM archive_member WHERE folder_label = ? "
        "ORDER BY rel_path, member",
        (label,),
    ):
        members.setdefault(m["rel_path"], []).append(
            {"name": m["member"], "size": m["size"], "crc32": m["crc32"]}
        )
    problems = dict(
        conn.execute(
            "SELECT rel_path, message FROM archive_problem WHERE folder_label = ?", (label,)
        ).fetchall()
    )
    # Discarded rows count too: an output may not take the name of a file in discarded/.
    existing = {
        r[0].lower()
        for r in conn.execute("SELECT rel_path FROM folder_file WHERE folder_label = ?", (label,))
    }

    def is_rom(name: str) -> bool:
        return PurePosixPath(name).suffix.lower().lstrip(".") in rom_extensions

    planned: set[str] = set()
    result = []
    for f in files:
        rel = f["rel_path"]
        row = ConversionRow(rel, f["size"], container_of(rel, f["kind"]), members.get(rel, []))
        roms = [m for m in row.members if is_rom(m["name"])]
        if rel in problems:
            row.status, row.note = FLAGGED, problems[rel]
        elif row.container != PLAIN and len(roms) != 1:
            row.status = FLAGGED
            row.note = (
                "no ROM file inside"
                if not roms
                else f"{len(roms)} ROM files in one archive; split it by hand"
            )
        elif row.container == target.produces:
            row.status = DONE
        elif row.container in target.accepts:
            row.status, row.note = ACCEPTED, f"{row.container} is accepted as it is"
        else:
            _propose(settings, label, target, row, roms, delete_originals, existing | planned)
            if row.output:
                planned.add(row.output.lower())
        result.append(row)
    return result


def _propose(settings, label, target, row, roms, delete_originals, existing) -> None:
    parent = PurePosixPath(row.rel_path).parent
    if target.produces == PLAIN:
        member = roms[0]
        row.status = UNWRAP
        row.output = str(parent / PurePosixPath(member["name"]).name)
        row.verify = f"CRC32 {member['crc32']} and size {member['size']} of the extracted file"
        extras = len(row.members) - len(roms)
        if extras:
            row.note = f"{extras} other file(s) in the archive stay in the original"
    elif target.produces != ZIP:
        row.status, row.note = FLAGGED, f"the app cannot write {target.produces} archives"
        return
    else:
        row.status = WRAP
        row.output = str(parent / f"{PurePosixPath(row.rel_path).stem}.{target.produces}")
        row.verify = f"CRC32 and size of the zipped member equal the file's ({row.size} bytes)"
    if row.output.lower() in existing:
        row.status, row.note = FLAGGED, f"{row.output} already exists or is another file's output"
        row.output = row.verify = None
        return
    if delete_originals:
        row.reversible = False
    else:
        row.originals_to = originals_path(settings, label, row.rel_path)


def counts(conversion_rows: list[ConversionRow]) -> dict[str, int]:
    found = Counter(r.status for r in conversion_rows)
    return {s: found.get(s, 0) for s in STATUSES} | {
        "to_convert": sum(found.get(s, 0) for s in CONVERTING),
        "all": len(conversion_rows),
    }
