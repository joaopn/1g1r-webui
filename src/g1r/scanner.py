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
import zlib
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath

from g1r import (
    archives,
    cards,
    discs,
    fuzzy,
    hasheous,
    igir,
    journal,
    mounts,
    screenscraper,
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
    header_size,
    magic_length,
    native_order,
    payload_count,
    payload_sha1,
    payloads,
    rvz_identity,
    word_bytes,
)
from g1r.library import FolderEntry, LibraryStore

METHOD_CHECKSUM = "dat-checksum"
METHOD_HEADERLESS = "dat-headerless"
METHOD_BYTESWAPPED = "dat-byteswapped"
METHOD_UNTRIMMED = "dat-untrimmed"
METHOD_TITLE_ID = "title-id"
# identity.dat_sha1 of an identification that needed no DAT (title IDs).
NO_DAT = ""
METHOD_DUPLICATE = "duplicate"
METHOD_HASHEOUS = "hasheous"
METHOD_SCREENSCRAPER = "screenscraper"
METHOD_FUZZY = "fuzzy"
METHOD_MANUAL = "manual"
CHECKSUM_SCORE = 1.0

# (settings, dat file, folder[, merge=mode]) -> report rows
ReportRunner = Callable[..., list[igir.ReportRow]]


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
        settings.dats.max_upload_bytes,
    )


def headerless_keys(settings: Settings, platform: str, path: Path) -> list[list]:
    """[CRC, size] of each ROM's data with its copier header removed, for every header rule
    that recognises it."""
    rules = settings.headers.get(platform, [])
    if not rules:
        return []
    profile = settings.platforms.profiles[platform]
    exts = {e.lower() for e in profile.rom_extensions}
    keys = []
    for data in payloads(path, exts, settings.dats.max_upload_bytes):
        for rule in rules:
            size = header_size(rule, data)
            if size is None:
                continue
            body = data[size:]
            keys.append([format(zlib.crc32(body), "08x"), len(body)])
    return keys


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
        settings.dats.max_upload_bytes,
    )


def byte_order_keys(settings: Settings, platform: str, path: Path) -> dict[str, list[list]]:
    """[CRC, size] of each ROM's data as it is, and in the native byte order."""
    config = settings.byte_orders.get(platform)
    keys: dict[str, list[list]] = {"as_is": [], "native": []}
    if config is None:
        return keys
    exts = {e.lower() for e in settings.platforms.profiles[platform].rom_extensions}

    def key(data: bytes) -> list:
        return [format(zlib.crc32(data), "08x"), len(data)]

    for data in payloads(path, exts, settings.dats.max_upload_bytes):
        keys["as_is"].append(key(data))
        swapped = native_order(config, data)
        if swapped is not None:
            keys["native"].append(key(swapped))
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
    settings: Settings, platform: str, root: Path, files, members, progress=None, cache=None
) -> dict:
    """rel_path -> (CardInfo, zip member or None) for each card image the platform's header
    format recognises: a bare file, or a zip's one ROM member."""
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

    def read(f: InventoryFile, member: str | None, size: int) -> list | None:
        info = cards.read_ncsd(config, root / f.rel_path, member, size)
        if info is None:
            return None
        return [info.image_size, info.data_size, info.encrypted, info.product_code]

    found = {}
    for f in (progress or Progress()).each("Reading card headers", files):
        if f.kind == "rom":
            member, size = None, f.size
        elif f.rel_path.lower().endswith(ZIP_SUFFIX) and len(inside.get(f.rel_path, [])) == 1:
            member, size = inside[f.rel_path][0].name, inside[f.rel_path][0].size
        else:
            continue
        info = cache.get(f, name, lambda f=f, member=member, size=size: read(f, member, size))
        if info is not None:
            found[f.rel_path] = (cards.CardInfo(*info), member)
    return found


# The scan ------------------------------------------------------------------------


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
        screenscraper_get: screenscraper.Get = screenscraper.http_get,
    ):
        self.settings = settings
        self.store = store
        self.registry = registry
        self.report_runner = report_runner or igir.run_report
        self.seven_zip = seven_zip
        self.lookup_post = lookup_post
        self.screenscraper_get = screenscraper_get

    def start(self, conn: sqlite3.Connection, label: str) -> int:
        reason = journal.busy(conn, label)
        if reason:
            raise ScanError(reason)
        return conn.execute(
            "INSERT INTO scan (folder_label, status) VALUES (?, 'running')", (label,)
        ).lastrowid

    def run(
        self,
        conn: sqlite3.Connection,
        scan_id: int,
        label: str,
        refresh_lookups: bool = False,
        full: bool = False,
    ) -> None:
        """`full`: read every file again, ignoring what earlier scans read (this app's cache
        and igir's), for files changed in a way their size and mtime do not show."""
        progress = Progress(conn, scan_id, self.settings.jobs.progress_interval_seconds)
        try:
            message = self._scan(conn, label, refresh_lookups, progress, full)
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

    def _scan(
        self,
        conn: sqlite3.Connection,
        label: str,
        refresh_lookups: bool,
        progress: Progress,
        full: bool = False,
    ) -> str:
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
            self.settings, folder.platform, root, files, found.members, progress, cache
        )
        if self.settings.platforms.profiles[folder.platform].title_ids:
            self._title_ids(root, files, found, progress)
        active = self.registry.active_version(conn, library, folder.platform)
        if active is None and found.identified:
            # Title IDs identify without a DAT.
            progress.stage("Saving")
            self._store(conn, label, files, NO_DAT, found)
            candidates = sum(1 for f in files if f.kind in ("rom", "archive"))
            return f"{len(found.identified)} of {candidates} files identified by title ID"
        if active is None:
            progress.stage("Saving")
            self._store(conn, label, files, None, found)
            return (
                f"inventory only, {len(files)} files: this platform has no active DAT, so "
                "nothing was identified (add one in Settings → DATs)"
            )
        dat_file = self.settings.paths.data_dir / active["file"]
        modes = self.settings.platforms.profiles[folder.platform].igir_merge_modes
        # igir reports nothing until it is done: this step has no file count.
        progress.stage("Matching checksums with igir")
        # A full scan has igir hash every file again too.
        fresh = {"fresh": True} if full else {}
        if modes:
            # Arcade: each mode identifies the sets built its way; none misidentifies.
            by_path: dict[str, set[str]] = {}
            for mode in modes:
                found_now = igir.identified_files(
                    self.report_runner(self.settings, dat_file, root, merge=mode, **fresh)
                )
                for path, games in found_now.items():
                    by_path.setdefault(path, set()).update(games)
        else:
            by_path = igir.identified_files(
                self.report_runner(self.settings, dat_file, root, **fresh)
            )
        parts = {
            e.lower() for e in self.settings.platforms.profiles[folder.platform].part_extensions
        }
        unmatched = []
        for f in files:
            if f.kind not in ("rom", "archive") or f.rel_path in found.identified:
                continue
            games = by_path.get(str(root / f.rel_path), set())
            if games:
                found.identify(f.rel_path, games, METHOD_CHECKSUM)
            elif not _part(f.rel_path, parts):
                # A cue sheet or track the DAT misses waits for conversion: not hashed,
                # not looked up online, not suggested.
                unmatched.append(f)
        dat = self.registry.load_active(conn, library, folder.platform)
        if unmatched and self.settings.headers.get(folder.platform):
            index = _crc_index(dat)
            name = headerless_step(self.settings, folder.platform)
            for f in progress.each("Checking header-stripped data", unmatched):
                keys = cache.get(
                    f,
                    name,
                    lambda f=f: headerless_keys(self.settings, folder.platform, root / f.rel_path),
                )
                found.identify(f.rel_path, _look(index, keys), METHOD_HEADERLESS)
        unmatched = [f for f in unmatched if f.rel_path not in found.identified]
        if self.settings.byte_orders.get(folder.platform):
            index = _crc_index(dat)
            name = byte_order_step(self.settings, folder.platform)
            for f in progress.each("Checking byte orders", unmatched):
                keys = cache.get(
                    f,
                    name,
                    lambda f=f: byte_order_keys(self.settings, folder.platform, root / f.rel_path),
                )
                as_is, native = _look(index, keys["as_is"]), _look(index, keys["native"])
                found.identify(f.rel_path, as_is, METHOD_CHECKSUM)
                found.identify(f.rel_path, native - as_is, METHOD_BYTESWAPPED)
        unmatched = [f for f in unmatched if f.rel_path not in found.identified]
        self._untrimmed(folder.platform, root, unmatched, dat, found, progress)
        unmatched = [f for f in unmatched if f.rel_path not in found.identified]
        self._duplicates(root, folder.platform, files, found, progress)
        unmatched = [f for f in unmatched if f.rel_path not in found.identified]
        notes = self._look_up(
            conn, library, folder.platform, root, unmatched, found, refresh_lookups, dat, progress
        )
        unmatched = [f for f in unmatched if f.rel_path not in found.identified]
        self._suggest(dat, unmatched, found, progress)
        progress.stage("Saving")
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

    def _look_up(
        self, conn, library, platform, root, unmatched, found, refresh, dat, progress
    ) -> list[str]:
        """Identification steps 3 and 4: hash what the DAT missed; ask Hasheous, then
        ScreenScraper, for the services that are on."""
        profile = self.settings.platforms.profiles[platform]
        hasheous_on = library.lookups.hasheous
        session = self._screenscraper(library, profile)
        dat_names = {g.name for g in dat.games} if session else set()
        services = [
            service
            for service, on in ((hasheous.SERVICE, hasheous_on), (screenscraper.SERVICE, session))
            if on
        ]
        notes = []
        stage = "Looking up unmatched files online" if services else "Hashing unmatched files"
        name = step(
            "content-hashes",
            profile.rom_extensions,
            self.settings.headers.get(platform, []),
            self.settings.byte_orders.get(platform),
            self.settings.lookups.max_hash_bytes,
        )
        for f in progress.each(stage, unmatched):
            hashes = [
                ContentHash(**h)
                for h in found.cache.get(
                    f,
                    name,
                    lambda f=f: [
                        asdict(h)
                        for h in content_hashes(self.settings, platform, root / f.rel_path)
                    ],
                )
            ]
            found.hashes[f.rel_path] = hashes
            skipped = None
            if not hashes:
                skipped = "no ROM data to look up"
            elif payload_count(hashes) > 1:
                # One answer would name one game and hide the others in the archive.
                skipped = "several ROM files in one archive"
            if skipped:
                for service in services:
                    found.lookups[(f.rel_path, service)] = (hasheous.SKIPPED, skipped)
                continue
            if hasheous_on:
                try:
                    answer = hasheous.lookup(
                        self.settings,
                        conn,
                        hashes,
                        profile.dat_name,
                        self.lookup_post,
                        refresh=refresh,
                    )
                except hasheous.LookupError_ as exc:
                    found.lookups[(f.rel_path, hasheous.SERVICE)] = (hasheous.ERROR, str(exc))
                    notes.append(f"online lookups stopped: {exc}")
                    hasheous_on = False
                else:
                    found.lookups[(f.rel_path, hasheous.SERVICE)] = (answer.status, answer.detail)
                    if answer.status == hasheous.FOUND and answer.game_name:
                        found.identify(f.rel_path, {answer.game_name}, METHOD_HASHEOUS)
                        continue
            if session and not session.stopped:
                try:
                    answer = screenscraper.lookup(
                        session,
                        conn,
                        hashes,
                        profile.screenscraper_id,
                        dat_names,
                        refresh=refresh,
                    )
                except screenscraper.LookupError_ as exc:
                    found.lookups[(f.rel_path, screenscraper.SERVICE)] = (
                        screenscraper.ERROR,
                        str(exc),
                    )
                    notes.append(f"ScreenScraper lookups stopped: {exc}")
                    continue
                found.lookups[(f.rel_path, screenscraper.SERVICE)] = (
                    answer.status,
                    answer.detail,
                )
                if answer.status == screenscraper.FOUND and answer.game_name:
                    found.identify(f.rel_path, {answer.game_name}, METHOD_SCREENSCRAPER)
                elif answer.known_as:
                    found.known_as[f.rel_path] = answer.known_as
        return notes

    def _screenscraper(self, library, profile) -> "screenscraper.Session | None":
        """A session for this scan, when ScreenScraper is on, configured and knows the
        platform."""
        config = self.settings.lookups.screenscraper
        if not library.lookups.screenscraper or profile.screenscraper_id is None:
            return None
        creds = screenscraper.credentials(self.settings)
        if creds is None:
            return None
        return screenscraper.Session(config, creds, self.screenscraper_get)

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
        for rel, game, _, _ in found.identities:
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
        limit = self.settings.lookups.max_hash_bytes
        byte_order = self.settings.byte_orders.get(platform)
        name = step("payload-sha1", sorted(rom_extensions), limit, byte_order)
        for f, size in progress.each("Looking for duplicates", wanted):
            sha1 = found.cache.get(
                f,
                name,
                lambda f=f: payload_sha1(
                    root / f.rel_path, rom_extensions, limit, self._rvz_sha1, byte_order
                ),
            )
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
                found.identify(f.rel_path, games[original], METHOD_DUPLICATE)

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
        self, platform, root: Path, unmatched, dat: Dat, found: "Found", progress
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

        for f in progress.each("Checking trimmed images", unmatched):
            card = found.cards.get(f.rel_path)
            if card is None or not card[0].trimmed:
                continue
            info, member = card
            crc = found.cache.get(f, name, lambda f=f, i=info, m=member: read(f, i, m))
            if crc is None:
                continue
            found.identify(f.rel_path, index.get((crc, info.image_size), set()), METHOD_UNTRIMMED)

    def _rvz_sha1(self, path: Path) -> str | None:
        dolphin = self.settings.dolphin
        try:
            return discs.rvz_sha1(dolphin, self.settings.paths.data_dir / dolphin.user_dir, path)
        except discs.DiscError:
            return None

    def _suggest(self, dat: Dat, unmatched: list[InventoryFile], found: "Found", progress) -> None:
        config = self.settings.fuzzy
        names = [g.name for g in dat.games]
        by_serial: dict[str, list[str]] = {}
        for g in dat.games:
            if g.serial:
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
            known = found.known_as.get(f.rel_path)
            if known:
                # ScreenScraper's name for the data is a better hint than the file name.
                scores = dict(best)
                for name, score in fuzzy.suggestions(config, known, names):
                    scores[name] = max(score, scores.get(name, 0))
                best = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
                best = best[: config.max_suggestions]
            found.suggestions[f.rel_path] = best
            threshold = config.auto_match_threshold
            single = payload_count(found.hashes.get(f.rel_path, [])) <= 1
            if best and single and threshold is not None and best[0][1] >= threshold:
                found.identify(f.rel_path, {best[0][0]}, METHOD_FUZZY, best[0][1])

    def _apply_manual(self, conn, label, files, found: "Found") -> None:
        present = {f.rel_path for f in files}
        for rel_path, game in conn.execute(
            "SELECT rel_path, game_name FROM manual_identity WHERE folder_label = ?", (label,)
        ):
            if rel_path in present:
                found.forget(rel_path)
                found.identify(rel_path, {game}, METHOD_MANUAL)

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
            value = cache.get(f, "members", lambda f=f: read(f))
            if "error" in value:
                problems.append((f.rel_path, value["error"]))
                continue
            members += [(f.rel_path, archives.Member(*m)) for m in value["members"]]
        return members, problems

    def _store(self, conn, label, files, dat_sha1, found: "Found") -> None:
        conn.execute("BEGIN")
        try:
            # Files an apply moved to discarded/ keep their rows (and identities) so the table
            # still shows them; one that is back in the folder is scanned afresh instead.
            conn.execute(
                "DELETE FROM folder_file WHERE folder_label = ? AND place = 'folder'", (label,)
            )
            conn.executemany(
                "DELETE FROM folder_file WHERE folder_label = ? AND rel_path = ?",
                [(label, f.rel_path) for f in files],
            )
            conn.executemany(
                "INSERT INTO folder_file (folder_label, rel_path, size, mtime_ns, kind) "
                "VALUES (?, ?, ?, ?, ?)",
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
                    (label, rel, service, status, detail)
                    for (rel, service), (status, detail) in found.lookups.items()
                ],
            )
            conn.executemany(
                "INSERT INTO payload_hash VALUES (?, ?, ?, ?)",
                [(label, rel, size, sha1) for rel, (size, sha1) in found.payloads.items()],
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
            found.cache.save(conn, {f.rel_path for f in files})
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
    # (rel_path, service) -> (status, detail)
    lookups: dict[tuple[str, str], tuple[str, str]] = field(default_factory=dict)
    # rel_path -> ScreenScraper's name for data no DAT entry has: used for suggestions
    known_as: dict[str, str] = field(default_factory=dict)
    suggestions: dict[str, list[tuple[str, float]]] = field(default_factory=dict)
    # rel_path -> (payload size, payload SHA1), where a duplicate was possible
    payloads: dict[str, tuple[int, str]] = field(default_factory=dict)
    # rel_path -> word length to reverse for the native byte order (swapped dumps only)
    byte_orders: dict[str, int] = field(default_factory=dict)
    # rel_path -> (cards.CardInfo, zip member or None), for card images (3DS)
    cards: dict[str, tuple] = field(default_factory=dict)
    # What earlier scans read from unchanged files; this scan's reads are added to it.
    cache: FileCache = field(default_factory=lambda: FileCache(None, ""))

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


def folder_summary(conn: sqlite3.Connection, label: str, parts=frozenset()) -> dict:
    counts = {
        row["kind"]: row["n"]
        for row in conn.execute(
            "SELECT kind, COUNT(*) AS n FROM folder_file WHERE folder_label = ? "
            "AND place = 'folder' GROUP BY kind",
            (label,),
        )
    }
    identified = conn.execute(
        "SELECT COUNT(DISTINCT i.rel_path) FROM identity i JOIN folder_file f "
        "USING (folder_label, rel_path) WHERE i.folder_label = ? AND f.place = 'folder'",
        (label,),
    ).fetchone()[0]
    methods = {
        row["method"]: row["n"]
        for row in conn.execute(
            "SELECT i.method, COUNT(DISTINCT i.rel_path) AS n FROM identity i JOIN folder_file f "
            "USING (folder_label, rel_path) WHERE i.folder_label = ? AND f.place = 'folder' "
            "GROUP BY i.method",
            (label,),
        )
    }
    roms = counts.get("rom", 0) + counts.get("archive", 0)
    waiting = 0
    unidentified_parts = 0
    if parts:
        for row in conn.execute(
            "SELECT f.rel_path, EXISTS (SELECT 1 FROM identity i WHERE i.folder_label = "
            "f.folder_label AND i.rel_path = f.rel_path) AS known FROM folder_file f "
            "WHERE f.folder_label = ? AND f.kind = 'rom' AND f.place = 'folder'",
            (label,),
        ):
            if _part(row["rel_path"], parts):
                waiting += 1
                unidentified_parts += not row["known"]
    return {
        "counts": counts,
        "roms": roms,
        "identified": identified,
        "unmatched": roms - identified - unidentified_parts,
        # Cue sheets and tracks: they become versions once converted to one file.
        "waiting": waiting,
        "methods": methods,
    }


def _part(rel_path: str, parts) -> bool:
    return PurePosixPath(rel_path).suffix.lower().lstrip(".") in parts


def unmatched_files(conn: sqlite3.Connection, label: str, parts=frozenset()) -> list[sqlite3.Row]:
    """Unidentified ROM files; parts of a game (cue sheets, tracks) wait for conversion."""
    found = conn.execute(
        """SELECT f.* FROM folder_file f
           WHERE f.folder_label = ? AND f.kind IN ('rom', 'archive') AND f.place = 'folder'
             AND NOT EXISTS (SELECT 1 FROM identity i
                             WHERE i.folder_label = f.folder_label AND i.rel_path = f.rel_path)
           ORDER BY f.rel_path""",
        (label,),
    ).fetchall()
    return [r for r in found if not _part(r["rel_path"], parts)]


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
