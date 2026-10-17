"""Scanning a platform folder: inventory its files and archive members, then identify
them against the DAT.

Identification is igir's checksum match first; for files igir leaves unmatched on
platforms with copier headers, the header-stripped data is looked up by CRC and size.
Without an active DAT the scan still takes the inventory, which is all conversion needs.
"""

import fnmatch
import os
import sqlite3
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from g1r import archives, fuzzy, hasheous, igir, mounts
from g1r.config import Settings
from g1r.dat_registry import DatRegistry
from g1r.dats import Dat
from g1r.hashing import ContentHash, content_hashes, header_size, payloads
from g1r.library import FolderEntry, LibraryStore

METHOD_CHECKSUM = "dat-checksum"
METHOD_HEADERLESS = "dat-headerless"
METHOD_HASHEOUS = "hasheous"
METHOD_FUZZY = "fuzzy"
METHOD_MANUAL = "manual"
CHECKSUM_SCORE = 1.0

ReportRunner = Callable[[Settings, Path, Path], list[igir.ReportRow]]


class ScanError(RuntimeError):
    """The scan could not start or finish; the message is shown on the folder page."""


@dataclass(frozen=True)
class InventoryFile:
    rel_path: str
    size: int
    mtime_ns: int
    kind: str


def is_ignored(name: str, patterns: list[str]) -> bool:
    lowered = name.lower()
    return any(fnmatch.fnmatchcase(lowered, p.lower()) for p in patterns)


def inventory(settings: Settings, root: Path, platform: str, ignored: list[str]):
    profile = settings.platforms.profiles[platform]
    roms = {e.lower() for e in profile.rom_extensions}
    archives = {e.lower() for e in settings.platforms.archive_extensions}
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in sorted(filenames):
            path = Path(dirpath) / name
            stat = path.stat()
            extension = path.suffix.lower().lstrip(".")
            if is_ignored(name, ignored) or name.startswith("."):
                kind = "ignored"
            elif extension in roms:
                kind = "rom"
            elif extension in archives:
                kind = "archive"
            else:
                kind = "other"
            rel = PurePosixPath(path.relative_to(root).as_posix())
            files.append(InventoryFile(str(rel), stat.st_size, stat.st_mtime_ns, kind))
    return files


# Header-stripped fallback -------------------------------------------------------


def headerless_matches(settings: Settings, platform: str, path: Path, dat: Dat) -> set[str]:
    rules = settings.headers.get(platform, [])
    if not rules:
        return set()
    index: dict[tuple[str, int], set[str]] = {}
    for game in dat.games:
        for rom in game.roms:
            if rom.crc and rom.size is not None:
                index.setdefault((rom.crc, rom.size), set()).add(game.name)
    profile = settings.platforms.profiles[platform]
    exts = {e.lower() for e in profile.rom_extensions}
    found: set[str] = set()
    for data in payloads(path, exts, settings.dats.max_upload_bytes):
        for rule in rules:
            size = header_size(rule, data)
            if size is None:
                continue
            body = data[size:]
            crc = format(zlib.crc32(body), "08x")
            found |= index.get((crc, len(body)), set())
    return found


# The scan ------------------------------------------------------------------------


class Scanner:
    def __init__(
        self,
        settings: Settings,
        store: LibraryStore,
        registry: DatRegistry,
        report_runner: ReportRunner | None = None,
        seven_zip: archives.SevenZipRunner = archives.run_seven_zip,
        lookup_post: hasheous.Post = hasheous.http_post,
    ):
        self.settings = settings
        self.store = store
        self.registry = registry
        self.report_runner = report_runner or igir.run_report
        self.seven_zip = seven_zip
        self.lookup_post = lookup_post

    def start(self, conn: sqlite3.Connection, label: str) -> int:
        running = conn.execute(
            "SELECT id FROM scan WHERE folder_label = ? AND status = 'running'", (label,)
        ).fetchone()
        if running:
            raise ScanError("a scan of this folder is already running")
        return conn.execute(
            "INSERT INTO scan (folder_label, status) VALUES (?, 'running')", (label,)
        ).lastrowid

    def run(
        self, conn: sqlite3.Connection, scan_id: int, label: str, refresh_lookups: bool = False
    ) -> None:
        try:
            message = self._scan(conn, label, refresh_lookups)
            self._finish(conn, scan_id, "done", message)
        except (ScanError, igir.IgirError, mounts.FolderPathError, OSError) as exc:
            self._finish(conn, scan_id, "failed", str(exc))
        except Exception as exc:  # a background job must never stay 'running'
            self._finish(conn, scan_id, "failed", f"unexpected error: {exc!r}")
            raise

    def _finish(self, conn, scan_id, status, message) -> None:
        conn.execute(
            "UPDATE scan SET status = ?, message = ?, "
            "finished_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
            (status, message, scan_id),
        )

    def _scan(self, conn: sqlite3.Connection, label: str, refresh_lookups: bool) -> str:
        library = self.store.load()
        folder: FolderEntry | None = library.folder(label)
        if folder is None:
            raise ScanError("the folder is no longer in the library")
        root = mounts.resolve(self.settings, folder.mount, folder.path)
        if not root.is_dir():
            raise ScanError(f"{root} is not available")
        files = inventory(
            self.settings, root, folder.platform, self.store.ignored_filenames(library)
        )
        found = Found(*self._members(root, files))
        active = self.registry.active_version(conn, library, folder.platform)
        if active is None:
            self._store(conn, label, files, None, found)
            return (
                f"inventory only, {len(files)} files: this platform has no active DAT, so "
                "nothing was identified (add one in Settings → DATs)"
            )
        dat_file = self.settings.paths.data_dir / active["file"]
        rows = self.report_runner(self.settings, dat_file, root)
        by_path = igir.identified_files(rows)
        unmatched = []
        for f in files:
            if f.kind not in ("rom", "archive"):
                continue
            games = by_path.get(str(root / f.rel_path), set())
            if games:
                found.identify(f.rel_path, games, METHOD_CHECKSUM)
            else:
                unmatched.append(f)
        dat = self.registry.load_active(conn, library, folder.platform)
        if unmatched and self.settings.headers.get(folder.platform):
            for f in unmatched:
                games = headerless_matches(self.settings, folder.platform, root / f.rel_path, dat)
                found.identify(f.rel_path, games, METHOD_HEADERLESS)
        unmatched = [f for f in unmatched if f.rel_path not in found.identified]
        notes = self._look_up(
            conn, library, folder.platform, root, unmatched, found, refresh_lookups
        )
        unmatched = [f for f in unmatched if f.rel_path not in found.identified]
        self._suggest(dat, unmatched, found)
        self._apply_manual(conn, label, files, found)
        self._store(conn, label, files, active["sha1"], found)
        conn.execute(
            "UPDATE scan SET dat_sha1 = ? WHERE folder_label = ? AND status = 'running'",
            (active["sha1"], label),
        )
        candidates = sum(1 for f in files if f.kind in ("rom", "archive"))
        parts = [f"{len(found.identified)} of {candidates} ROM files identified"]
        online = sum(1 for m in found.identified.values() if m == METHOD_HASHEOUS)
        if online:
            parts.append(f"{online} of them via Hasheous")
        return "; ".join(parts + notes)

    def _look_up(self, conn, library, platform, root, unmatched, found, refresh) -> list[str]:
        """Identification step 3: hash what the DAT missed; ask Hasheous when it is on."""
        dat_name = self.settings.platforms.profiles[platform].nointro_dat
        for f in unmatched:
            hashes = content_hashes(self.settings, platform, root / f.rel_path)
            found.hashes[f.rel_path] = hashes
            if not library.lookups.hasheous or not hashes:
                continue
            try:
                answer = hasheous.lookup(
                    self.settings, conn, hashes, dat_name, self.lookup_post, refresh=refresh
                )
            except hasheous.LookupError_ as exc:
                found.lookups[f.rel_path] = (hasheous.ERROR, str(exc))
                return [f"online lookups stopped: {exc}"]
            found.lookups[f.rel_path] = (answer.status, answer.detail)
            if answer.status == hasheous.FOUND and answer.game_name:
                found.identify(f.rel_path, {answer.game_name}, METHOD_HASHEOUS)
        return []

    def _suggest(self, dat: Dat, unmatched: list[InventoryFile], found: "Found") -> None:
        config = self.settings.fuzzy
        names = [g.name for g in dat.games]
        for f in unmatched:
            best = fuzzy.suggestions(config, f.rel_path, names)
            found.suggestions[f.rel_path] = best
            threshold = config.auto_match_threshold
            if best and threshold is not None and best[0][1] >= threshold:
                found.identify(f.rel_path, {best[0][0]}, METHOD_FUZZY, best[0][1])

    def _apply_manual(self, conn, label, files, found: "Found") -> None:
        present = {f.rel_path for f in files}
        for rel_path, game in conn.execute(
            "SELECT rel_path, game_name FROM manual_identity WHERE folder_label = ?", (label,)
        ):
            if rel_path in present:
                found.forget(rel_path)
                found.identify(rel_path, {game}, METHOD_MANUAL)

    def _members(self, root: Path, files: list[InventoryFile]):
        members: list[tuple[str, archives.Member]] = []
        problems: list[tuple[str, str]] = []
        for f in files:
            if f.kind != "archive":
                continue
            try:
                found = archives.list_members(self.settings, root / f.rel_path, self.seven_zip)
            except archives.ArchiveError as exc:
                problems.append((f.rel_path, str(exc)))
                continue
            members += [(f.rel_path, m) for m in found]
        return members, problems

    def _store(self, conn, label, files, dat_sha1, found: "Found") -> None:
        conn.execute("BEGIN")
        try:
            conn.execute("DELETE FROM identity WHERE folder_label = ?", (label,))
            conn.execute("DELETE FROM folder_file WHERE folder_label = ?", (label,))
            conn.executemany(
                "INSERT INTO folder_file VALUES (?, ?, ?, ?, ?)",
                [(label, f.rel_path, f.size, f.mtime_ns, f.kind) for f in files],
            )
            conn.executemany(
                "INSERT OR IGNORE INTO identity (folder_label, rel_path, game_name, method, "
                "dat_sha1, score) VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (label, rel, game, method, dat_sha1, score)
                    for rel, game, method, score in found.identities
                ],
            )
            conn.executemany(
                "INSERT OR IGNORE INTO archive_member VALUES (?, ?, ?, ?, ?)",
                [(label, rel, m.name, m.size, m.crc32) for rel, m in found.members],
            )
            conn.executemany(
                "INSERT INTO archive_problem VALUES (?, ?, ?)",
                [(label, rel, message) for rel, message in found.problems],
            )
            conn.executemany(
                "INSERT INTO content_hash VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (label, rel, h.variant, h.size, h.crc32, h.md5, h.sha1)
                    for rel, hashes in found.hashes.items()
                    for h in hashes
                ],
            )
            conn.executemany(
                "INSERT INTO lookup_result VALUES (?, ?, ?, ?, ?)",
                [
                    (label, rel, hasheous.SERVICE, status, detail)
                    for rel, (status, detail) in found.lookups.items()
                ],
            )
            conn.executemany(
                "INSERT INTO suggestion VALUES (?, ?, ?, ?)",
                [
                    (label, rel, game, score)
                    for rel, best in found.suggestions.items()
                    for game, score in best
                ],
            )
            conn.execute("COMMIT")
        except sqlite3.Error:
            conn.execute("ROLLBACK")
            raise


@dataclass
class Found:
    """What a scan learned about a folder's files, stored together at the end."""

    members: list[tuple[str, archives.Member]]
    problems: list[tuple[str, str]]
    # (rel_path, game_name, method, score)
    identities: list[tuple[str, str, str, float]] = field(default_factory=list)
    # rel_path -> the method that identified it first
    identified: dict[str, str] = field(default_factory=dict)
    hashes: dict[str, list[ContentHash]] = field(default_factory=dict)
    lookups: dict[str, tuple[str, str]] = field(default_factory=dict)
    suggestions: dict[str, list[tuple[str, float]]] = field(default_factory=dict)

    def identify(self, rel_path, games, method, score=CHECKSUM_SCORE) -> None:
        for game in sorted(games):
            self.identities.append((rel_path, game, method, score))
            self.identified.setdefault(rel_path, method)

    def forget(self, rel_path: str) -> None:
        self.identities = [i for i in self.identities if i[0] != rel_path]
        self.identified.pop(rel_path, None)


def fail_interrupted(conn: sqlite3.Connection) -> None:
    """Scans still 'running' at start-up were cut off by a restart."""
    conn.execute(
        "UPDATE scan SET status = 'failed', message = 'interrupted by a restart', "
        "finished_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE status = 'running'"
    )


def latest_scan(conn: sqlite3.Connection, label: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM scan WHERE folder_label = ? ORDER BY id DESC LIMIT 1", (label,)
    ).fetchone()


def folder_summary(conn: sqlite3.Connection, label: str) -> dict:
    counts = {
        row["kind"]: row["n"]
        for row in conn.execute(
            "SELECT kind, COUNT(*) AS n FROM folder_file WHERE folder_label = ? GROUP BY kind",
            (label,),
        )
    }
    identified = conn.execute(
        "SELECT COUNT(DISTINCT rel_path) FROM identity WHERE folder_label = ?", (label,)
    ).fetchone()[0]
    methods = {
        row["method"]: row["n"]
        for row in conn.execute(
            "SELECT method, COUNT(DISTINCT rel_path) AS n FROM identity WHERE folder_label = ? "
            "GROUP BY method",
            (label,),
        )
    }
    roms = counts.get("rom", 0) + counts.get("archive", 0)
    return {
        "counts": counts,
        "roms": roms,
        "identified": identified,
        "unmatched": roms - identified,
        "methods": methods,
    }


def unmatched_files(conn: sqlite3.Connection, label: str) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT f.* FROM folder_file f
           WHERE f.folder_label = ? AND f.kind IN ('rom', 'archive')
             AND NOT EXISTS (SELECT 1 FROM identity i
                             WHERE i.folder_label = f.folder_label AND i.rel_path = f.rel_path)
           ORDER BY f.rel_path""",
        (label,),
    ).fetchall()


def other_files(conn: sqlite3.Connection, label: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM folder_file WHERE folder_label = ? AND kind IN ('other', 'ignored') "
        "ORDER BY kind, rel_path",
        (label,),
    ).fetchall()
