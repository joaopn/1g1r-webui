"""The bind mounts folders can be picked from, and safe paths inside them.

Mount "roms" is the main mount (paths.roms_root), which also holds discarded/. Every
directory directly under paths.extra_mounts_root is an additional mount, id "mnt/<name>".
"""

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from g1r.config import Settings
from g1r.library import FolderEntry

MAIN_MOUNT = "roms"
EXTRA_PREFIX = "mnt/"


class FolderPathError(ValueError):
    """A requested folder path is unusable; the message is shown to the user."""


@dataclass(frozen=True)
class Mount:
    id: str
    root: Path

    @property
    def is_main(self) -> bool:
        return self.id == MAIN_MOUNT


def list_mounts(settings: Settings) -> list[Mount]:
    mounts = [Mount(MAIN_MOUNT, settings.paths.roms_root)]
    extra = settings.paths.extra_mounts_root
    if extra.is_dir():
        for entry in sorted(extra.iterdir()):
            if entry.is_dir() and not entry.name.startswith("."):
                mounts.append(Mount(EXTRA_PREFIX + entry.name, entry))
    return mounts


def get_mount(settings: Settings, mount_id: str) -> Mount:
    for mount in list_mounts(settings):
        if mount.id == mount_id:
            return mount
    raise FolderPathError(f"unknown mount {mount_id!r}")


def normalise_relative(path: str) -> str:
    """'a/b/', '/a//b', 'a/./b' -> 'a/b'; refuses '..' and absolute escapes."""
    parts = [p for p in PurePosixPath(path.strip()).parts if p not in ("/", ".")]
    if ".." in parts:
        raise FolderPathError("a folder path may not contain '..'")
    return "/".join(parts)


def resolve(settings: Settings, mount_id: str, relative: str) -> Path:
    """The real path of mount/relative, guaranteed (after symlinks) to stay inside the mount."""
    mount = get_mount(settings, mount_id)
    relative = normalise_relative(relative)
    root = mount.root.resolve()
    target = (root / relative).resolve() if relative else root
    if target != root and root not in target.parents:
        raise FolderPathError("that folder points outside its mount")
    return target


def discarded_root(settings: Settings) -> Path:
    return settings.paths.discarded_root.resolve()


def is_in_discarded(settings: Settings, path: Path) -> bool:
    discarded = discarded_root(settings)
    return path == discarded or discarded in path.parents


def subdirectories(settings: Settings, mount_id: str, relative: str) -> list[str]:
    """Visible child directory names, without discarded/ and hidden directories."""
    base = resolve(settings, mount_id, relative)
    if not base.is_dir():
        raise FolderPathError("that folder does not exist")
    names = []
    for entry in sorted(base.iterdir(), key=lambda e: e.name.lower()):
        if entry.name.startswith(".") or not entry.is_dir():
            continue
        if is_in_discarded(settings, entry.resolve()):
            continue
        names.append(entry.name)
    return names


def check_new_folder(
    settings: Settings, mount_id: str, relative: str, existing: list[FolderEntry]
) -> Path:
    """Validate a folder for Add platform; returns its real path or raises FolderPathError."""
    mount = get_mount(settings, mount_id)
    target = resolve(settings, mount_id, relative)
    if not target.is_dir():
        raise FolderPathError("that folder does not exist")
    if mount.is_main and target == mount.root.resolve():
        raise FolderPathError(
            "pick a platform folder inside the main mount, not the mount itself "
            "(it also holds discarded/)"
        )
    if is_in_discarded(settings, target):
        raise FolderPathError("folders inside discarded/ cannot be added")
    for folder in existing:
        try:
            other = resolve(settings, folder.mount, folder.path)
        except FolderPathError:
            continue  # its mount is gone; it cannot overlap anything reachable
        if other == target:
            raise FolderPathError(f"that folder is already added as {folder.label!r}")
        if other in target.parents or target in other.parents:
            raise FolderPathError(f"folders may not be nested: it overlaps {folder.label!r}")
    return target
