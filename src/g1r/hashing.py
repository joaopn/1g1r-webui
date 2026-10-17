"""Content hashes of a file's ROM data: what an online lookup sends.

The data is the bare file, or each ROM member of a zip; on platforms with copier headers
the header-stripped data is hashed too, since databases list either form.
"""

import hashlib
import struct
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


# A CHD (v5) header, big-endian: tag, header length, version, the four compressors, logical
# size, map and metadata offsets, hunk and unit sizes, then the raw data SHA1, the SHA1 of
# data and metadata together (what chdman info calls "SHA1"), and the parent's SHA1.
CHD_TAG = b"MComprHD"
CHD_SUFFIX = ".chd"
CHD_V5 = ">8sII16sQQQII20s20s20s"


def chd_identity(path: Path) -> tuple[int, str] | None:
    """A CHD's disc, whatever its compression: (logical size, SHA1 of data and metadata)."""
    size = struct.calcsize(CHD_V5)
    try:
        with path.open("rb") as handle:
            header = handle.read(size)
    except OSError:
        return None
    if len(header) < size:
        return None
    tag, length, _, _, logical, *_, sha1, _ = struct.unpack(CHD_V5, header)
    if tag != CHD_TAG or length != size:
        return None
    return logical, sha1.hex()


def payload_sha1(path: Path, rom_extensions: set[str], limit: int) -> str | None:
    """The SHA1 of the file's ROM data when it holds exactly one payload, else None. A CHD's
    is the disc's own SHA1 from its header, so two compressions of one disc are equal."""
    if path.suffix.lower() == CHD_SUFFIX:
        identity = chd_identity(path)
        return identity[1] if identity else None
    found = []
    for data in payloads(path, rom_extensions, limit):
        found.append(hashlib.sha1(data, usedforsecurity=False).hexdigest())
        if len(found) > 1:
            return None
    return found[0] if found else None


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
