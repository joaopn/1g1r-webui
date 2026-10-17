"""The library: what the user set up in the UI, kept in <data_dir>/library.yaml.

It holds the platform folders, the target format chosen per platform and the ignored
filenames. It is written by the app (atomically, via a temp file and rename) and stays
human-readable; the database only holds data derived from it.
"""

import os
import tempfile
import threading
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

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


class ActiveDat(BaseModel):
    """The DAT a platform matches against, recorded explicitly."""

    model_config = ConfigDict(extra="forbid")

    source: str
    file: str = Field(description="Relative to the data directory")
    header_name: str
    version: str | None = None
    sha1: str
    pinned: bool = False


class LookupSwitches(BaseModel):
    """Which online lookups the user switched on; all off until they do."""

    model_config = ConfigDict(extra="forbid")

    hasheous: bool = False


class Library(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lookups: LookupSwitches = Field(default_factory=LookupSwitches)
    platform_targets: dict[str, str] = Field(default_factory=dict)
    dats: dict[str, ActiveDat] = Field(default_factory=dict)
    ignored_filenames: list[str] | None = None
    folders: list[FolderEntry] = Field(default_factory=list)

    def folder(self, label: str) -> FolderEntry | None:
        return next((f for f in self.folders if f.label == label), None)


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
        return folder.ranking or self.settings.ranking

    def ignored_filenames(self, library: Library) -> list[str]:
        if library.ignored_filenames is None:
            return list(self.settings.ignored_filenames)
        return library.ignored_filenames
