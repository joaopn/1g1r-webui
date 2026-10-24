"""The per-platform DAT registry: stored versions (database) and the active one (library.yaml).

Sources: the libretro mirror (one-click download), No-Intro DAT-o-MATIC files (uploaded,
singly or as a daily pack, which is split by platform), and any uploaded override.
"""

import hashlib
import io
import re
import sqlite3
import time
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath

from g1r import titledb, tosec
from g1r.config import LOOKUP_ENTRIES, PlatformProfile, Settings
from g1r.dats import Dat, DatError, parse_dat_bytes, parsed
from g1r.library import ActiveDat, Library, LibraryStore, PlatformDats

Fetch = Callable[[str], bytes]
DAT_SUFFIXES = (".dat", ".xml")


# Downloads may come zipped (redump.info); a zip starts with these bytes.
ZIP_MAGIC = b"PK\x03\x04"


class RegistryError(ValueError):
    """A DAT could not be added or activated; the message is shown to the user."""


@dataclass
class PackResult:
    member: str
    platform: str | None
    version_id: int | None
    message: str


# TOSEC DATs carry it in their header name; the merged DAT is "<dat_name> (TOSEC)".
TOSEC_MARK = "(TOSEC)"
TOSEC_STYLE = "tosec"
NOINTRO_STYLE = "nointro"


def name_style(version: sqlite3.Row | None) -> str:
    """How the active DAT's names read: TOSEC style for a TOSEC DAT (downloaded, from a
    pack, or uploaded on its own), No-Intro/Redump style otherwise."""
    if version is None:
        return NOINTRO_STYLE
    header = version["header_name"] or ""
    tosec_dat = version["source"] == TOSEC_STYLE or TOSEC_STYLE in header.lower()
    return TOSEC_STYLE if tosec_dat else NOINTRO_STYLE


@dataclass(frozen=True)
class Entry:
    """One step of a platform's identification order: a source's active DAT (`version`
    set) or an online lookup."""

    id: str
    on: bool
    version: sqlite3.Row | None = None
    # A titledb region file: names and details by title ID, no checksums.
    titledb: bool = False

    @property
    def lookup(self) -> bool:
        return self.id in LOOKUP_ENTRIES


def _suffixes(profile: PlatformProfile, header_name: str) -> list[str] | None:
    """The parenthesised groups after the platform's DAT name, or None when the name is not
    the platform's name followed only by such groups."""
    if not header_name.startswith(profile.dat_name):
        return None
    rest = header_name[len(profile.dat_name) :]
    groups = re.findall(r" (\([^()]*\))", rest)
    return groups if "".join(f" {g}" for g in groups) == rest else None


def header_matches(settings: Settings, profile: PlatformProfile, header_name: str) -> bool:
    """The platform's DAT name, alone or with format variants ('... (Headered)'); another
    suffix names a different set ('Nintendo - Wii (Development Kit Hard Drives)')."""
    groups = _suffixes(profile, header_name)
    allowed = {*settings.dats.variant_suffixes, TOSEC_MARK}
    return groups is not None and all(g in allowed for g in groups)


def side_set_of(settings: Settings, header_name: str) -> str | None:
    """The platform whose DAT name this one extends with a suffix that is not a variant."""
    for platform, profile in settings.platforms.enabled_profiles().items():
        groups = _suffixes(profile, header_name)
        if groups and not header_matches(settings, profile, header_name):
            return platform
    return None


class DatRegistry:
    def __init__(self, settings: Settings, store: LibraryStore, fetch: Fetch | None = None):
        self.settings = settings
        self.store = store
        self.fetch = fetch or self._http_fetch
        # titledb's region files and when they were read.
        self._titledb_files: tuple[float, list[str]] | None = None
        # Each platform's kept versions.json, with the mtime it was read at.
        self._titledb_latest: dict[str, tuple[float, dict]] = {}

    def _http_fetch(self, url: str, timeout: float | None = None) -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": self.settings.dats.user_agent})
        with urllib.request.urlopen(
            request, timeout=timeout or self.settings.dats.download_timeout_seconds
        ) as r:
            return r.read(self.settings.dats.max_upload_bytes + 1)

    # Adding ----------------------------------------------------------------------

    def add(
        self,
        conn: sqlite3.Connection,
        platform: str,
        data: bytes,
        *,
        source: str,
        origin: str | None,
        original_name: str | None,
        matches_platform: bool | None = None,
    ) -> int:
        profile = self._profile(platform)
        if len(data) > self.settings.dats.max_upload_bytes:
            raise RegistryError("the file is larger than dats.max_upload_bytes")
        try:
            dat = parse_dat_bytes(data)
        except DatError as exc:
            raise RegistryError(f"not a usable DAT: {exc}") from exc
        if not dat.games:
            raise RegistryError("the DAT contains no games")
        sha1 = hashlib.sha1(data).hexdigest()
        existing = conn.execute(
            "SELECT id FROM dat_version WHERE platform = ? AND sha1 = ?", (platform, sha1)
        ).fetchone()
        if existing:
            version_id = existing["id"]
        else:
            relative = PurePosixPath(self.settings.dats.directory, platform, f"{sha1}.dat")
            target = self.settings.paths.data_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            matches = (
                header_matches(self.settings, profile, dat.header.name)
                if matches_platform is None
                else matches_platform
            )
            version_id = self._insert(
                conn, platform, source, str(relative), dat, sha1, matches, origin, original_name
            )
        self._maybe_activate(conn, platform, version_id)
        return version_id

    def _insert(self, conn, platform, source, file, dat: Dat, sha1, matches, origin, name) -> int:
        cursor = conn.execute(
            """INSERT INTO dat_version (platform, source, file, original_name, origin,
                   header_name, description, version, date, sha1, game_count,
                   has_parent_clone, matches_platform)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                platform,
                source,
                file,
                name,
                origin,
                dat.header.name,
                dat.header.description,
                dat.header.version,
                dat.header.date,
                sha1,
                len(dat.games),
                int(dat.has_parent_clone),
                int(matches),
            ),
        )
        return cursor.lastrowid

    def remove_source(self, conn: sqlite3.Connection, source: str) -> tuple[int, list[str]]:
        """Every stored DAT of this source, on every platform, leaves the library: its
        active entries, its versions and their files. Sets keep their matches until their
        next scan. Returns how many versions went and from which platforms."""
        config = self.settings.titledb
        if source == config.short_label:
            # Every titledb region file.
            prefix = config.entry_prefix
            rows = [
                r
                for r in conn.execute("SELECT id, platform, file, source FROM dat_version")
                if r["source"].startswith(prefix)
            ]
        elif source in self.settings.dats.sources:
            rows = conn.execute(
                "SELECT id, platform, file, source FROM dat_version WHERE source = ?", (source,)
            ).fetchall()
        else:
            raise RegistryError(f"unknown DAT source {source!r}")
        sources = {row["source"] for row in rows} | {source}

        def change(library: Library) -> None:
            for dats in library.dats.values():
                for gone in sources:
                    dats.active.pop(gone, None)

        # The library first: an active entry whose version is gone is skipped, never used.
        self.store.update(change)
        for row in rows:
            conn.execute("DELETE FROM dat_version WHERE id = ?", (row["id"],))
        if source == config.short_label:
            for platform in {row["platform"] for row in rows}:
                self._versions_path(platform).unlink(missing_ok=True)
        for row in rows:
            (self.settings.paths.data_dir / row["file"]).unlink(missing_ok=True)
        return len(rows), sorted({row["platform"] for row in rows})

    def recheck_names(self, conn: sqlite3.Connection) -> None:
        """At start-up: whether each stored DAT's name is its platform's follows the current
        rule, so a side set taken for the platform before (B7) shows "name differs"."""
        rows = conn.execute("SELECT id, platform, header_name, source FROM dat_version").fetchall()
        for row in rows:
            profile = self.settings.platforms.profiles.get(row["platform"])
            if profile is None:
                continue
            # A titledb file is named after itself, never after the platform.
            matches = self.is_titledb(row["source"]) or header_matches(
                self.settings, profile, row["header_name"]
            )
            conn.execute(
                "UPDATE dat_version SET matches_platform = ? WHERE id = ?",
                (int(matches), row["id"]),
            )

    def _maybe_activate(self, conn, platform: str, version_id: int) -> None:
        source = conn.execute(
            "SELECT source FROM dat_version WHERE id = ?", (version_id,)
        ).fetchone()["source"]
        current = self.store.load().dats.get(platform, PlatformDats()).active.get(source)
        if current is None or (self.settings.dats.auto_activate_new and not current.pinned):
            self.activate(conn, platform, version_id)

    # titledb ----------------------------------------------------------------------

    def is_titledb(self, entry: str) -> bool:
        return titledb.file_of(self.settings.titledb, entry) is not None

    def titledb_files(self) -> list[str]:
        """Every titledb region file ("US.en"), from its languages list (read again after
        `languages_ttl_seconds`)."""
        config = self.settings.titledb
        now = time.monotonic()
        if self._titledb_files and now - self._titledb_files[0] < config.languages_ttl_seconds:
            return self._titledb_files[1]
        try:
            files = titledb.files_from_languages(config, self.fetch(config.languages_url))
        except OSError as exc:
            raise RegistryError(f"titledb's file list could not be read: {exc}") from exc
        except titledb.TitleDbError as exc:
            raise RegistryError(str(exc)) from exc
        self._titledb_files = (now, files)
        return files

    def download_titledb(self, conn: sqlite3.Connection, platform: str, file: str) -> int:
        """A titledb region file, kept as a DAT of its title IDs and made an entry of the
        platform's order (the first version of a file is used at once)."""
        profile = self._profile(platform)
        if not profile.title_ids:
            raise RegistryError(f"{profile.name} games have no title IDs: titledb is Switch only")
        config = self.settings.titledb
        if file not in config.featured and file not in self.titledb_files():
            raise RegistryError(f"titledb has no file {file!r}")
        url = config.url_template.format(file=urllib.parse.quote(file))
        try:
            data = self._fetch_long(url, config.timeout_seconds)
        except OSError as exc:
            raise RegistryError(f"download failed: {exc}") from exc
        if len(data) > config.max_download_bytes:
            raise RegistryError("the file is larger than titledb.max_download_bytes")
        version = time.strftime(config.version_format)
        try:
            dat, _ = titledb.to_dat(config, file, data, version)
            latest = titledb.latest_versions(self._fetch_long(config.versions_url, None))
        except OSError as exc:
            raise RegistryError(f"download failed: {exc}") from exc
        except titledb.TitleDbError as exc:
            raise RegistryError(str(exc)) from exc
        version_id = self.add(
            conn,
            platform,
            dat,
            source=titledb.entry_id(config, file),
            origin=url,
            original_name=f"{file}.json",
            matches_platform=True,
        )
        # Every update version released, refreshed with each region file.
        target = self._versions_path(platform)
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".part")
        partial.write_bytes(titledb.versions_json(latest))
        partial.replace(target)
        return version_id

    def _versions_path(self, platform: str):
        return self.settings.dats_root / platform / self.settings.titledb.versions_file

    def titledb_latest(self, platform: str) -> dict[str, titledb.Latest]:
        """The newest update version titledb knows per title ID (empty before a titledb
        file was downloaded)."""
        path = self._versions_path(platform)
        if not path.is_file():
            return {}
        mtime = path.stat().st_mtime
        kept = self._titledb_latest.get(platform)
        if kept is None or kept[0] != mtime:
            kept = (mtime, titledb.read_versions(path.read_bytes()))
            self._titledb_latest[platform] = kept
        return kept[1]

    def download_libretro(self, conn: sqlite3.Connection, platform: str) -> int:
        return self.download(conn, platform, "libretro")

    def downloads(self, platform: str) -> list[str]:
        """The sources the platform's DAT can be downloaded from, in the order shown."""
        profile = self._profile(platform)
        found: list[str] = []
        if not profile.dat_download:
            return found
        for source_id, source in self.settings.dats.sources.items():
            if source.index_url:
                # TOSEC: a second source beside the platform's own (No-Intro) DAT.
                if profile.tosec_prefixes:
                    found.append(source_id)
                continue
            if not source.url_template:
                continue
            if source.families and profile.dat_family not in source.families:
                continue
            if "{system}" in source.url_template and not profile.redump_system:
                continue
            if "{dat_file}" in source.url_template and not profile.dat_file:
                continue
            found.append(source_id)
        return found

    def download(self, conn: sqlite3.Connection, platform: str, source_id: str) -> int:
        profile = self._profile(platform)
        if source_id not in self.downloads(platform):
            raise RegistryError(f"{platform} cannot be downloaded from {source_id}")
        source = self.settings.dats.sources[source_id]
        if source.index_url:
            return self._download_tosec(conn, platform, source_id)
        family = self.settings.dats.families[profile.dat_family]
        url = source.url_template.format(
            name=urllib.parse.quote(profile.dat_name),
            family=urllib.parse.quote(family.libretro_dir),
            system=urllib.parse.quote(profile.redump_system or ""),
            dat_file=urllib.parse.quote(profile.dat_file or ""),
        )
        try:
            data = self.fetch(url)
        except OSError as exc:
            raise RegistryError(f"download failed: {exc}") from exc
        name = f"{profile.dat_name}.dat"
        if data[: len(ZIP_MAGIC)] == ZIP_MAGIC:
            members = self._zip_dats(data)
            if len(members) != 1:
                raise RegistryError(f"the download holds {len(members)} DATs, expected one")
            name, data = members[0]
        return self.add(conn, platform, data, source=source_id, origin=url, original_name=name)

    def _download_tosec(self, conn, platform: str, source_id: str) -> int:
        """The newest TOSEC pack (kept for the next platform), this platform's DATs merged."""
        source = self.settings.dats.sources[source_id]
        try:
            url = tosec.latest_pack_url(self.fetch, source)
            cache = self.settings.paths.data_dir / (source.cache_dir or "")
            cached = cache / urllib.parse.quote(url, safe="")
            if cached.is_file():
                data = cached.read_bytes()
            else:
                data = self._fetch_long(url, source.timeout_seconds)
                cache.mkdir(parents=True, exist_ok=True)
                for old in cache.iterdir():
                    old.unlink()
                cached.write_bytes(data)
            merged = self._tosec_merged(platform, tosec.open_pack(data), source.member_dir or "")
        except OSError as exc:
            raise RegistryError(f"download failed: {exc}") from exc
        except tosec.TosecError as exc:
            raise RegistryError(str(exc)) from exc
        profile = self._profile(platform)
        return self.add(
            conn, platform, merged, source=source_id, origin=url, original_name=profile.dat_name
        )

    def _fetch_long(self, url: str, timeout: float | None) -> bytes:
        if self.fetch == self._http_fetch:
            return self._http_fetch(url, timeout)
        return self.fetch(url)

    def _tosec_merged(self, platform: str, archive: zipfile.ZipFile, member_dir: str) -> bytes:
        profile = self._profile(platform)
        dats = tosec.platform_dats(
            archive,
            profile.tosec_dir or member_dir,
            profile.tosec_prefixes,
            self.settings.dats.max_upload_bytes,
        )
        return tosec.merge(dats, f"{profile.dat_name} {TOSEC_MARK}")

    def add_upload(self, conn, platform: str, data: bytes, filename: str) -> int:
        """One uploaded .dat/.xml, or a .zip holding exactly one."""
        source = "nointro" if self._looks_nointro(data) else "upload"
        if filename.lower().endswith(".zip"):
            members = self._zip_dats(data)
            if len(members) != 1:
                raise RegistryError(
                    "the zip holds several DATs; use 'Upload No-Intro daily pack' for packs"
                )
            filename, data = members[0]
            source = "nointro" if self._looks_nointro(data) else "upload"
        return self.add(conn, platform, data, source=source, origin=None, original_name=filename)

    def add_pack(self, conn: sqlite3.Connection, data: bytes) -> list[PackResult]:
        """A DAT-o-MATIC daily pack: each DAT goes to the enabled platform it names. A TOSEC
        pack: each TOSEC platform gets its DATs merged into one."""
        tosec_dirs = {
            s.member_dir
            for s in self.settings.dats.sources.values()
            if s.index_url and s.member_dir
        }
        archive = tosec.open_pack(data) if data[: len(ZIP_MAGIC)] == ZIP_MAGIC else None
        member_dir = next(
            (d for d in sorted(tosec_dirs) if archive and tosec.is_pack(archive, d)), None
        )
        if archive is not None and member_dir is not None:
            return self._add_tosec_pack(conn, archive, member_dir)
        results = []
        profiles = self.settings.platforms.enabled_profiles()
        for name, member in self._zip_dats(data):
            try:
                dat = parse_dat_bytes(member)
            except DatError as exc:
                results.append(PackResult(name, None, None, f"skipped: {exc}"))
                continue
            header = dat.header.name
            platform = next(
                (p for p, prof in profiles.items() if header_matches(self.settings, prof, header)),
                None,
            )
            side = side_set_of(self.settings, header) if platform is None else None
            if side is not None:
                label = profiles[side].name
                message = f"skipped: another {label} set, not its games"
                results.append(PackResult(name, None, None, message))
                continue
            if platform is None:
                results.append(PackResult(name, None, None, "skipped: not a supported platform"))
                continue
            try:
                version_id = self.add(
                    conn, platform, member, source="nointro", origin=None, original_name=name
                )
                results.append(PackResult(name, platform, version_id, "added"))
            except RegistryError as exc:
                results.append(PackResult(name, platform, None, f"skipped: {exc}"))
        return results

    def _add_tosec_pack(self, conn, archive: zipfile.ZipFile, member_dir: str) -> list[PackResult]:
        results = []
        for platform, profile in self.settings.platforms.enabled_profiles().items():
            if not profile.tosec_prefixes:
                continue
            try:
                merged = self._tosec_merged(platform, archive, member_dir)
                version_id = self.add(
                    conn,
                    platform,
                    merged,
                    source="tosec",
                    origin=None,
                    original_name=profile.dat_name,
                )
            except (tosec.TosecError, RegistryError) as exc:
                results.append(PackResult(profile.dat_name, platform, None, f"skipped: {exc}"))
                continue
            results.append(PackResult(profile.dat_name, platform, version_id, "added"))
        return results

    def _zip_dats(self, data: bytes) -> list[tuple[str, bytes]]:
        try:
            archive = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as exc:
            raise RegistryError("not a valid zip file") from exc
        members, total = [], 0
        for info in archive.infolist():
            if info.is_dir() or not info.filename.lower().endswith(DAT_SUFFIXES):
                continue
            total += info.file_size
            if total > self.settings.dats.max_upload_bytes:
                raise RegistryError("the zip unpacks to more than dats.max_upload_bytes")
            members.append((PurePosixPath(info.filename).name, archive.read(info)))
        if not members:
            raise RegistryError("the zip holds no .dat or .xml file")
        return members

    @staticmethod
    def _looks_nointro(data: bytes) -> bool:
        return b"<homepage>No-Intro</homepage>" in data or b"datomatic.no-intro.org" in data

    # Activating ------------------------------------------------------------------

    def activate(self, conn: sqlite3.Connection, platform: str, version_id: int) -> None:
        """Make this version its source's active one for the platform."""
        row = conn.execute(
            "SELECT * FROM dat_version WHERE id = ? AND platform = ?", (version_id, platform)
        ).fetchone()
        if row is None:
            raise RegistryError("unknown DAT version")

        def change(library: Library) -> None:
            dats = library.dats.setdefault(platform, PlatformDats())
            current = dats.active.get(row["source"])
            if current and current.pinned and current.sha1 != row["sha1"]:
                raise RegistryError("this source's active DAT is pinned; unpin it first")
            dats.active[row["source"]] = ActiveDat(
                source=row["source"],
                file=row["file"],
                header_name=row["header_name"],
                version=row["version"],
                sha1=row["sha1"],
                pinned=bool(current and current.pinned),
            )

        self.store.update(change)

    def set_pinned(self, platform: str, source: str, pinned: bool) -> None:
        def change(library: Library) -> None:
            active = library.dats.get(platform, PlatformDats()).active.get(source)
            if active is None:
                raise RegistryError("no active DAT of that source to pin")
            active.pinned = pinned

        self.store.update(change)

    def _check_order(self, order: list[str], off: list[str], extra: set[str] = frozenset()) -> None:
        known = set(self.settings.dats.priority) | extra
        if len(set(order)) != len(order) or not set(order) <= known or not set(off) <= known:
            raise RegistryError(f"the order may list only {sorted(known)}, each once")

    def set_order(self, platform: str, order: list[str] | None, off: list[str]) -> None:
        """The platform's own identification order and the entries switched off there;
        None: follow the global order again."""
        self._profile(platform)
        if order is not None:
            active = self.store.load().dats.get(platform, PlatformDats()).active
            self._check_order(order, off, {e for e in active if self.is_titledb(e)})

        def change(library: Library) -> None:
            dats = library.dats.setdefault(platform, PlatformDats())
            dats.order = None if order is None else list(order)
            dats.off = [] if order is None else sorted(set(off))

        self.store.update(change)

    def set_global_order(self, order: list[str] | None, off: list[str]) -> None:
        """The order every platform without its own follows; None: the default."""
        if order is not None:
            self._check_order(order, off)

        def change(library: Library) -> None:
            library.dat_order = None if order is None else list(order)
            library.dat_off = [] if order is None else sorted(set(off))

        self.store.update(change)

    def global_order(self, library: Library) -> list[str]:
        """Every source and lookup in the global order (one the order misses, at the end in
        its default place)."""
        chosen = [e for e in (library.dat_order or []) if e in self.settings.dats.priority]
        return chosen + [e for e in self.settings.dats.priority if e not in chosen]

    def off(self, library: Library, platform: str) -> set[str]:
        dats = library.dats.get(platform, PlatformDats())
        return set(dats.off if dats.order is not None else library.dat_off)

    # Reading ---------------------------------------------------------------------

    def versions(self, conn: sqlite3.Connection, platform: str) -> list[sqlite3.Row]:
        return conn.execute(
            "SELECT * FROM dat_version WHERE platform = ? ORDER BY added_at DESC, id DESC",
            (platform,),
        ).fetchall()

    def order(self, library: Library, platform: str) -> list[str]:
        """Every source with an active DAT and every online lookup, in the platform's order.
        One the chosen order does not name (a source added since) takes its default place
        among its kind: before the first DAT the default order puts after it, else after
        the last one it puts before it, else (none of its kind yet) a DAT before the
        lookups, a lookup at the end."""
        dats = library.dats.get(platform, PlatformDats())
        default = self.settings.dats.priority
        # titledb region files, in the order they were added, rank after every other DAT.
        files = [e for e in dats.active if self.is_titledb(e)]
        sources = [e for e in default if e not in LOOKUP_ENTRIES]

        def rank(entry: str) -> int:
            return len(sources) if entry in files else default.index(entry)

        present = [
            *(e for e in sources if e in dats.active),
            *files,
            *(e for e in default if e in LOOKUP_ENTRIES),
        ]
        chosen = dats.order if dats.order is not None else self.global_order(library)
        order = [e for e in chosen if e in present]
        for entry in present:
            if entry in order:
                continue
            kin = [
                (i, rank(e))
                for i, e in enumerate(order)
                if (e in LOOKUP_ENTRIES) == (entry in LOOKUP_ENTRIES)
            ]
            later = [i for i, r in kin if r > rank(entry)]
            # Equal ranks (titledb files): after the ones already placed.
            earlier = [i for i, r in kin if r <= rank(entry)]
            # Without one of its kind placed: a DAT before the lookups, a lookup at the end.
            lookups = [i for i, e in enumerate(order) if e in LOOKUP_ENTRIES]
            alone = lookups[0] if lookups and entry not in LOOKUP_ENTRIES else len(order)
            at = later[0] if later else (earlier[-1] + 1 if earlier else alone)
            order.insert(at, entry)
        return order

    def entries(self, conn, library: Library, platform: str) -> list[Entry]:
        """The platform's identification order, each DAT with its stored version."""
        dats = library.dats.get(platform, PlatformDats())
        off = self.off(library, platform)
        found = []
        for entry in self.order(library, platform):
            version = None
            if entry not in LOOKUP_ENTRIES:
                version = conn.execute(
                    "SELECT * FROM dat_version WHERE platform = ? AND sha1 = ?",
                    (platform, dats.active[entry].sha1),
                ).fetchone()
                if version is None:
                    continue
            found.append(Entry(entry, entry not in off, version, self.is_titledb(entry)))
        return found

    def active_versions(self, conn, library: Library, platform: str) -> list[sqlite3.Row]:
        """The DATs that identify the platform's files, in order (switched-off ones left
        out)."""
        return [
            e.version
            for e in self.entries(conn, library, platform)
            if e.on and e.version is not None
        ]

    def active_version(self, conn, library: Library, platform: str) -> sqlite3.Row | None:
        """The first DAT of the platform's order."""
        versions = self.active_versions(conn, library, platform)
        return versions[0] if versions else None

    def load(self, version: sqlite3.Row) -> Dat:
        return parsed(self.settings.paths.data_dir / version["file"], version["sha1"])

    def load_active(self, conn, library: Library, platform: str) -> Dat | None:
        row = self.active_version(conn, library, platform)
        return None if row is None else self.load(row)

    def load_all(self, conn, library: Library, platform: str) -> list[tuple[sqlite3.Row, Dat]]:
        """The DATs whose names a file can be matched to by hand (titledb files name title
        IDs, not files)."""
        return [
            (v, self.load(v))
            for v in self.active_versions(conn, library, platform)
            if not self.is_titledb(v["source"])
        ]

    def titledb_titles(self, conn, library: Library, platform: str) -> list[dict]:
        """The platform's titledb files that are on, in order, each by title ID."""
        return [
            titledb.index(e.version["sha1"], self.load(e.version))
            for e in self.entries(conn, library, platform)
            if e.on and e.titledb
        ]

    def _profile(self, platform: str) -> PlatformProfile:
        profiles = self.settings.platforms.enabled_profiles()
        if platform not in profiles:
            raise RegistryError(f"{platform!r} is not a supported platform")
        return profiles[platform]
