"""The Matching & 1G1R table of a folder: groups, decisions, overrides and proposed moves.

Everything here is a proposal computed on request; nothing is moved.
"""

import sqlite3
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path, PurePosixPath

from g1r import journal, titles
from g1r.config import PLAIN, RankingConfig, Settings
from g1r.dats import Dat, DatHeader, parse_dat
from g1r.grouping import (
    DatSet,
    Group,
    SourceDat,
    Version,
    build_groups,
    build_title_groups,
)
from g1r.ranking import Decision, decide

STATUS_SINGLE = "single"
STATUS_DECIDED = "decided"
STATUS_UNDECIDED = "undecided"
STATUS_PICKED = "your pick"
STATUS_LEFT = "left alone"
STATUS_APPLIED = "applied"

FILTERS = {
    "all": "All games",
    "several": "With several versions",
    "proposals": "With proposed moves",
    "undecided": "Undecided",
    "left": "Left alone",
    "applied": "Applied",
}

REASON_DISCARDED = journal.REASON_1G1R
# Identical copies of the version kept go here instead of 1g1r/.
REASON_DUPLICATES = journal.REASON_DUPLICATES
# A title-ID game's updates (Switch: game + DLC is what 1G1R keeps).
REASON_UPDATES = journal.REASON_UPDATES
# Title-ID versions that are not ranked against the base game.
EXTRA_ROLES = (titles.UPDATE, titles.DLC)
# discarded/ subfolders whose files stay versions in the table.
VERSION_REASONS = (REASON_DISCARDED, REASON_DUPLICATES, REASON_UPDATES)


@dataclass
class Row:
    version: Version
    size: int | None
    keep: bool
    operation: str | None  # None = nothing happens to this file
    probability: float = 1.0
    # Set when an apply moved this version to discarded/: the journal operation's id.
    discarded: int | None = None
    # The other versions with byte-identical ROM data.
    identical: list[str] = field(default_factory=list)
    # The discarded/ subfolder the proposed move goes to.
    discard_reason: str = REASON_DISCARDED
    # What the file's header says (cards.ENCRYPTED, cards.TRIMMED).
    notes: list[str] = field(default_factory=list)


@dataclass
class GameRow:
    group: Group
    status: str
    reason: str
    rows: list[Row]
    kept: Row | None
    candidates: set[str] = field(default_factory=set)

    @property
    def has_proposals(self) -> bool:
        return any(r.operation for r in self.rows)


@dataclass
class Table:
    games: list[GameRow]
    total: int
    page: int
    pages: int
    counts: dict[str, int]
    reclaim_bytes: int


@cache
def _dat(path: Path, sha1: str) -> Dat:
    return parse_dat(path)


def load_dat(settings: Settings, conn: sqlite3.Connection, sha1: str) -> Dat | None:
    row = conn.execute("SELECT file FROM dat_version WHERE sha1 = ?", (sha1,)).fetchone()
    if row is None:
        return None
    return _dat(settings.paths.data_dir / row["file"], sha1)


def discard_path(
    settings: Settings, label: str, rel_path: str, reason: str = REASON_DISCARDED
) -> str:
    return str(PurePosixPath(settings.paths.discarded_root, label, reason, rel_path))


def container_of_path(rel_path: str, archive_extensions: set[str]) -> str:
    """A file's container as targets name them: its archive extension, else plain."""
    suffix = PurePosixPath(rel_path).suffix.lower().lstrip(".")
    return suffix if suffix in archive_extensions else PLAIN


def _copies(
    versions: list[Version],
    payloads: dict[str, str],
    prefer: str | None = None,
    archive_extensions: set[str] = frozenset(),
) -> list[list[Version]]:
    """Versions grouped by identical ROM data; each list starts with the copy to rank.

    Which identical copy stands for the others is cosmetic: the one named like its DAT
    entry, then one already in the target container (`prefer`, e.g. "zip"), else the
    first by path. Versions without a payload hash stand alone.
    """
    sets: dict[str, list[Version]] = {}
    for v in sorted(versions, key=lambda v: v.rel_path):
        sets.setdefault(payloads.get(v.rel_path) or f"\0{v.rel_path}", []).append(v)
    for copies in sets.values():
        copies.sort(
            key=lambda v: (
                PurePosixPath(v.rel_path).stem != v.game_name,
                container_of_path(v.rel_path, archive_extensions) != prefer,
            )
        )
    return list(sets.values())


@dataclass(frozen=True)
class FolderView:
    """What the table needs from the folder's platform."""

    # The container its target produces: kept among identical copies.
    prefer: str | None = None
    # Extensions of files that are only part of a game (cue sheets, tracks): not versions.
    parts: frozenset[str] = frozenset()
    # Where titles come from: DAT names, or descriptions (arcade sets).
    names_from: str = "name"
    # Identified and grouped by title ID (Switch), no DAT needed.
    title_ids: bool = False
    # The platform's DATs in its identification order: (sha1, name style), each DAT's names
    # read in its own style (No-Intro/Redump or TOSEC).
    dats: tuple[tuple[str, str], ...] = ()


def is_part(rel_path: str, parts: frozenset[str]) -> bool:
    return PurePosixPath(rel_path).suffix.lower().lstrip(".") in parts


def game_rows(
    settings: Settings,
    conn: sqlite3.Connection,
    label: str,
    ranking: RankingConfig,
    view: FolderView | None = None,
) -> list[GameRow]:
    view = view or FolderView()
    prefer = view.prefer
    identities = [
        r
        for r in conn.execute(
            "SELECT rel_path, game_name, method, dat_sha1, score FROM identity "
            "WHERE folder_label = ?",
            (label,),
        )
        if not is_part(r["rel_path"], view.parts)
    ]
    if not identities:
        return []
    places = dict(
        conn.execute(
            "SELECT rel_path, place FROM folder_file WHERE folder_label = ?", (label,)
        ).fetchall()
    )
    # A file put back by hand shows as in the folder again (a rescan found it there).
    gone = {
        op["rel_path"]: op["id"]
        for op in journal.active_discards(conn, label)
        if places.get(op["rel_path"]) == journal.PLACE_DISCARDED and op["reason"] in VERSION_REASONS
    }
    # Other discarded files (a conversion's originals) are no versions: their output is.
    identities = [
        r
        for r in identities
        if places.get(r["rel_path"]) != journal.PLACE_DISCARDED or r["rel_path"] in gone
    ]
    if not identities:
        return []
    # The platform's DATs, then any other DAT an identity names (a file discarded before
    # its DAT left the order keeps the identity of the scan before its move).
    listed = list(view.dats)
    style = listed[0][1] if listed else "nointro"
    for r in identities:
        if r["dat_sha1"] and all(r["dat_sha1"] != sha1 for sha1, _ in listed):
            listed.append((r["dat_sha1"], style))
    sources = []
    for sha1, name_style in listed:
        dat = load_dat(settings, conn, sha1)
        if dat is not None:
            sources.append(SourceDat(sha1, dat, name_style))
    if not sources and not view.title_ids:
        return []
    dats = DatSet(sources or [SourceDat("", Dat(DatHeader(name=""), [], "none"))])
    scores = {(r["rel_path"], r["game_name"]): r["score"] for r in identities}
    sizes = dict(
        conn.execute(
            "SELECT rel_path, size FROM folder_file WHERE folder_label = ?", (label,)
        ).fetchall()
    )
    picks = dict(
        conn.execute(
            "SELECT group_key, rel_path FROM keep_choice WHERE folder_label = ?", (label,)
        ).fetchall()
    )
    left = {
        r[0]
        for r in conn.execute("SELECT group_key FROM game_flag WHERE folder_label = ?", (label,))
    }
    archives = {e.lower() for e in settings.platforms.archive_extensions}
    payloads = dict(
        conn.execute(
            "SELECT rel_path, sha1 FROM payload_hash WHERE folder_label = ?", (label,)
        ).fetchall()
    )
    file_notes: dict[str, list[str]] = {}
    for rel, note in conn.execute(
        "SELECT rel_path, note FROM file_note WHERE folder_label = ? ORDER BY note", (label,)
    ):
        file_notes.setdefault(rel, []).append(note)
    triples = [(r["rel_path"], r["game_name"], r["method"]) for r in identities]
    quads = [(*t, r["dat_sha1"]) for t, r in zip(triples, identities, strict=True)]
    groups = (
        build_title_groups(settings, triples)
        if view.title_ids
        else build_groups(settings, dats, quads, view.names_from)
    )
    result = []
    for group in groups:
        # Ranking and picks see only the versions still in the folder, and (title IDs) only
        # the base game: its DLC are kept and its updates proposed, whatever is kept.
        extras = {v.rel_path: v.role for v in group.versions if v.role in EXTRA_ROLES}
        present = Group(
            group.key,
            group.name,
            group.source,
            [v for v in group.versions if v.rel_path not in gone and v.rel_path not in extras],
        )
        # Identical copies are ranked once; the copy standing for them is the first.
        copies = _copies(present.versions, payloads, prefer, archives)
        ranked = Group(group.key, group.name, group.source, [c[0] for c in copies])
        status, reason, winner, candidates = _decide(ranked, ranking, picks, left, present)
        if extras and not any(v.role == titles.BASE for v in group.versions):
            # DLC or an update without its game: nothing to choose, nothing proposed.
            status, reason, winner, candidates = (
                STATUS_LEFT,
                "the base game is not in the folder: its DLC and updates are kept",
                None,
                set(),
            )
        if extras and status == STATUS_SINGLE:
            # One base game: what is left to say depends on its updates.
            updates = [r for r, role in extras.items() if role == titles.UPDATE]
            if any(r not in gone for r in updates):
                status, reason = STATUS_DECIDED, "one base game: its DLC are kept, updates proposed"
            elif updates:
                status, reason = STATUS_APPLIED, "its updates are in discarded/"
            else:
                reason = "its DLC are kept"
        if group.versions and all(v.bios for v in group.versions):
            # Every arcade game needs its BIOS set: never proposed for discarding.
            status, reason, winner, candidates = (
                STATUS_LEFT,
                "a BIOS: every game needs it",
                None,
                set(),
            )
        if len(ranked.versions) == 1 and len(present.versions) > 1 and status == STATUS_SINGLE:
            status, reason = STATUS_DECIDED, "identical copies of one version"
        if status == STATUS_SINGLE and any(v.rel_path in gone for v in group.versions):
            status, reason = STATUS_APPLIED, "the other versions are in discarded/"
        set_of = {v.rel_path: c for c in copies for v in c}
        rows = []
        for version in group.versions:
            keep = winner is not None and version.rel_path == winner.rel_path
            operation = None
            discard_reason = REASON_DISCARDED
            role = extras.get(version.rel_path)
            if role is not None:
                keep = role == titles.DLC
                if role == titles.UPDATE and version.rel_path not in gone and status != STATUS_LEFT:
                    discard_reason = REASON_UPDATES
                    operation = discard_path(settings, label, version.rel_path, discard_reason)
            mine = set_of.get(version.rel_path, [])
            twin_of_kept = winner is not None and winner in mine
            stands_in = bool(mine) and mine[0] is version
            if role is None and version in present.versions and not keep and status != STATUS_LEFT:
                if twin_of_kept:
                    discard_reason = REASON_DUPLICATES
                    operation = discard_path(settings, label, version.rel_path, discard_reason)
                elif status in (STATUS_DECIDED, STATUS_PICKED):
                    operation = discard_path(settings, label, version.rel_path)
                elif status == STATUS_UNDECIDED and not stands_in:
                    # Still undecided, but a second identical copy is never needed.
                    discard_reason = REASON_DUPLICATES
                    operation = discard_path(settings, label, version.rel_path, discard_reason)
            sha1 = payloads.get(version.rel_path)
            identical = sorted(
                v.rel_path
                for v in group.versions
                if sha1 is not None and v is not version and payloads.get(v.rel_path) == sha1
            )
            probability = scores.get((version.rel_path, version.game_name), 1.0)
            rows.append(
                Row(
                    version,
                    sizes.get(version.rel_path),
                    keep,
                    operation,
                    probability,
                    gone.get(version.rel_path),
                    identical,
                    discard_reason,
                    file_notes.get(version.rel_path, []),
                )
            )
        kept = next((r for r in rows if r.keep), None)
        result.append(GameRow(group, status, reason, rows, kept, candidates))
    return result


def _decide(
    ranked: Group, ranking, picks, left, present: Group
) -> tuple[str, str, Version | None, set[str]]:
    """Rank one copy per distinct ROM data (`ranked`); picks may name any present version."""
    if not ranked.versions:
        return STATUS_APPLIED, "every version is in discarded/", None, set()
    # A version lacking ROMs another DAT lists for its game (one disk of a multi-disk game) is
    # never kept over a whole one; with no whole version, nothing is chosen for you.
    complete = [v for v in ranked.versions if not v.incomplete]
    if len(ranked.versions) > 1 and not complete:
        winner, candidates = None, {v.rel_path for v in ranked.versions}
        status, reason = STATUS_UNDECIDED, "every version lacks ROMs another DAT lists"
    elif len(ranked.versions) > 1 and len(complete) == 1:
        winner, candidates = complete[0], set()
        status, reason = STATUS_DECIDED, "the only version with every ROM its DAT lists"
    else:
        if complete and len(complete) < len(ranked.versions):
            ranked = Group(ranked.key, ranked.name, ranked.source, complete)
        decision: Decision = decide(ranked, ranking)
        winner, candidates = decision.winner, {v.rel_path for v in decision.candidates}
        status = (
            STATUS_SINGLE
            if len(ranked.versions) == 1
            else (STATUS_DECIDED if winner else STATUS_UNDECIDED)
        )
        reason = decision.reason
    picked = picks.get(present.key)
    if picked and len(present.versions) > 1 and any(v.rel_path == picked for v in present.versions):
        winner = next(v for v in present.versions if v.rel_path == picked)
        status, reason = STATUS_PICKED, "you ticked this version"
    if present.key in left:
        status, reason = STATUS_LEFT, "you took this game out of the operations"
    return status, reason, winner, candidates


def table(
    settings: Settings,
    conn: sqlite3.Connection,
    label: str,
    ranking: RankingConfig,
    *,
    view: str = "all",
    query: str = "",
    page: int = 1,
    folder_view: FolderView | None = None,
) -> Table:
    games = game_rows(settings, conn, label, ranking, folder_view)
    tests = {
        "all": lambda g: True,
        "several": lambda g: len(g.rows) > 1,
        "proposals": lambda g: g.has_proposals,
        "undecided": lambda g: g.status == STATUS_UNDECIDED,
        "left": lambda g: g.status == STATUS_LEFT,
        "applied": lambda g: any(r.discarded for r in g.rows),
    }
    counts = {name: sum(1 for g in games if test(g)) for name, test in tests.items()}
    reclaim = sum(r.size or 0 for g in games for r in g.rows if r.operation)
    test = tests.get(view, tests["all"])
    needle = query.strip().lower()
    selected = [
        g
        for g in games
        if test(g)
        and (
            not needle
            or needle in g.group.name.lower()
            or any(needle in r.version.game_name.lower() for r in g.rows)
        )
    ]
    size = settings.ui.page_size
    pages = max(1, -(-len(selected) // size))
    page = min(max(1, page), pages)
    start = (page - 1) * size
    return Table(selected[start : start + size], len(selected), page, pages, counts, reclaim)


def find_game(settings, conn, label, ranking, group_key, view=None) -> GameRow | None:
    return next(
        (g for g in game_rows(settings, conn, label, ranking, view) if g.group.key == group_key),
        None,
    )


def set_keep(conn: sqlite3.Connection, label: str, group_key: str, rel_path: str | None) -> None:
    if rel_path is None:
        conn.execute(
            "DELETE FROM keep_choice WHERE folder_label = ? AND group_key = ?", (label, group_key)
        )
    else:
        conn.execute(
            "INSERT INTO keep_choice (folder_label, group_key, rel_path) VALUES (?, ?, ?) "
            "ON CONFLICT (folder_label, group_key) DO UPDATE SET rel_path = excluded.rel_path, "
            "chosen_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')",
            (label, group_key, rel_path),
        )


def set_left_alone(conn: sqlite3.Connection, label: str, group_key: str, left: bool) -> None:
    if left:
        conn.execute(
            "INSERT OR IGNORE INTO game_flag (folder_label, group_key) VALUES (?, ?)",
            (label, group_key),
        )
    else:
        conn.execute(
            "DELETE FROM game_flag WHERE folder_label = ? AND group_key = ?", (label, group_key)
        )
