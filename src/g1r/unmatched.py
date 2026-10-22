"""Unmatched content: files nothing identified, with what the lookups said and the name
suggestions; and the manual assignments that take a file out of it."""

import sqlite3

from g1r import hasheous, scanner
from g1r.dats import Dat


def rows(
    conn: sqlite3.Connection,
    label: str,
    hasheous_on: bool,
    parts: frozenset[str] = frozenset(),
    waiting: frozenset[str] = frozenset(),
) -> list[dict]:
    files = scanner.unmatched_files(conn, label, parts, waiting)
    hashes: dict[str, dict] = {}
    for h in conn.execute(
        "SELECT rel_path, variant, crc32, sha1 FROM content_hash WHERE folder_label = ? "
        "ORDER BY rel_path, variant",
        (label,),
    ):
        hashes.setdefault(h["rel_path"], {"crc32": h["crc32"], "sha1": h["sha1"]})
    lookups = {
        (r["rel_path"], r["service"]): {"status": r["status"], "detail": r["detail"]}
        for r in conn.execute(
            "SELECT rel_path, service, status, detail FROM lookup_result WHERE folder_label = ?",
            (label,),
        )
    }
    suggestions: dict[str, list[dict]] = {}
    for s in conn.execute(
        "SELECT rel_path, game_name, score FROM suggestion WHERE folder_label = ? "
        "ORDER BY rel_path, score DESC, game_name",
        (label,),
    ):
        suggestions.setdefault(s["rel_path"], []).append(
            {"game_name": s["game_name"], "score": s["score"]}
        )
    off = {"status": "off", "detail": ""}
    return [
        {
            "rel_path": f["rel_path"],
            "size": f["size"],
            "hash": hashes.get(f["rel_path"]),
            "hasheous": lookups.get(
                (f["rel_path"], hasheous.SERVICE), off if not hasheous_on else None
            ),
            "suggestions": suggestions.get(f["rel_path"], []),
        }
        for f in files
    ]


def assign(
    conn: sqlite3.Connection,
    label: str,
    rel_path: str,
    game_name: str | None,
    dat_sha1: str = "",
) -> None:
    """Link a file to a DAT entry by hand (or undo that); it applies now and on every scan.
    `dat_sha1`: the DAT the name is read with (the first of the platform's to list it)."""
    conn.execute("BEGIN")
    try:
        conn.execute(
            "DELETE FROM manual_identity WHERE folder_label = ? AND rel_path = ?",
            (label, rel_path),
        )
        conn.execute(
            "DELETE FROM identity WHERE folder_label = ? AND rel_path = ? AND method = ?",
            (label, rel_path, scanner.METHOD_MANUAL),
        )
        if game_name is not None:
            conn.execute(
                "INSERT INTO manual_identity VALUES (?, ?, ?)", (label, rel_path, game_name)
            )
            conn.execute(
                "DELETE FROM identity WHERE folder_label = ? AND rel_path = ?", (label, rel_path)
            )
            conn.execute(
                "INSERT INTO identity (folder_label, rel_path, game_name, method, dat_sha1) "
                "VALUES (?, ?, ?, ?, ?)",
                (label, rel_path, game_name, scanner.METHOD_MANUAL, dat_sha1),
            )
        conn.execute("COMMIT")
    except sqlite3.Error:
        conn.execute("ROLLBACK")
        raise


def search(dats: "Dat | list[Dat]", query: str, limit: int) -> list[str]:
    """Names containing the query, from every DAT given."""
    needle = query.strip().lower()
    if not needle:
        return []
    found = {g.name for dat in ([dats] if isinstance(dats, Dat) else dats) for g in dat.games}
    return sorted(n for n in found if needle in n.lower())[:limit]
