"""Listing what an archive holds: member names, sizes and CRC32s.

Zip archives are read with Python's zipfile; 7z archives are listed by 7-Zip
(`7z l -slt`), whose technical listing is one `Key = value` block per member. A 7z
member's first bytes (a card header) are streamed from `7z e -so`.
"""

import subprocess
import threading
import zipfile
import zlib
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from g1r.config import Settings


class ArchiveError(RuntimeError):
    """The archive could not be listed; the message says why."""


@dataclass(frozen=True)
class Member:
    name: str
    size: int
    crc32: str | None


SevenZipRunner = Callable[[Settings, Path], str]

# 7-Zip's technical listing: the archive's own block, then this line, then one block per
# member, blocks separated by blank lines.
SLT_SEPARATOR = "----------"


def run_seven_zip(settings: Settings, path: Path) -> str:
    try:
        result = subprocess.run(
            [settings.archives.seven_zip_binary, "l", "-slt", "--", str(path)],
            capture_output=True,
            text=True,
            timeout=settings.archives.list_timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ArchiveError(f"7-Zip could not run: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        raise ArchiveError(detail[-1] if detail else f"7-Zip exited with {result.returncode}")
    return result.stdout


# Streams one member of a 7z archive, read forward only: (settings, archive, member).
MemberOpener = Callable[[Settings, Path, str], AbstractContextManager[BinaryIO]]


@contextmanager
def open_seven_zip_member(settings: Settings, path: Path, member: str) -> Iterator[BinaryIO]:
    """The member's bytes as 7-Zip extracts them; 7-Zip is stopped once the reader is done
    (only the start is read), or after archives.list_timeout_seconds."""
    command = [settings.archives.seven_zip_binary, "e", "-so", "-spd", "--", str(path), member]
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError as exc:
        raise ArchiveError(f"7-Zip could not run: {exc}") from exc
    timer = threading.Timer(settings.archives.list_timeout_seconds, process.kill)
    timer.start()
    try:
        yield process.stdout  # type: ignore[misc]
    finally:
        timer.cancel()
        process.kill()
        process.wait()


# A folder's Windows attribute letter. Zips also get `Folder = +`; a .7z marks a folder only
# by its attributes ("D drwxr-xr-x"), the Unix mode after them being lowercase.
FOLDER_ATTRIBUTE = "D"
# An empty file in a .7z is listed with no CRC: that of no bytes.
EMPTY_CRC32 = format(zlib.crc32(b""), "08x")


def _is_folder(fields: dict[str, str]) -> bool:
    attributes = fields.get("Attributes", "").split()
    return fields.get("Folder") == "+" or (bool(attributes) and FOLDER_ATTRIBUTE in attributes[0])


def parse_slt(listing: str) -> list[Member]:
    _, found, body = listing.partition(f"\n{SLT_SEPARATOR}\n")
    if not found:
        raise ArchiveError("7-Zip listed no members")
    members = []
    for block in body.split("\n\n"):
        fields = dict(line.split(" = ", 1) for line in block.strip().splitlines() if " = " in line)
        if "Path" not in fields or _is_folder(fields):
            continue
        size = int(fields.get("Size") or 0)
        crc = fields.get("CRC") or (EMPTY_CRC32 if not size else None)
        members.append(Member(fields["Path"], size, crc and crc.lower()))
    return members


def list_members(
    settings: Settings, path: Path, seven_zip: SevenZipRunner = run_seven_zip
) -> list[Member]:
    extension = path.suffix.lower().lstrip(".")
    if extension == "zip":
        try:
            with zipfile.ZipFile(path) as archive:
                return [
                    Member(info.filename, info.file_size, format(info.CRC, "08x"))
                    for info in archive.infolist()
                    if not info.is_dir()
                ]
        except (zipfile.BadZipFile, OSError) as exc:
            raise ArchiveError(f"unreadable zip: {exc}") from exc
    return parse_slt(seven_zip(settings, path))
