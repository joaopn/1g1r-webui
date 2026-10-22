"""Scanning a platform folder: inventory its files and archive members, then identify
them against the DAT.

Identification is igir's checksum match first; for files igir leaves unmatched on
platforms with copier headers, the header-stripped data is looked up by CRC and size, and
on platforms with several byte orders, a swapped file's data in the native order.
Without an active DAT the scan still takes the inventory, which is all conversion needs.
"""

import fnmatch
import os
import sqlite3
import time
import zipfile
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath

from g1r import (
    archives,
    cards,
    conversion,
    fuzzy,
    hasheous,
    hashing,
    igir,
    journal,
    mounts,
    titles,
)
from g1r.config import Settings
from g1r.conversion import ZIP_SUFFIX
from g1r.dat_registry import DatRegistry
from g1r.dats import Dat
from g1r.filecache import FileCache, step
from g1r.hashing import (
    CHD_SUFFIX,
    RVZ_SUFFIX,
    ContentHash,
    chd_identity,
    content_hashes,
    magic_length,
    payload_count,
    payloads,
    probe_sha1,
    rvz_identity,
    word_bytes,
)
from g1r.library import FolderEntry, Library, LibraryStore

METHOD_CHECKSUM = "dat-checksum"
METHOD_HEADERLESS = "dat-headerless"
METHOD_BYTESWAPPED = "dat-byteswapped"
METHOD_UNTRIMMED = "dat-untrimmed"
METHOD_TITLE_ID = "title-id"
# identity.dat_sha1 of an identification that needed no DAT (title IDs).
NO_DAT = ""
METHOD_DUPLICATE = "duplicate"
METHOD_HASHEOUS = "hasheous"  # also in grouping.SINGLE_FILE_METHODS
METHOD_FUZZY = "fuzzy"  # also in grouping.SINGLE_FILE_METHODS
METHOD_MANUAL = "manual"
CHECKSUM_SCORE = 1.0

# (settings, dat file, folder[, merge=mode]) -> report rows
ReportRunner = Callable[..., list[igir.ReportRow]]


class ConvertFirst(Exception):
    """A scan stops after its check: files are not in the target format yet."""


class ScanError(RuntimeError):
    """The scan could not start or finish; the message is shown on the folder page."""


class Progress:
    """How far a running scan is: its step and, for a step that goes file by file, how many
    files are done. Written to the scan's row at most every `interval` seconds, and always
    when a step starts or ends. Without a connection nothing is written."""

    def __init__(
        self,
        conn: sqlite3.Connection | None = None,
        scan_id: int | None = None,
        interval: float = 0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.conn = conn
        self.scan_id = scan_id
        self.interval = interval
        self.clock = clock
        self.name: str | None = None
        self.done: int | None = None
        self.total: int | None = None
        self.written = clock()

    def stage(self, name: str, total: int | None = None) -> None:
        self.name, self.total = name, total
        self.done = None if total is None else 0
        self._write()

    def each[T](self, name: str, items: Iterable[T]) -> Iterator[T]:
        """The items, counting each one done as the loop moves past it."""
        items = list(items)
        self.stage(name, len(items))
        for item in items:
            yield item
            self.done = (self.done or 0) + 1
            if self.done == self.total or self.clock() - self.written >= self.interval:
                self._write()

    def _write(self) -> None:
        self.written = self.clock()
        if self.conn is None:
            return
        self.conn.execute(
            "UPDATE scan SET stage = ?, files_done = ?, files_total = ? WHERE id = ?",
            (self.name, self.done, self.total, self.scan_id),
        )


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
    return _look(_crc_index(dat), headerless_keys(settings, platform, path))


def headerless_step(settings: Settings, platform: str) -> str:
    return step(
        "headerless",
        settings.headers.get(platform, []),
        settings.platforms.profiles[platform].rom_extensions,
    )


def headerless_keys(settings: Settings, platform: str, path: Path) -> list[list]:
    """[CRC, size] of each ROM's data with its copier header removed, for every header rule
    that recognises it."""
    rules = settings.headers.get(platform, [])
    if not rules:
        return []
    profile = settings.platforms.profiles[platform]
    exts = {e.lower() for e in profile.rom_extensions}
    return [
        [digest.crc32, digest.size]
        for payload in payloads(settings, path, exts, rules)
        for digest in payload.headerless
    ]


def _look(index: dict[tuple[str, int], set[str]], keys: list[list]) -> set[str]:
    found: set[str] = set()
    for crc, size in keys:
        found |= index.get((crc, size), set())
    return found


def _crc_index(dat: Dat) -> dict[tuple[str, int], set[str]]:
    index: dict[tuple[str, int], set[str]] = {}
    for game in dat.games:
        for rom in game.roms:
            if rom.crc and rom.size is not None:
                index.setdefault((rom.crc, rom.size), set()).add(game.name)
    return index


def byte_order_matches(
    settings: Settings, platform: str, path: Path, dat: Dat
) -> tuple[set[str], set[str]]:
    """On a platform with several byte orders: the games with a ROM equal to this file's
    data as it is, and those equal to it in the native order. A DAT may list each order as a
    ROM of one game (libretro's N64 DAT has .z64 and .v64), which igir then reports missing
    unless every order is present: any one of them identifies the game."""
    keys = byte_order_keys(settings, platform, path)
    index = _crc_index(dat)
    return _look(index, keys["as_is"]), _look(index, keys["native"])


def byte_order_step(settings: Settings, platform: str) -> str:
    return step(
        "byte-order-crcs",
        settings.byte_orders.get(platform),
        settings.platforms.profiles[platform].rom_extensions,
    )


def byte_order_keys(settings: Settings, platform: str, path: Path) -> dict[str, list[list]]:
    """[CRC, size] of each ROM's data as it is, and in the native byte order."""
    config = settings.byte_orders.get(platform)
    keys: dict[str, list[list]] = {"as_is": [], "native": []}
    if config is None:
        return keys
    exts = {e.lower() for e in settings.platforms.profiles[platform].rom_extensions}
    for payload in payloads(settings, path, exts, byte_order=config):
        keys["as_is"].append([payload.full.crc32, payload.full.size])
        if payload.native is not None:
            keys["native"].append([payload.native.crc32, payload.native.size])
    return keys


# Byte orders ----------------------------------------------------------------------


def read_byte_orders(
    settings: Settings, platform: str, root: Path, files, members, progress=None, cache=None
) -> dict:
    """rel_path -> word length to reverse, for each file whose single ROM (bare, or the one
    ROM member of a zip) starts with a swapped order's magic. 7z is not read."""
    config = settings.byte_orders.get(platform)
    if config is None:
        return {}
    exts = {e.lower() for e in settings.platforms.profiles[platform].rom_extensions}
    roms_inside: dict[str, list[str]] = {}
    for rel, member in members:
        if PurePosixPath(member.name).suffix.lower().lstrip(".") in exts:
            roms_inside.setdefault(rel, []).append(member.name)
    length = magic_length(config)
    cache = cache or FileCache(None, "")
    name = step("byte-order", config, sorted(exts))

    def read(f: InventoryFile) -> int | None:
        head = None
        try:
            if f.kind == "rom":
                with (root / f.rel_path).open("rb") as handle:
                    head = handle.read(length)
            elif (
                f.rel_path.lower().endswith(ZIP_SUFFIX)
                and len(roms_inside.get(f.rel_path, [])) == 1
            ):
                with (
                    zipfile.ZipFile(root / f.rel_path) as z,
                    z.open(roms_inside[f.rel_path][0]) as m,
                ):
                    head = m.read(length)
        except (OSError, zipfile.BadZipFile, KeyError):
            return None
        return word_bytes(config, head) if head else None

    found = {}
    for f in (progress or Progress()).each("Reading byte orders", files):
        word = cache.get(f, name, lambda f=f: read(f))
        if word is not None:
            found[f.rel_path] = word
    return found


# Card images ----------------------------------------------------------------------


def read_cards(
    settings: Settings,
    platform: str,
    root: Path,
    files,
    members,
    progress=None,
    cache=None,
    open_member: archives.MemberOpener = archives.open_seven_zip_member,
) -> dict:
    """rel_path -> (CardInfo, archive member or None) for each card image the platform's
    header format recognises: a bare file, or a zip's or 7z's one ROM member."""
    profile = settings.platforms.profiles[platform]
    config = settings.card_images.get(profile.card_image or "")
    if config is None:
        return {}
    exts = {e.lower() for e in profile.rom_extensions}
    inside: dict[str, list[archives.Member]] = {}
    for rel, member in members:
        if PurePosixPath(member.name).suffix.lower().lstrip(".") in exts:
            inside.setdefault(rel, []).append(member)
    cache = cache or FileCache(None, "")
    name = step("card", config, sorted(exts))

    def stream(path: Path, member: str):
        return open_member(settings, path, member)

    def read(f: InventoryFile, member: str | None, size: int) -> list | None:
        try:
            info = cards.read_ncsd(config, root / f.rel_path, member, size, stream)
        except archives.ArchiveError:
            return None
        if info is None:
            return None
        return [
            info.image_size,
            info.data_size,
            info.encrypted,
            info.product_code,
            info.seed,
            info.program_id,
        ]

    found = {}
    for f in (progress or Progress()).each("Reading card headers", files):
        if f.kind == "rom":
            member, size = None, f.size
        elif f.kind == "archive" and len(inside.get(f.rel_path, [])) == 1:
            member, size = inside[f.rel_path][0].name, inside[f.rel_path][0].size
        else:
            continue
        info = cache.get(f, name, lambda f=f, member=member, size=size: read(f, member, size))
        if info is not None:
            found[f.rel_path] = (cards.CardInfo(*info), member)
    return found


# The scan ------------------------------------------------------------------------


# A folder's runs (scan.kind): Check files reads what conversion needs and hashes nothing;
# Scan does that, then identifies the files with nothing left to convert.
CHECK = "check"
IDENTIFY = "identify"
# Per-file tables a check writes, and those identification writes (the rest of a file's
# rows: folder_file and its cascade, and the file cache).
INVENTORY_TABLES = ("archive_member", "archive_problem", "card_info", "file_note", "byte_order")
IDENTIFICATION_TABLES = ("identity", "content_hash", "lookup_result", "payload_hash", "suggestion")


@dataclass
class Inventory:
    library: Library
    folder: FolderEntry
    root: Path
    files: list[InventoryFile]
    found: "Found"


# A suggestion from the card's product code ranks above every name-based one.
SERIAL_SCORE = 1.0


class Scanner:
    def __init__(
        self,
        settings: Settings,
        store: LibraryStore,
        registry: DatRegistry,
        report_runner: ReportRunner | None = None,
        seven_zip: archives.SevenZipRunner = archives.run_seven_zip,
        lookup_post: hasheous.Post = hasheous.http_post,
        read_chd: hashing.ChdReader = hashing.chd_track_hashes,
        read_rvz: hashing.RvzReader = hashing.rvz_disc_hash,
        open_member: archives.MemberOpener = archives.open_seven_zip_member,
    ):
        self.settings = settings
        self.store = store
        self.registry = registry
        self.report_runner = report_runner or igir.run_report
        self.seven_zip = seven_zip
        self.lookup_post = lookup_post
        self.read_chd = read_chd
        self.read_rvz = read_rvz
        self.open_member = open_member

    def start(self, conn: sqlite3.Connection, label: str, kind: str = IDENTIFY) -> int:
        reason = journal.busy(conn, label)
        if reason:
            raise ScanError(reason)
        return conn.execute(
            "INSERT INTO scan (folder_label, status, kind) VALUES (?, 'running', ?)",
            (label, kind),
        ).lastrowid

    def run(
        self,
        conn: sqlite3.Connection,
        scan_id: int,
        label: str,
        refresh_lookups: bool = False,
        full: bool = False,
        kind: str = IDENTIFY,
    ) -> None:
        """`kind`: CHECK (what conversion needs, nothing hashed) or IDENTIFY (that, then the
        identification of files with nothing left to convert). `full`: read every file again,
        ignoring what earlier scans read (this app's cache and igir's), for files changed in a
        way their size and mtime do not show."""
        progress = Progress(conn, scan_id, self.settings.jobs.progress_interval_seconds)
        try:
            if kind == CHECK:
                message = self._check(conn, label, progress)
            else:
                try:
                    message = self._scan(conn, label, refresh_lookups, progress, full)
                except ConvertFirst as stopped:
                    # Recorded as the check it was: the set still needs its scan.
                    conn.execute("UPDATE scan SET kind = ? WHERE id = ?", (CHECK, scan_id))
                    message = str(stopped)
            self._finish(conn, scan_id, "done", message)
        except (ScanError, igir.IgirError, mounts.FolderPathError, OSError) as exc:
            self._finish(conn, scan_id, "failed", str(exc))
        except Exception as exc:  # a background job must never stay 'running'
            self._finish(conn, scan_id, "failed", f"unexpected error: {exc!r}")
            raise

    def _finish(self, conn, scan_id, status, message) -> None:
        conn.execute(
            "UPDATE scan SET status = ?, message = ?, "
            "stage = NULL, files_done = NULL, files_total = NULL, "
            "finished_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
            (status, message, scan_id),
        )

    def _inventory(self, conn, label: str, progress: Progress, full: bool) -> "Inventory":
        """The folder's files and what conversion decides on: archive listings, byte orders,
        card headers. Nothing is hashed."""
        library = self.store.load()
        folder: FolderEntry | None = library.folder(label)
        if folder is None:
            raise ScanError("the folder is no longer in the library")
        root = mounts.resolve(self.settings, folder.mount, folder.path)
        if not root.is_dir():
            raise ScanError(f"{root} is not available")
        progress.stage("Listing files")
        files = inventory(
            self.settings, root, folder.platform, self.store.ignored_filenames(library)
        )
        cache = FileCache(conn, label, reuse=not full)
        found = Found(*self._members(root, files, progress, cache), cache=cache)
        found.byte_orders = read_byte_orders(
            self.settings, folder.platform, root, files, found.members, progress, cache
        )
        found.cards = read_cards(
            self.settings,
            folder.platform,
            root,
            files,
            found.members,
            progress,
            cache,
            self.open_member,
        )
        return Inventory(library, folder, root, files, found)

    def waiting(self, conn, library: Library, folder: FolderEntry, root: Path | None) -> set[str]:
        """The folder's files waiting for a conversion (as the Conversion page proposes)."""
        target = self.settings.platforms.targets[self.store.target_for(library, folder.platform)]
        rows = conversion.rows(
            self.settings,
            conn,
            folder.label,
            folder.platform,
            target,
            delete_originals=folder.delete_originals,
            root=root,
        )
        return conversion.waiting(rows)

    def _check(self, conn, label: str, progress: Progress) -> str:
        """Check files: what conversion needs, stored; identification is left as it was."""
        found_files = self._inventory(conn, label, progress, full=False)
        progress.stage("Saving")
        self._store_inventory(conn, label, found_files.files, found_files.found)
        found_files.found.cache.save(conn, {f.rel_path for f in found_files.files})
        waiting = self.waiting(conn, found_files.library, found_files.folder, found_files.root)
        roms = [f for f in found_files.files if f.kind in ("rom", "archive")]
        left = sum(1 for f in roms if f.rel_path in waiting)
        return f"{len(roms)} ROM files checked; {left} to convert"

    def _scan(
        self,
        conn: sqlite3.Connection,
        label: str,
        refresh_lookups: bool,
        progress: Progress,
        full: bool = False,
    ) -> str:
        """Scan: the check, then the identification of the files with nothing left to convert
        (a file waiting for a conversion is identified once it is converted)."""
        found_files = self._inventory(conn, label, progress, full)
        library, folder, root, files, found = (
            found_files.library,
            found_files.folder,
            found_files.root,
            found_files.files,
            found_files.found,
        )
        self._store_inventory(conn, label, files, found)
        found.cache.save(conn, {f.rel_path for f in files})
        waiting = self.waiting(conn, library, folder, root)
        candidates = [f for f in files if f.kind in ("rom", "archive")]
        left = sum(1 for f in candidates if f.rel_path in waiting)
        if left:
            raise ConvertFirst(f"{left} files to convert or discard first; nothing identified")
        final = [f for f in files if f.rel_path not in waiting]
        igir_cache = igir.cache_path(self.settings, label)
        if full:
            igir_cache.unlink(missing_ok=True)
        run_igir = {
            "cache": igir_cache,
            "timeout": igir.time_limit(self.settings, sum(f.size for f in files)),
            "threads": self.store.igir_threads(library),
        }
        if self.settings.platforms.profiles[folder.platform].excess_files:
            run_igir["excess"] = True
        if self.settings.platforms.profiles[folder.platform].title_ids:
            self._title_ids(root, final, found, progress)
        entries = [e for e in self.registry.entries(conn, library, folder.platform) if e.on]
        dats = [(e, self.registry.load(e.version)) for e in entries if e.version is not None]
        if not dats and found.identified:
            # Title IDs identify without a DAT.
            progress.stage("Saving")
            self._store_identity(conn, label, final, found)
            found.cache.save(conn, {f.rel_path for f in files})
            identified = sum(1 for f in candidates if f.rel_path not in waiting)
            return f"{len(found.identified)} of {identified} files identified by title ID"
        if not dats:
            progress.stage("Saving")
            self._store_identity(conn, label, final, found)
            found.cache.save(conn, {f.rel_path for f in files})
            return (
                f"inventory only, {len(files)} files: this platform has no active DAT, so "
                f"nothing was identified (add one in Settings → DATs)"
            )
        parts = {
            e.lower() for e in self.settings.platforms.profiles[folder.platform].part_extensions
        }
        roms = [f for f in final if f.kind in ("rom", "archive")]

        def unmatched() -> list[InventoryFile]:
            # A cue sheet or track the DATs miss waits for conversion: not hashed, not looked
            # up online, not suggested.
            return [
                f
                for f in roms
                if f.rel_path not in found.identified and not _part(f.rel_path, parts)
            ]

        # Names for suggestions and manual matches: every DAT's, the first DAT
        # listing a name being the one it is read with.
        dat_of_name: dict[str, str] = {}
        for entry, dat in dats:
            for game in dat.games:
                dat_of_name.setdefault(game.name, entry.version["sha1"])
        notes: list[str] = []
        duplicates_checked = False
        for entry in entries:
            if entry.lookup:
                if not duplicates_checked:
                    self._duplicates(root, folder.platform, final, found, progress)
                    duplicates_checked = True
                notes += self._look_up(
                    conn,
                    library,
                    folder.platform,
                    root,
                    unmatched(),
                    found,
                    refresh_lookups,
                    progress,
                    entry.id,
                    set(dat_of_name),
                )
                continue
            dat = next(d for e, d in dats if e is entry)
            named = f" ({self._source_label(entry)})" if len(dats) > 1 else ""
            self._dat_pass(
                entry, dat, named, folder.platform, root, roms, unmatched, found, progress, run_igir
            )
        if not duplicates_checked:
            self._duplicates(root, folder.platform, final, found, progress)
        # Every file still unmatched shows its hashes in the table.
        self._hash(folder.platform, root, unmatched(), found, progress, "Hashing unmatched files")
        self._suggest(dat_of_name, [d for _, d in dats], unmatched(), found, progress)
        progress.stage("Saving")
        self._apply_manual(conn, label, final, found, dat_of_name)
        self._store_identity(conn, label, final, found)
        found.cache.save(conn, {f.rel_path for f in files})
        conn.execute(
            "UPDATE scan SET dat_sha1 = ? WHERE folder_label = ? AND status = 'running'",
            (dats[0][0].version["sha1"], label),
        )
        summary = [f"{len(found.identified)} of {len(roms)} ROM files identified"]
        by_dat = Counter(found.dat_of[rel] for rel in found.identified if found.dat_of.get(rel))
        if len(by_dat) > 1:
            summary.append(
                ", ".join(
                    f"{by_dat[e.version['sha1']]} by {self._source_label(e)}"
                    for e, _ in dats
                    if by_dat[e.version["sha1"]]
                )
            )
        online = sum(1 for m in found.identified.values() if m == METHOD_HASHEOUS)
        if online:
            summary.append(f"{online} of them via Hasheous")
        return "; ".join(summary + notes)

    def _source_label(self, entry) -> str:
        source = self.settings.dats.sources.get(entry.id)
        return source.label if source else entry.id

    def _dat_pass(
        self, entry, dat: Dat, named, platform, root, roms, unmatched, found, progress, run_igir
    ) -> None:
        """One DAT's turn: igir's checksum match, then the header-stripped, byte-order and
        trimmed-image checks, on the files no earlier step identified. `run_igir`: the
        folder's igir cache and time limit."""
        sha1 = entry.version["sha1"]
        dat_file = self.settings.paths.data_dir / entry.version["file"]
        modes = self.settings.platforms.profiles[platform].igir_merge_modes
        # igir reports nothing until it is done: this step has no file count.
        progress.stage(f"Matching checksums with igir{named}")
        if modes:
            # Arcade: each mode identifies the sets built its way; none misidentifies.
            by_path: dict[str, set[str]] = {}
            for mode in modes:
                found_now = igir.identified_files(
                    self.report_runner(self.settings, dat_file, root, merge=mode, **run_igir)
                )
                for path, games in found_now.items():
                    by_path.setdefault(path, set()).update(games)
        else:
            by_path = igir.identified_files(
                self.report_runner(self.settings, dat_file, root, **run_igir)
            )
        if run_igir.get("excess"):
            by_path = _without_other_roms(self.settings, platform, root, dat, by_path, found)
        for f in roms:
            if f.rel_path not in found.identified:
                found.identify(
                    f.rel_path,
                    by_path.get(str(root / f.rel_path), set()),
                    METHOD_CHECKSUM,
                    dat=sha1,
                )
        if self.settings.headers.get(platform):
            index = _crc_index(dat)
            name = headerless_step(self.settings, platform)
            for f in progress.each(f"Checking header-stripped data{named}", unmatched()):
                keys = found.cache.get(
                    f, name, lambda f=f: headerless_keys(self.settings, platform, root / f.rel_path)
                )
                found.identify(f.rel_path, _look(index, keys), METHOD_HEADERLESS, dat=sha1)
        if self.settings.byte_orders.get(platform):
            index = _crc_index(dat)
            name = byte_order_step(self.settings, platform)
            for f in progress.each(f"Checking byte orders{named}", unmatched()):
                keys = found.cache.get(
                    f, name, lambda f=f: byte_order_keys(self.settings, platform, root / f.rel_path)
                )
                as_is, native = _look(index, keys["as_is"]), _look(index, keys["native"])
                found.identify(f.rel_path, as_is, METHOD_CHECKSUM, dat=sha1)
                found.identify(f.rel_path, native - as_is, METHOD_BYTESWAPPED, dat=sha1)
        self._untrimmed(platform, root, unmatched(), dat, found, progress, sha1, named)

    def _content_hashes(self, platform, root, f: InventoryFile, found: "Found") -> list:
        """A file's hashes (CRC32, MD5, SHA1 of each ROM payload, header-stripped too; a
        CHD's data track, an RVZ's disc): read once, then from the scan cache while the file
        is unchanged. Every step that needs a file's hashes asks here."""
        if f.rel_path not in found.hashes:
            profile = self.settings.platforms.profiles[platform]
            name = step(
                "content-hashes",
                profile.rom_extensions,
                self.settings.headers.get(platform, []),
                self.settings.byte_orders.get(platform),
                self.settings.lookups.chd,
                self.settings.dolphin,
            )
            found.hashes[f.rel_path] = [
                ContentHash(**h)
                for h in found.cache.get(
                    f,
                    name,
                    lambda: [
                        asdict(h)
                        for h in content_hashes(
                            self.settings,
                            platform,
                            root / f.rel_path,
                            self.read_chd,
                            self.read_rvz,
                        )
                    ],
                )
            ]
        return found.hashes[f.rel_path]

    def _hash(self, platform, root, files, found: "Found", progress, stage: str) -> None:
        """CRC32, MD5 and SHA1 of each file's ROM data, for lookups and the table."""
        for f in progress.each(stage, [f for f in files if f.rel_path not in found.hashes]):
            self._content_hashes(platform, root, f, found)

    def _why_no_hashes(self, f: InventoryFile, found: "Found") -> str:
        """Why an unmatched file has nothing to look up."""
        if f.rel_path.lower().endswith(CHD_SUFFIX):
            return "the disc's tracks could not be read"
        if f.rel_path.lower().endswith(RVZ_SUFFIX):
            return "the disc could not be read"
        if any(
            rel == f.rel_path and member.name.lower().endswith(RVZ_SUFFIX)
            for rel, member in found.members
        ):
            return "an RVZ inside an archive: convert it first"
        return "no ROM data to look up"

    def _look_up(
        self, conn, library, platform, root, unmatched, found, refresh, progress, service, dat_names
    ) -> list[str]:
        """Hasheous's turn: hash what is still unmatched and ask it, when switched on."""
        if service != hasheous.SERVICE or not library.lookups.hasheous:
            return []
        profile = self.settings.platforms.profiles[platform]
        where = hasheous.platform(profile, dat_names)
        self._hash(platform, root, unmatched, found, progress, "Hashing unmatched files")
        notes = []
        for f in progress.each("Looking up unmatched files on Hasheous", unmatched):
            hashes = found.hashes[f.rel_path]
            skipped = None
            if not hashes:
                skipped = self._why_no_hashes(f, found)
            elif payload_count(hashes) > 1:
                # One answer would name one game and hide the others in the archive.
                skipped = "several ROM files in one archive"
            if skipped:
                found.lookups[(f.rel_path, service)] = (hasheous.SKIPPED, skipped)
                continue
            try:
                answer = hasheous.lookup(
                    self.settings,
                    conn,
                    hashes,
                    where,
                    self.lookup_post,
                    refresh=refresh,
                )
            except hasheous.LookupError_ as exc:
                found.lookups[(f.rel_path, service)] = (hasheous.ERROR, str(exc))
                notes.append(f"online lookups stopped: {exc}")
                break
            found.lookups[(f.rel_path, service)] = (answer.status, answer.detail)
            if answer.status == hasheous.FOUND and answer.game_name:
                found.identify(f.rel_path, {answer.game_name}, METHOD_HASHEOUS)
            elif answer.known_as:
                found.known_as[f.rel_path] = list(answer.known_as)
        return notes

    def _duplicates(self, root: Path, platform: str, files, found: "Found", progress) -> None:
        """Identification step 2: an unmatched file byte-identical to an identified one is
        a version of that file's game. Also hashes identified files that may be identical
        copies of each other (same game, same payload size), for the 1G1R table.
        """
        rom_extensions = {
            e.lower() for e in self.settings.platforms.profiles[platform].rom_extensions
        }
        roms_inside: dict[str, list[archives.Member]] = {}
        for rel, member in found.members:
            if PurePosixPath(member.name).suffix.lower().lstrip(".") in rom_extensions:
                roms_inside.setdefault(rel, []).append(member)

        def payload_size(f: InventoryFile) -> int | None:
            if f.kind == "rom" and f.rel_path.lower().endswith(CHD_SUFFIX):
                identity = chd_identity(root / f.rel_path)
                return identity[0] if identity else None
            if f.kind == "rom" and f.rel_path.lower().endswith(RVZ_SUFFIX):
                # Not a size: a key equal only for the same disc of the same game.
                return rvz_identity(root / f.rel_path)
            if f.kind == "rom":
                return f.size
            # Only zips are read for their data here (hashing.payloads); 7z is not compared.
            inside = roms_inside.get(f.rel_path, [])
            readable = f.kind == "archive" and f.rel_path.lower().endswith(ZIP_SUFFIX)
            return inside[0].size if readable and len(inside) == 1 else None

        games: dict[str, set[str]] = {}
        for rel, game, *_ in found.identities:
            games.setdefault(rel, set()).add(game)
        sized = [(f, payload_size(f)) for f in files if f.kind in ("rom", "archive")]
        sized = [(f, size) for f, size in sized if size is not None]
        identified = [(f, size) for f, size in sized if f.rel_path in games]
        unmatched = [(f, size) for f, size in sized if f.rel_path not in games]
        identified_sizes = {size for _, size in identified}
        unmatched_sizes = {size for _, size in unmatched}
        per_game = Counter((game, size) for f, size in identified for game in games[f.rel_path])
        wanted = [
            (f, size)
            for f, size in identified
            if size in unmatched_sizes or any(per_game[(g, size)] > 1 for g in games[f.rel_path])
        ] + [(f, size) for f, size in unmatched if size in identified_sizes]
        # Identical copies have equal sizes, then equal first bytes (the probe), then equal
        # SHA1s: only files whose size and probe are shared are read whole.
        probe = step("probe", sorted(rom_extensions), self.settings.hashing.probe_bytes)
        keys: dict[str, tuple] = {}
        for f, size in progress.each("Comparing the start of possible duplicates", wanted):
            if f.rel_path.lower().endswith((CHD_SUFFIX, RVZ_SUFFIX)):
                # Their key names the disc already (a CHD's is its header's SHA1).
                keys[f.rel_path] = (size, "")
                continue
            start = found.cache.get(
                f, probe, lambda f=f: probe_sha1(self.settings, root / f.rel_path, rom_extensions)
            )
            if start is not None:
                keys[f.rel_path] = (size, start)
        shared = Counter(keys.values())
        alike = [(f, size) for f, size in wanted if shared[keys.get(f.rel_path)] > 1]
        for f, size in progress.each("Looking for duplicates", alike):
            if f.rel_path.lower().endswith(CHD_SUFFIX):
                identity = chd_identity(root / f.rel_path)
                sha1 = identity[1] if identity else None
            else:
                hashes = self._content_hashes(platform, root, f, found)
                full = [h for h in hashes if h.variant == hashing.FULL]
                sha1 = full[0].sha1 if payload_count(hashes) == 1 and full else None
            if sha1 is not None:
                # An RVZ's key starts with the disc's size, which is what is stored.
                stored = int(size.split(":")[0]) if isinstance(size, str) else size
                found.payloads[f.rel_path] = (stored, sha1)
        originals: dict[str, str] = {}
        for f, _ in sorted(identified, key=lambda pair: pair[0].rel_path):
            if f.rel_path in found.payloads:
                originals.setdefault(found.payloads[f.rel_path][1], f.rel_path)
        for f, _ in unmatched:
            original = originals.get(found.payloads.get(f.rel_path, (None, None))[1])
            if original is not None:
                found.identify(
                    f.rel_path,
                    games[original],
                    METHOD_DUPLICATE,
                    dat=found.dat_of.get(original, NO_DAT),
                )

    def _title_ids(self, root: Path, files, found: "Found", progress) -> None:
        """Switch: every file with a title ID (ticket or name) is identified by it; the
        identity's name carries the ID, which matching groups by."""
        config = self.settings.title_ids
        if config is None:
            return
        name = step("title", config)

        def read(f: InventoryFile) -> list | None:
            title = titles.read_title(root / f.rel_path, PurePosixPath(f.rel_path).name, config)
            return None if title is None else [title.title_id, title.version, title.name]

        for f in progress.each("Reading title IDs", files):
            if f.kind not in ("rom", "archive"):
                continue
            value = found.cache.get(f, name, lambda f=f: read(f))
            title = None if value is None else titles.Title(*value)
            if title is not None:
                found.identify(f.rel_path, {titles.identity_name(title, config)}, METHOD_TITLE_ID)

    def _untrimmed(
        self, platform, root: Path, unmatched, dat: Dat, found: "Found", progress, sha1, named
    ) -> None:
        """A trimmed card image is the DAT's entry once padded back to the card's size."""
        profile = self.settings.platforms.profiles[platform]
        config = self.settings.card_images.get(profile.card_image or "")
        if config is None:
            return
        index = _crc_index(dat)
        name = step("padded-crc", config)

        def read(f: InventoryFile, info: cards.CardInfo, member: str | None) -> str | None:
            try:
                return cards.padded_crc(
                    config,
                    root / f.rel_path,
                    member,
                    info.image_size,
                    self.settings.apply.copy_chunk_bytes,
                )
            except (OSError, zipfile.BadZipFile, KeyError):
                return None

        for f in progress.each(f"Checking trimmed images{named}", unmatched):
            card = found.cards.get(f.rel_path)
            if card is None or not card[0].trimmed:
                continue
            info, member = card
            crc = found.cache.get(f, name, lambda f=f, i=info, m=member: read(f, i, m))
            if crc is None:
                continue
            found.identify(
                f.rel_path, index.get((crc, info.image_size), set()), METHOD_UNTRIMMED, dat=sha1
            )

    def _suggest(
        self, dat_of_name, dats: list[Dat], unmatched: list[InventoryFile], found: "Found", progress
    ) -> None:
        """Every DAT's names that look like the file's, closest first."""
        config = self.settings.fuzzy
        names = list(dat_of_name)
        by_serial: dict[str, list[str]] = {}
        for dat in dats:
            for g in dat.games:
                if g.serial and g.name not in by_serial.get(g.serial.upper(), []):
                    by_serial.setdefault(g.serial.upper(), []).append(g.name)
        for f in progress.each("Suggesting names", unmatched):
            best = fuzzy.suggestions(config, f.rel_path, names)
            card = found.cards.get(f.rel_path)
            code = card[0].product_code.upper() if card else ""
            if by_serial.get(code):
                # The card's own product code (an encrypted image never has the DAT's hash):
                # the entries with that serial first, ordered by how well the name fits.
                fits = dict(best)
                same = sorted(by_serial[code], key=lambda n: (-fits.get(n, 0), n))
                found.suggestions[f.rel_path] = [
                    *[(n, SERIAL_SCORE) for n in same],
                    *[b for b in best if b[0] not in same],
                ][: config.max_suggestions]
                # A product code is not a checksum, and revisions share it: never auto-matched.
                continue
            known = found.known_as.get(f.rel_path, [])
            if known:
                # What another database calls the data is a better hint than the file name.
                scores = dict(best)
                for hint in known:
                    for name, score in fuzzy.suggestions(config, fuzzy.bare_title(hint), names):
                        scores[name] = max(score, scores.get(name, 0))
                best = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
                best = best[: config.max_suggestions]
            found.suggestions[f.rel_path] = best
            threshold = config.auto_match_threshold
            single = payload_count(found.hashes.get(f.rel_path, [])) <= 1
            if best and single and threshold is not None and best[0][1] >= threshold:
                found.identify(
                    f.rel_path,
                    {best[0][0]},
                    METHOD_FUZZY,
                    best[0][1],
                    dat=dat_of_name.get(best[0][0], NO_DAT),
                )

    def _apply_manual(self, conn, label, files, found: "Found", dat_of_name) -> None:
        present = {f.rel_path for f in files}
        for rel_path, game in conn.execute(
            "SELECT rel_path, game_name FROM manual_identity WHERE folder_label = ?", (label,)
        ):
            if rel_path in present:
                found.forget(rel_path)
                found.identify(rel_path, {game}, METHOD_MANUAL, dat=dat_of_name.get(game, NO_DAT))

    def _members(
        self, root: Path, files: list[InventoryFile], progress: Progress, cache: FileCache
    ):
        members: list[tuple[str, archives.Member]] = []
        problems: list[tuple[str, str]] = []
        in_archives = [f for f in files if f.kind == "archive"]

        def read(f: InventoryFile) -> dict:
            try:
                listed = archives.list_members(self.settings, root / f.rel_path, self.seven_zip)
            except archives.ArchiveError as exc:
                return {"error": str(exc)}
            return {"members": [[m.name, m.size, m.crc32] for m in listed]}

        for f in progress.each("Reading archives", in_archives):
            # Renamed when the listing changes (B11: 7z folders), so no old one is reused.
            value = cache.get(f, "archive-members", lambda f=f: read(f))
            if "error" in value:
                problems.append((f.rel_path, value["error"]))
                continue
            members += [(f.rel_path, archives.Member(*m)) for m in value["members"]]
        return members, problems

    def _store_inventory(self, conn, label, files, found: "Found") -> None:
        """The folder's files and what a check read. A file unchanged since the last run keeps
        its identification; a changed, new or vanished one loses it (the cascade)."""
        listed = {f.rel_path: (f.size, f.mtime_ns, f.kind) for f in files}
        # Taking the write lock first: a transaction that reads before it writes cannot wait
        # for another scan's write and fails with "database is locked".
        conn.execute("BEGIN IMMEDIATE")
        try:
            stored = conn.execute(
                "SELECT rel_path, size, mtime_ns, kind FROM folder_file "
                "WHERE folder_label = ? AND place = 'folder'",
                (label,),
            ).fetchall()
            kept = {
                r["rel_path"]
                for r in stored
                if listed.get(r["rel_path"]) == (r["size"], r["mtime_ns"], r["kind"])
            }
            # Files an apply moved to discarded/ keep their rows (and identities) so the table
            # still shows them; one that is back in the folder is scanned afresh instead.
            conn.executemany(
                "DELETE FROM folder_file WHERE folder_label = ? AND rel_path = ? "
                "AND place = 'folder'",
                [(label, r["rel_path"]) for r in stored if r["rel_path"] not in kept],
            )
            conn.executemany(
                "DELETE FROM folder_file WHERE folder_label = ? AND rel_path = ? "
                "AND place != 'folder'",
                [(label, rel) for rel in listed],
            )
            conn.executemany(
                "INSERT INTO folder_file (folder_label, rel_path, size, mtime_ns, kind) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    (label, f.rel_path, f.size, f.mtime_ns, f.kind)
                    for f in files
                    if f.rel_path not in kept
                ],
            )
            for table in INVENTORY_TABLES:
                conn.executemany(
                    f"DELETE FROM {table} WHERE folder_label = ? AND rel_path = ?",
                    [(label, rel) for rel in kept],
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
                "INSERT INTO card_info VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        label,
                        rel,
                        info.image_size,
                        info.data_size,
                        info.encrypted,
                        info.seed,
                        info.product_code,
                        info.program_id,
                    )
                    for rel, (info, _) in found.cards.items()
                ],
            )
            conn.executemany(
                "INSERT INTO file_note VALUES (?, ?, ?)",
                [
                    (label, rel, note)
                    for rel, (info, _) in found.cards.items()
                    for note in info.notes()
                ],
            )
            conn.executemany(
                "INSERT INTO byte_order VALUES (?, ?, ?)",
                [(label, rel, word) for rel, word in found.byte_orders.items()],
            )
            conn.execute("COMMIT")
        except sqlite3.Error:
            conn.execute("ROLLBACK")
            raise

    def _store_identity(self, conn, label, files, found: "Found") -> None:
        """What identification found for `files` (those with nothing left to convert),
        replacing what an earlier scan found for them. Other files keep theirs."""
        rels = [(label, f.rel_path) for f in files]
        conn.execute("BEGIN IMMEDIATE")
        try:
            for table in IDENTIFICATION_TABLES:
                conn.executemany(
                    f"DELETE FROM {table} WHERE folder_label = ? AND rel_path = ?", rels
                )
            # Looked at: unidentified now means unmatched, no longer "not scanned yet".
            conn.executemany(
                "UPDATE folder_file SET scanned = 1 WHERE folder_label = ? AND rel_path = ? "
                "AND place = 'folder'",
                rels,
            )
            conn.executemany(
                "INSERT OR IGNORE INTO identity (folder_label, rel_path, game_name, method, "
                "dat_sha1, score) VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (label, rel, game, method, dat_sha1, score)
                    for rel, game, method, score, dat_sha1 in found.identities
                ],
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
                    (label, rel, service, status, detail)
                    for (rel, service), (status, detail) in found.lookups.items()
                ],
            )
            conn.executemany(
                "INSERT INTO payload_hash VALUES (?, ?, ?, ?)",
                [(label, rel, size, sha1) for rel, (size, sha1) in found.payloads.items()],
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


def _without_other_roms(
    settings: Settings, platform: str, root: Path, dat: Dat, by_path, found: "Found"
) -> dict[str, set[str]]:
    """igir's matches with excess files allowed, less any archive holding a ROM file (a
    platform extension) that is not one of the game's, or whose CRC32 is not listed."""
    rom_extensions = {e.lower() for e in settings.platforms.profiles[platform].rom_extensions}
    crcs = {g.name: {(r.crc or "").lower() for r in g.roms} - {""} for g in dat.games}
    roms_in: dict[str, list[str | None]] = {}
    for rel, member in found.members:
        if PurePosixPath(member.name).suffix.lower().lstrip(".") in rom_extensions:
            roms_in.setdefault(str(root / rel), []).append(member.crc32)
    return {
        path: {
            game
            for game in games
            if all(
                crc is not None and crc.lower() in crcs.get(game, set())
                for crc in roms_in.get(path, [])
            )
        }
        for path, games in by_path.items()
    }


@dataclass
class Found:
    """What a scan learned about a folder's files, stored together at the end."""

    members: list[tuple[str, archives.Member]]
    problems: list[tuple[str, str]]
    # (rel_path, game_name, method, score, the DAT's sha1 or NO_DAT)
    identities: list[tuple[str, str, str, float, str]] = field(default_factory=list)
    # rel_path -> the method that identified it first
    identified: dict[str, str] = field(default_factory=dict)
    # rel_path -> the DAT that identified it (NO_DAT: an online lookup or a title ID)
    dat_of: dict[str, str] = field(default_factory=dict)
    hashes: dict[str, list[ContentHash]] = field(default_factory=dict)
    # (rel_path, service) -> (status, detail)
    lookups: dict[tuple[str, str], tuple[str, str]] = field(default_factory=dict)
    # rel_path -> names Hasheous's other sources give the data that no DAT lists: hints for
    # the suggestions
    known_as: dict[str, list[str]] = field(default_factory=dict)
    suggestions: dict[str, list[tuple[str, float]]] = field(default_factory=dict)
    # rel_path -> (payload size, payload SHA1), where a duplicate was possible
    payloads: dict[str, tuple[int, str]] = field(default_factory=dict)
    # rel_path -> word length to reverse for the native byte order (swapped dumps only)
    byte_orders: dict[str, int] = field(default_factory=dict)
    # rel_path -> (cards.CardInfo, zip member or None), for card images (3DS)
    cards: dict[str, tuple] = field(default_factory=dict)
    # What earlier scans read from unchanged files; this scan's reads are added to it.
    cache: FileCache = field(default_factory=lambda: FileCache(None, ""))

    def identify(self, rel_path, games, method, score=CHECKSUM_SCORE, dat=NO_DAT) -> None:
        for game in sorted(games):
            self.identities.append((rel_path, game, method, score, dat))
            self.identified.setdefault(rel_path, method)
            self.dat_of.setdefault(rel_path, dat)

    def forget(self, rel_path: str) -> None:
        self.identities = [i for i in self.identities if i[0] != rel_path]
        self.identified.pop(rel_path, None)
        self.dat_of.pop(rel_path, None)


def fail_interrupted(conn: sqlite3.Connection) -> None:
    """Scans still 'running' at start-up were cut off by a restart."""
    conn.execute(
        "UPDATE scan SET status = 'failed', message = 'interrupted by a restart', "
        "finished_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE status = 'running'"
    )


def latest_scan(
    conn: sqlite3.Connection, label: str, kind: str | None = None
) -> sqlite3.Row | None:
    """The folder's latest run, or its latest of one kind (CHECK or IDENTIFY)."""
    if kind is None:
        return conn.execute(
            "SELECT * FROM scan WHERE folder_label = ? ORDER BY id DESC LIMIT 1", (label,)
        ).fetchone()
    return conn.execute(
        "SELECT * FROM scan WHERE folder_label = ? AND kind = ? ORDER BY id DESC LIMIT 1",
        (label, kind),
    ).fetchone()


def folder_summary(
    conn: sqlite3.Connection, label: str, parts=frozenset(), waiting=frozenset()
) -> dict:
    """The folder's counts. `waiting`: files a conversion is proposed for; with the cue
    sheets and tracks (`parts`) they wait for conversion, neither identified nor unmatched."""
    counts = {
        row["kind"]: row["n"]
        for row in conn.execute(
            "SELECT kind, COUNT(*) AS n FROM folder_file WHERE folder_label = ? "
            "AND place = 'folder' GROUP BY kind",
            (label,),
        )
    }
    roms = rom_paths(conn, label)
    held = {r for r in roms if r in waiting or _part(r, parts)}
    methods: dict[str, int] = {}
    known = set()
    for rel, method in conn.execute(
        "SELECT DISTINCT i.rel_path, i.method FROM identity i JOIN folder_file f "
        "USING (folder_label, rel_path) WHERE i.folder_label = ? AND f.place = 'folder'",
        (label,),
    ):
        if rel in held:
            continue
        if rel not in known:
            methods[method] = methods.get(method, 0) + 1
        known.add(rel)
    size = conn.execute(
        "SELECT COALESCE(SUM(size), 0) FROM folder_file "
        "WHERE folder_label = ? AND place = 'folder'",
        (label,),
    ).fetchone()[0]
    unscanned = len(unscanned_files(conn, label, parts, waiting))
    return {
        "counts": counts,
        "roms": len(roms),
        # Every file in the folder, as last scanned (ROMs, frontend files, the rest).
        "bytes": size,
        "identified": len(known),
        "unmatched": len(roms) - len(known) - len(held) - unscanned,
        # Listed (by Check files, or new since the last scan) but not looked at by a Scan.
        "unscanned": unscanned,
        # Waiting for a conversion (cue sheets and tracks included): identified once converted.
        "waiting": len(held),
        "methods": methods,
    }


def _part(rel_path: str, parts) -> bool:
    return PurePosixPath(rel_path).suffix.lower().lstrip(".") in parts


def rom_paths(conn: sqlite3.Connection, label: str) -> list[str]:
    """The ROM files in the folder (what folder_summary counts as roms)."""
    return [
        row["rel_path"]
        for row in conn.execute(
            "SELECT rel_path FROM folder_file WHERE folder_label = ? "
            "AND kind IN ('rom', 'archive') AND place = 'folder'",
            (label,),
        )
    ]


def unmatched_files(
    conn: sqlite3.Connection, label: str, parts=frozenset(), waiting=frozenset()
) -> list[sqlite3.Row]:
    """Unidentified ROM files; parts of a game (cue sheets, tracks) and files a conversion
    is proposed for (`waiting`) wait for conversion instead."""
    return [r for r in _unidentified(conn, label, parts, waiting) if r["scanned"]]


def unscanned_files(
    conn: sqlite3.Connection, label: str, parts=frozenset(), waiting=frozenset()
) -> list[sqlite3.Row]:
    """Unidentified ROM files no Scan has looked at yet (listed by Check files, new or changed
    since the last scan, or a conversion's output): not unmatched, not scanned yet."""
    return [r for r in _unidentified(conn, label, parts, waiting) if not r["scanned"]]


def _unidentified(conn, label, parts, waiting) -> list[sqlite3.Row]:
    found = conn.execute(
        """SELECT f.* FROM folder_file f
           WHERE f.folder_label = ? AND f.kind IN ('rom', 'archive') AND f.place = 'folder'
             AND NOT EXISTS (SELECT 1 FROM identity i
                             WHERE i.folder_label = f.folder_label AND i.rel_path = f.rel_path)
           ORDER BY f.rel_path""",
        (label,),
    ).fetchall()
    return [r for r in found if not _part(r["rel_path"], parts) and r["rel_path"] not in waiting]


def other_files(conn: sqlite3.Connection, label: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM folder_file WHERE folder_label = ? AND kind IN ('other', 'ignored') "
        "AND place = 'folder' "
        "ORDER BY kind, rel_path",
        (label,),
    ).fetchall()


def unsupported_files(
    conn: sqlite3.Connection, label: str, rom_extensions: list[str], romsets: bool
) -> list[dict]:
    """Files the app leaves alone because they are not in a format the platform supports:
    an unknown extension, or an archive with no supported ROM inside (an arcade romset's
    chips have no fixed extensions, so romsets are not looked into)."""
    exts = {e.lower() for e in rom_extensions}
    inside: dict[str, set[str]] = {}
    for rel, member in conn.execute(
        "SELECT rel_path, member FROM archive_member WHERE folder_label = ?", (label,)
    ):
        inside.setdefault(rel, set()).add(PurePosixPath(member).suffix.lower().lstrip("."))
    result = []
    for row in conn.execute(
        "SELECT rel_path, size, kind FROM folder_file WHERE folder_label = ? "
        "AND kind IN ('other', 'archive') AND place = 'folder' ORDER BY rel_path",
        (label,),
    ):
        rel = row["rel_path"]
        if row["kind"] == "other":
            ext = PurePosixPath(rel).suffix.lower().lstrip(".")
            reason = f".{ext} is not a supported format" if ext else "no file extension"
        elif not romsets and rel in inside and not inside[rel] & exts:
            found = ", ".join(f".{e}" if e else "no extension" for e in sorted(inside[rel]))
            reason = f"no supported ROM inside (it holds {found})"
        else:
            continue
        result.append({"rel_path": rel, "size": row["size"], "reason": reason})
    return result
