"""Listing what an archive holds: member names, sizes and CRC32s.

Zip archives are read with Python's zipfile; 7z archives are listed by 7-Zip
(`7z l -slt`), whose technical listing is one `Key = value` block per member.
"""

import subprocess
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

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


def parse_slt(listing: str) -> list[Member]:
    _, found, body = listing.partition(f"\n{SLT_SEPARATOR}\n")
    if not found:
        raise ArchiveError("7-Zip listed no members")
    members = []
    for block in body.split("\n\n"):
        fields = dict(line.split(" = ", 1) for line in block.strip().splitlines() if " = " in line)
        if "Path" not in fields or fields.get("Folder") == "+":
            continue
        crc = fields.get("CRC") or None
        members.append(Member(fields["Path"], int(fields.get("Size") or 0), crc and crc.lower()))
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
            raise ArchiveError(f"not a readable zip: {exc}") from exc
    return parse_slt(seven_zip(settings, path))
