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

from g1r.config import PlatformProfile, Settings
from g1r.dats import Dat, DatError, parse_dat_bytes
from g1r.library import ActiveDat, Library, LibraryStore

Fetch = Callable[[str], bytes]
DAT_SUFFIXES = (".dat", ".xml")


class RegistryError(ValueError):
    """A DAT could not be added or activated; the message is shown to the user."""


@dataclass
class PackResult:
    member: str
    platform: str | None
    version_id: int | None
    message: str


def header_matches(profile: PlatformProfile, header_name: str) -> bool:
    """No-Intro names some DATs with a suffix, e.g. 'Nintendo - ... (Headered)'."""
    return header_name == profile.nointro_dat or header_name.startswith(profile.nointro_dat + " (")


class DatRegistry:
    def __init__(self, settings: Settings, store: LibraryStore, fetch: Fetch | None = None):
        self.settings = settings
        self.store = store
        self.fetch = fetch or self._http_fetch

    def _http_fetch(self, url: str) -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": self.settings.dats.user_agent})
        with urllib.request.urlopen(
            request, timeout=self.settings.dats.download_timeout_seconds
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
        profile = self._profile(platform)
        source = self.settings.dats.sources["libretro"]
        url = source.url_template.format(name=urllib.parse.quote(profile.nointro_dat))
        try:
            data = self.fetch(url)
        except OSError as exc:
            raise RegistryError(f"download failed: {exc}") from exc
        return self.add(
            conn,
            platform,
            data,
            source="libretro",
            origin=url,
            original_name=f"{profile.nointro_dat}.dat",
        )

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
        """A DAT-o-MATIC daily pack: each DAT goes to the enabled platform it names."""
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
