"""The per-platform DAT registry: stored versions (database) and the active one (library.yaml).

Sources: the libretro mirror (one-click download), No-Intro DAT-o-MATIC files (uploaded,
singly or as a daily pack, which is split by platform), and any uploaded override.
"""

import hashlib
import io
import sqlite3
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath

from g1r import tosec
from g1r.config import PlatformProfile, Settings
from g1r.dats import Dat, DatError, parse_dat_bytes
from g1r.library import ActiveDat, Library, LibraryStore

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


def header_matches(profile: PlatformProfile, header_name: str) -> bool:
    """No-Intro names some DATs with a suffix, e.g. 'Nintendo - ... (Headered)'."""
    return header_name == profile.dat_name or header_name.startswith(profile.dat_name + " (")


class DatRegistry:
    def __init__(self, settings: Settings, store: LibraryStore, fetch: Fetch | None = None):
        self.settings = settings
        self.store = store
        self.fetch = fetch or self._http_fetch

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
            version_id = self._insert(
                conn, platform, source, str(relative), dat, sha1, profile, origin, original_name
            )
        self._maybe_activate(conn, platform, version_id)
        return version_id

    def _insert(self, conn, platform, source, file, dat: Dat, sha1, profile, origin, name) -> int:
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
                int(header_matches(profile, dat.header.name)),
            ),
        )
        return cursor.lastrowid

    def _maybe_activate(self, conn, platform: str, version_id: int) -> None:
        library = self.store.load()
        current = library.dats.get(platform)
        if current is None or (self.settings.dats.auto_activate_new and not current.pinned):
            self.activate(conn, platform, version_id)

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
            archive, member_dir, profile.tosec_prefixes, self.settings.dats.max_upload_bytes
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
            platform = next(
                (p for p, prof in profiles.items() if header_matches(prof, dat.header.name)), None
            )
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
        row = conn.execute(
            "SELECT * FROM dat_version WHERE id = ? AND platform = ?", (version_id, platform)
        ).fetchone()
        if row is None:
            raise RegistryError("unknown DAT version")

        def change(library: Library) -> None:
            current = library.dats.get(platform)
            if current and current.pinned and current.sha1 != row["sha1"]:
                raise RegistryError("the active DAT is pinned; unpin it first")
            library.dats[platform] = ActiveDat(
                source=row["source"],
                file=row["file"],
                header_name=row["header_name"],
                version=row["version"],
                sha1=row["sha1"],
                pinned=bool(current and current.pinned),
            )

        self.store.update(change)

    def set_pinned(self, platform: str, pinned: bool) -> None:
        def change(library: Library) -> None:
            if platform not in library.dats:
                raise RegistryError("no active DAT to pin")
            library.dats[platform].pinned = pinned

        self.store.update(change)

    # Reading ---------------------------------------------------------------------

    def versions(self, conn: sqlite3.Connection, platform: str) -> list[sqlite3.Row]:
        return conn.execute(
            "SELECT * FROM dat_version WHERE platform = ? ORDER BY added_at DESC, id DESC",
            (platform,),
        ).fetchall()

    def active_version(self, conn, library: Library, platform: str) -> sqlite3.Row | None:
        active = library.dats.get(platform)
        if active is None:
            return None
        return conn.execute(
            "SELECT * FROM dat_version WHERE platform = ? AND sha1 = ?", (platform, active.sha1)
        ).fetchone()

    def load_active(self, conn, library: Library, platform: str) -> Dat | None:
        row = self.active_version(conn, library, platform)
        if row is None:
            return None
        return parse_dat_bytes((self.settings.paths.data_dir / row["file"]).read_bytes())

    def _profile(self, platform: str) -> PlatformProfile:
        profiles = self.settings.platforms.enabled_profiles()
        if platform not in profiles:
            raise RegistryError(f"{platform!r} is not a supported platform")
        return profiles[platform]
