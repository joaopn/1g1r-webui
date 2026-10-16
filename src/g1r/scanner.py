"""Scanning a platform folder: inventory its files and archive members, then identify
them against the DAT.

Identification is igir's checksum match first; for files igir leaves unmatched on
platforms with copier headers, the header-stripped data is looked up by CRC and size.
Without an active DAT the scan still takes the inventory, which is all conversion needs.
"""

import fnmatch
import os
import sqlite3
import zipfile
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from g1r import archives, igir, mounts
from g1r.config import HeaderRule, Settings
from g1r.dat_registry import DatRegistry
from g1r.dats import Dat
from g1r.library import FolderEntry, LibraryStore

METHOD_CHECKSUM = "dat-checksum"
METHOD_HEADERLESS = "dat-headerless"

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


def header_size(rule: HeaderRule, data: bytes) -> int | None:
    if rule.magic_hex is not None:
        magic = bytes.fromhex(rule.magic_hex)
        end = rule.magic_offset + len(magic)
        if data[rule.magic_offset : end] == magic and len(data) > rule.header_size:
            return rule.header_size
        return None
    if len(data) % rule.size_modulus == rule.header_size:
        return rule.header_size
    return None


def _payloads(path: Path, rom_extensions: set[str], limit: int):
    """The ROM data inside a file: the file itself, or each ROM member of a zip."""
    if path.suffix.lower() == ".zip":
        try:
            with zipfile.ZipFile(path) as archive:
                for info in archive.infolist():
                    ext = PurePosixPath(info.filename).suffix.lower().lstrip(".")
                    if ext in rom_extensions and info.file_size <= limit:
                        yield archive.read(info)
        except zipfile.BadZipFile:
            return
    elif path.stat().st_size <= limit:
        yield path.read_bytes()


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
    for data in _payloads(path, exts, settings.dats.max_upload_bytes):
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
    ):
        self.settings = settings
        self.store = store
        self.registry = registry
        self.report_runner = report_runner or igir.run_report
        self.seven_zip = seven_zip

    def start(self, conn: sqlite3.Connection, label: str) -> int:
        running = conn.execute(
            "SELECT id FROM scan WHERE folder_label = ? AND status = 'running'", (label,)
        ).fetchone()
        if running:
            raise ScanError("a scan of this folder is already running")
        return conn.execute(
            "INSERT INTO scan (folder_label, status) VALUES (?, 'running')", (label,)
        ).lastrowid

    def run(self, conn: sqlite3.Connection, scan_id: int, label: str) -> None:
        try:
            message = self._scan(conn, label)
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

    def _scan(self, conn: sqlite3.Connection, label: str) -> str:
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
        members, problems = self._members(root, files)
        active = self.registry.active_version(conn, library, folder.platform)
        if active is None:
            self._store(conn, label, files, [], None, members, problems)
            return (
                f"inventory only, {len(files)} files: this platform has no active DAT, so "
                "nothing was identified (add one in Settings → DATs)"
            )
        dat_file = self.settings.paths.data_dir / active["file"]
        rows = self.report_runner(self.settings, dat_file, root)
        by_path = igir.identified_files(rows)
        identities: list[tuple[str, str, str]] = []
        unmatched = []
        for f in files:
            if f.kind not in ("rom", "archive"):
                continue
            games = by_path.get(str(root / f.rel_path), set())
            if games:
                identities += [(f.rel_path, g, METHOD_CHECKSUM) for g in games]
            else:
                unmatched.append(f)
        if unmatched and self.settings.headers.get(folder.platform):
            dat = self.registry.load_active(conn, library, folder.platform)
            for f in unmatched:
                for game in headerless_matches(
                    self.settings, folder.platform, root / f.rel_path, dat
                ):
                    identities.append((f.rel_path, game, METHOD_HEADERLESS))
        self._store(conn, label, files, identities, active["sha1"], members, problems)
        conn.execute(
            "UPDATE scan SET dat_sha1 = ? WHERE folder_label = ? AND status = 'running'",
            (active["sha1"], label),
        )
        identified = len({rel for rel, _, _ in identities})
        candidates = sum(1 for f in files if f.kind in ("rom", "archive"))
        return f"{identified} of {candidates} ROM files identified"

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

    def _store(self, conn, label, files, identities, dat_sha1, members, problems) -> None:
        conn.execute("BEGIN")
        try:
            conn.execute("DELETE FROM identity WHERE folder_label = ?", (label,))
            conn.execute("DELETE FROM folder_file WHERE folder_label = ?", (label,))
            conn.executemany(
                "INSERT INTO folder_file VALUES (?, ?, ?, ?, ?)",
                [(label, f.rel_path, f.size, f.mtime_ns, f.kind) for f in files],
            )
            conn.executemany(
                "INSERT OR IGNORE INTO identity VALUES (?, ?, ?, ?, ?)",
                [(label, rel, game, method, dat_sha1) for rel, game, method in identities],
            )
            conn.executemany(
                "INSERT OR IGNORE INTO archive_member VALUES (?, ?, ?, ?, ?)",
                [(label, rel, m.name, m.size, m.crc32) for rel, m in members],
            )
            conn.executemany(
                "INSERT INTO archive_problem VALUES (?, ?, ?)",
                [(label, rel, message) for rel, message in problems],
            )
            conn.execute("COMMIT")
        except sqlite3.Error:
            conn.execute("ROLLBACK")
            raise


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
