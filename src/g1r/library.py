"""The library: what the user set up in the UI, kept in <data_dir>/library.yaml.

It holds the platform folders (each with its own ignore list) and the target format chosen
per platform. It is written by the app (atomically, via a temp file and rename) and stays
human-readable; the database only holds data derived from it.
"""

import os
import tempfile
import threading
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from g1r.config import RankingConfig, Settings

LIBRARY_HEADER = (
    "# Written by 1g1r-webui from what you set in the UI. Human-readable on purpose;\n"
    "# edit it only while the app is stopped.\n"
)


class FolderEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    platform: str
    mount: str
    path: str = Field(description="Relative to the mount root, POSIX separators; '' = root")
    # This folder's own ranking; None = the default ranking from the configuration.
    ranking: RankingConfig | None = None
    # Conversion: delete replaced originals instead of moving them to discarded/ (irreversible).
    delete_originals: bool = False
    # Hidden from the sidebar and Home (Settings → Folders shows it again); still a set.
    hidden: bool = False
    # Filename patterns this folder ignores (None = the configured default list), and files
    # ignored by their exact path in the folder (POSIX separators).
    ignored_patterns: list[str] | None = None
    ignored_files: list[str] = Field(default_factory=list)
    # The naming template of the Rename tab (None: the configured default).
    rename_template: str | None = None


class ActiveDat(BaseModel):
    """The DAT a platform matches against, recorded explicitly."""

    model_config = ConfigDict(extra="forbid")

    source: str
    file: str = Field(description="Relative to the data directory")
    header_name: str
    version: str | None = None
    sha1: str
    pinned: bool = False


class PlatformDats(BaseModel):
    """A platform's DATs: the active version of each source, and the order sources and
    online lookups identify files in (None: the configured default)."""

    model_config = ConfigDict(extra="forbid")

    active: dict[str, ActiveDat] = Field(default_factory=dict)
    # The platform's own order; None: the configured default.
    order: list[str] | None = None
    # Entries switched off here (besides those off on every platform): they identify nothing
    # until switched on again.
    off: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _one_active_dat(cls, data):
        """Before the priority list a platform had one active DAT, stored as it."""
        if isinstance(data, dict) and "sha1" in data:
            return {"active": {data["source"]: data}}
        return data


class LookupSwitches(BaseModel):
    """Which online lookups the user switched on; all off until they do."""

    model_config = ConfigDict(extra="forbid")

    hasheous: bool = False

    @model_validator(mode="before")
    @classmethod
    def _no_screenscraper(cls, data):
        """ScreenScraper was a lookup until it was dropped; its old switch is ignored."""
        if isinstance(data, dict):
            data = {k: v for k, v in data.items() if k != "screenscraper"}
        return data


class Library(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lookups: LookupSwitches = Field(default_factory=LookupSwitches)
    platform_targets: dict[str, str] = Field(default_factory=dict)
    dats: dict[str, PlatformDats] = Field(default_factory=dict)
    # Sources switched off on every platform.
    dat_off: list[str] = Field(default_factory=list)
    # How many folder scans run at a time (None: the configured default).
    parallel_scans: int | None = None
    # How many files a conversion run converts at a time (None: the configured default).
    parallel_conversions: int | None = None
    # Rows per page of every table (None: the configured default).
    page_size: int | None = None
    # Threads per igir run (None: igir's own).
    igir_threads: int | None = None
    folders: list[FolderEntry] = Field(default_factory=list)

    def folder(self, label: str) -> FolderEntry | None:
        return next((f for f in self.folders if f.label == label), None)

    @model_validator(mode="before")
    @classmethod
    def _ignored_per_folder(cls, data):
        """The ignored filenames were one list for every folder; each folder that has no list
        of its own starts from it."""
        if not isinstance(data, dict) or "ignored_filenames" not in data:
            return data
        data = dict(data)
        shared = data.pop("ignored_filenames")
        if shared is not None:
            data["folders"] = [
                {**f, "ignored_patterns": list(shared)}
                if isinstance(f, dict) and f.get("ignored_patterns") is None
                else f
                for f in data.get("folders") or []
            ]
        return data

    @model_validator(mode="before")
    @classmethod
    def _global_order_per_platform(cls, data):
        """There was one order for every platform without its own; each such platform keeps
        it, and the entries it switched off, as its own."""
        if not isinstance(data, dict) or "dat_order" not in data:
            return data
        data = dict(data)
        shared = data.pop("dat_order")
        if shared is not None:
            dats = {}
            for platform, entry in (data.get("dats") or {}).items():
                if isinstance(entry, dict) and "sha1" in entry:
                    # The single active DAT stored before the priority list.
                    entry = {"active": {entry["source"]: entry}}
                if isinstance(entry, dict) and entry.get("order") is None:
                    off = sorted({*(entry.get("off") or []), *(data.get("dat_off") or [])})
                    entry = {**entry, "order": list(shared), "off": off}
                dats[platform] = entry
            data["dats"] = dats
        return data


class LibraryError(ValueError):
    """library.yaml is unreadable or invalid."""


class LibraryStore:
    """Loads and saves library.yaml; one lock serialises read-modify-write updates."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.path: Path = settings.paths.library_path
        self._lock = threading.Lock()

    def load(self) -> Library:
        if not self.path.is_file():
            return Library()
        try:
            raw = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
            return Library.model_validate(raw)
        except (yaml.YAMLError, ValueError) as exc:
            raise LibraryError(f"{self.path}: {exc}") from exc

    def save(self, library: Library) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = library.model_dump(mode="json", exclude_none=True)
        text = LIBRARY_HEADER + yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".library-", suffix=".yaml")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def update(self, change) -> Library:
        """Apply change(library) under the lock and save; returns the saved library."""
        with self._lock:
            library = self.load()
            change(library)
            Library.model_validate(library.model_dump())
            self.save(library)
            return library

    # Derived views -------------------------------------------------------------

    def target_for(self, library: Library, platform: str) -> str:
        profile = self.settings.platforms.profiles[platform]
        chosen = library.platform_targets.get(platform)
        return chosen if chosen in profile.targets else profile.default_target

    def ranking_for(self, folder: FolderEntry) -> RankingConfig:
        """The folder's own ranking, else the default with the platform's criteria."""
        if folder.ranking is not None:
            return folder.ranking
        profile = self.settings.platforms.profiles.get(folder.platform)
        if profile is not None and profile.ranking_criteria is not None:
            return self.settings.ranking.model_copy(
                update={"criteria": list(profile.ranking_criteria)}
            )
        return self.settings.ranking

    def parallel_scans(self, library: Library) -> int:
        jobs = self.settings.jobs
        chosen = library.parallel_scans
        return (
            chosen if chosen is not None and chosen <= jobs.max_scan_workers else jobs.scan_workers
        )

    def parallel_conversions(self, library: Library) -> int:
        jobs = self.settings.jobs
        chosen = library.parallel_conversions
        if chosen is not None and chosen <= jobs.max_conversion_workers:
            return chosen
        return jobs.conversion_workers

    def page_size(self, library: Library) -> int:
        ui = self.settings.ui
        chosen = library.page_size
        return chosen if chosen is not None and chosen <= ui.max_page_size else ui.page_size

    def igir_threads(self, library: Library) -> int | None:
        chosen = library.igir_threads
        return chosen if chosen is not None and chosen <= self.settings.igir.max_threads else None

    def rename_template(self, folder: FolderEntry) -> str:
        """The folder's naming template, else the default (also when its platform no longer
        offers the one chosen)."""
        chosen = folder.rename_template
        if chosen is not None and chosen in self.settings.rename_templates(folder.platform):
            return chosen
        return self.settings.rename.default_template

    def ignored_patterns(self, folder: FolderEntry) -> list[str]:
        if folder.ignored_patterns is None:
            return list(self.settings.ignored_filenames)
        return folder.ignored_patterns
