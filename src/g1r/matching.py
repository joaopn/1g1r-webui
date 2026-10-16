"""The Matching & 1G1R table of a folder: groups, decisions, overrides and proposed moves.

Everything here is a proposal computed on request; nothing is moved.
"""

import sqlite3
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path, PurePosixPath

from g1r.config import RankingConfig, Settings
from g1r.dats import Dat, parse_dat
from g1r.grouping import Group, Version, build_groups
from g1r.ranking import Decision, decide

STATUS_SINGLE = "single"
STATUS_DECIDED = "decided"
STATUS_UNDECIDED = "undecided"
STATUS_PICKED = "your pick"
STATUS_LEFT = "left alone"

FILTERS = {
    "all": "All games",
    "several": "With several versions",
    "proposals": "With proposed moves",
    "undecided": "Undecided",
    "left": "Left alone",
}

REASON_DISCARDED = "1g1r"


@dataclass
class Row:
    version: Version
    size: int | None
    keep: bool
    operation: str | None  # None = nothing happens to this file


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


def discard_path(settings: Settings, label: str, rel_path: str) -> str:
    return str(PurePosixPath(settings.paths.discarded_root, label, REASON_DISCARDED, rel_path))


def game_rows(
    settings: Settings, conn: sqlite3.Connection, label: str, ranking: RankingConfig
) -> list[GameRow]:
    identities = conn.execute(
        "SELECT rel_path, game_name, method, dat_sha1 FROM identity WHERE folder_label = ?",
        (label,),
    ).fetchall()
    if not identities:
        return []
    dat = load_dat(settings, conn, identities[0]["dat_sha1"])
    if dat is None:
        return []
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
    groups = build_groups(
        settings, dat, [(r["rel_path"], r["game_name"], r["method"]) for r in identities]
    )
    result = []
    for group in groups:
        decision: Decision = decide(group, ranking)
        winner = decision.winner
        status = (
            STATUS_SINGLE
            if len(group.versions) == 1
            else (STATUS_DECIDED if winner else STATUS_UNDECIDED)
        )
        reason = decision.reason
        picked = picks.get(group.key)
        if picked and any(v.rel_path == picked for v in group.versions) and len(group.versions) > 1:
            winner = next(v for v in group.versions if v.rel_path == picked)
            status, reason = STATUS_PICKED, "you ticked this version"
        if group.key in left:
            status, reason = STATUS_LEFT, "you took this game out of the operations"
        rows = []
        for version in group.versions:
            keep = winner is not None and version.rel_path == winner.rel_path
            operation = None
            if status in (STATUS_DECIDED, STATUS_PICKED) and not keep:
                operation = discard_path(settings, label, version.rel_path)
            rows.append(Row(version, sizes.get(version.rel_path), keep, operation))
        kept = next((r for r in rows if r.keep), None)
        result.append(
            GameRow(group, status, reason, rows, kept, {v.rel_path for v in decision.candidates})
        )
    return result


def table(
    settings: Settings,
    conn: sqlite3.Connection,
    label: str,
    ranking: RankingConfig,
    *,
    view: str = "all",
    query: str = "",
    page: int = 1,
) -> Table:
    games = game_rows(settings, conn, label, ranking)
    tests = {
        "all": lambda g: True,
        "several": lambda g: len(g.rows) > 1,
        "proposals": lambda g: g.has_proposals,
        "undecided": lambda g: g.status == STATUS_UNDECIDED,
        "left": lambda g: g.status == STATUS_LEFT,
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


def find_game(settings, conn, label, ranking, group_key) -> GameRow | None:
    return next(
        (g for g in game_rows(settings, conn, label, ranking) if g.group.key == group_key), None
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
