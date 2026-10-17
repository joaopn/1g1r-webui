"""Content hashes of a file's ROM data: what an online lookup sends.

The data is the bare file, or each ROM member of a zip; on platforms with copier headers
the header-stripped data is hashed too, since databases list either form.
"""

import hashlib
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from g1r.config import HeaderRule, Settings

FULL = "full"
HEADERLESS = "headerless"


def header_size(rule: HeaderRule, data: bytes) -> int | None:
    if rule.magic_hex is not None:
        magic = bytes.fromhex(rule.magic_hex)
        end = rule.magic_offset + len(magic)
        if data[rule.magic_offset : end] == magic and len(data) > rule.header_size:
            return rule.header_size
        return None
    if len(data) % rule.size_modulus == rule.header_size:
        return rule.header_size
    return None


def payloads(path: Path, rom_extensions: set[str], limit: int):
    """The ROM data inside a file: the file itself, or each ROM member of a zip."""
    if path.suffix.lower() == ".zip":
        try:
            with zipfile.ZipFile(path) as archive:
                for info in archive.infolist():
                    ext = PurePosixPath(info.filename).suffix.lower().lstrip(".")
                    if ext in rom_extensions and info.file_size <= limit:
                        yield archive.read(info)
        except zipfile.BadZipFile:
            return
    elif path.stat().st_size <= limit:
        yield path.read_bytes()


@dataclass(frozen=True)
class ContentHash:
    variant: str
    size: int
    crc32: str
    md5: str
    sha1: str


def _hash(variant: str, data: bytes) -> ContentHash:
    return ContentHash(
        variant,
        len(data),
        format(zlib.crc32(data), "08x"),
        hashlib.md5(data, usedforsecurity=False).hexdigest(),
        hashlib.sha1(data, usedforsecurity=False).hexdigest(),
    )


def payload_count(hashes: list[ContentHash]) -> int:
    """How many ROM payloads the hashes cover (a payload may also have a headerless hash)."""
    return sum(1 for h in hashes if h.variant.split(":")[0] == FULL)


def content_hashes(settings: Settings, platform: str, path: Path) -> list[ContentHash]:
    profile = settings.platforms.profiles[platform]
    extensions = {e.lower() for e in profile.rom_extensions}
    rules = settings.headers.get(platform, [])
    found: list[ContentHash] = []
    for index, data in enumerate(payloads(path, extensions, settings.lookups.max_hash_bytes)):
        suffix = f":{index}" if index else ""
        found.append(_hash(FULL + suffix, data))
        for rule in rules:
            size = header_size(rule, data)
            if size is not None:
                found.append(_hash(HEADERLESS + suffix, data[size:]))
                break
    return found
