"""Content hashes of a file's ROM data: what an online lookup sends.

The data is the bare file, or each ROM member of a zip; on platforms with copier headers
the header-stripped data is hashed too, since databases list either form. On platforms whose
dumps come in several byte orders (N64), a swapped file is hashed in the native order too.
A CHD stands for its largest data track (decoded by `chd_track_hashes`), never for itself.
"""

import hashlib
import json
import struct
import subprocess
import zipfile
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from g1r.config import ByteOrderConfig, HeaderRule, Settings

FULL = "full"
HEADERLESS = "headerless"
SWAPPED = "native-order"


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


def word_bytes(config: ByteOrderConfig | None, head: bytes) -> int | None:
    """The word length to reverse for the native byte order, or None when the data is in it
    (or in no order the platform knows)."""
    if config is None:
        return None
    for order in config.swapped:
        magic = bytes.fromhex(order.magic_hex)
        if head[config.magic_offset : config.magic_offset + len(magic)] == magic:
            return order.word_bytes
    return None


def magic_length(config: ByteOrderConfig) -> int:
    """How many bytes from the start `word_bytes` needs to see."""
    return config.magic_offset + len(bytes.fromhex(config.native_magic_hex))


def swap_words(data: bytes, word: int) -> bytes:
    """Reverse the bytes of each `word`-long word (its own inverse). The length must be a
    multiple of `word`."""
    out = bytearray(len(data))
    for i in range(word):
        out[i::word] = data[word - 1 - i :: word]
    return bytes(out)


def native_order(config: ByteOrderConfig | None, data: bytes) -> bytes | None:
    """The data in the platform's native byte order, when it is swapped (else None)."""
    word = word_bytes(config, data)
    if word is None or len(data) % word:
        return None
    return swap_words(data, word)


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


# An RVZ (WIA family) starts with header 1: magic, version, compatible version, header 2's
# size and SHA1, the disc's size, the file's size, header 1's SHA1. Header 2 follows: disc
# type, compression, level, chunk size, then the disc's own header (game ID, disc number,
# revision first).
RVZ_TAG = b"RVZ\x01"
RVZ_HEADERS = ">4sIII20sQQ20sIIII6sBB"
RVZ_SUFFIX = ".rvz"


def rvz_identity(path: Path) -> str | None:
    """Which disc an RVZ holds, cheaply (no hashing): its size, game ID, disc and revision.
    Equal identities are only candidates; `payload_sha1` decides."""
    size = struct.calcsize(RVZ_HEADERS)
    try:
        with path.open("rb") as handle:
            header = handle.read(size)
    except OSError:
        return None
    if len(header) < size:
        return None
    tag, *_, disc_size, _, _, _, _, _, _, game_id, disc, revision = struct.unpack(
        RVZ_HEADERS, header
    )
    if tag != RVZ_TAG:
        return None
    return f"{disc_size}:{game_id.hex()}:{disc}:{revision}"


def payload_sha1(
    path: Path,
    rom_extensions: set[str],
    limit: int,
    rvz_sha1: Callable[[Path], str | None] | None = None,
    byte_order: ByteOrderConfig | None = None,
) -> str | None:
    """The SHA1 of the file's ROM data when it holds exactly one payload, else None. A CHD's
    is the disc's own SHA1 from its header, so two compressions of one disc are equal; a
    byte-swapped ROM's is that of its native order, so it equals the unswapped dump's."""
    if path.suffix.lower() == CHD_SUFFIX:
        identity = chd_identity(path)
        return identity[1] if identity else None
    if path.suffix.lower() == RVZ_SUFFIX:
        # The disc's SHA1, which only dolphin-tool can tell (it decompresses the disc).
        return rvz_sha1(path) if rvz_sha1 is not None else None
    found = []
    for data in payloads(path, rom_extensions, limit):
        native = native_order(byte_order, data)
        found.append(
            hashlib.sha1(data if native is None else native, usedforsecurity=False).hexdigest()
        )
        if len(found) > 1:
            return None
    return found[0] if found else None


# Reads a CHD's tracks: {"type": ..., "tracks": [{index, type, size, crc32, md5, sha1}]}.
ChdReader = Callable[[Settings, Path], dict | None]


def chd_track_hashes(settings: Settings, path: Path) -> dict | None:
    """Each track's hashes, from the helper script; None when the CHD cannot be read."""
    config = settings.lookups.chd
    command = [config.node, config.script, config.chdman_module, str(config.chunk_bytes), str(path)]
    try:
        timeout = config.timeout_seconds + path.stat().st_size / config.min_bytes_per_second
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except ValueError:
        return None


def disc_track(settings: Settings, read: dict | None) -> ContentHash | None:
    """The track a disc is looked up by: its largest data track."""
    tracks = [
        t
        for t in (read or {}).get("tracks", [])
        if t["type"] not in settings.lookups.chd.audio_track_types
    ]
    if not tracks:
        return None
    track = max(tracks, key=lambda t: t["size"])
    return ContentHash(FULL, track["size"], track["crc32"], track["md5"], track["sha1"])


def payload_count(hashes: list[ContentHash]) -> int:
    """How many ROM payloads the hashes cover (a payload may also have a headerless hash)."""
    return sum(1 for h in hashes if h.variant.split(":")[0] == FULL)


def content_hashes(
    settings: Settings, platform: str, path: Path, read_chd: ChdReader = chd_track_hashes
) -> list[ContentHash]:
    if path.suffix.lower() == CHD_SUFFIX:
        track = disc_track(settings, read_chd(settings, path))
        return [track] if track is not None else []
    profile = settings.platforms.profiles[platform]
    extensions = {e.lower() for e in profile.rom_extensions}
    rules = settings.headers.get(platform, [])
    byte_order = settings.byte_orders.get(platform)
    found: list[ContentHash] = []
    for index, data in enumerate(payloads(path, extensions, settings.lookups.max_hash_bytes)):
        suffix = f":{index}" if index else ""
        found.append(_hash(FULL + suffix, data))
        for rule in rules:
            size = header_size(rule, data)
            if size is not None:
                found.append(_hash(HEADERLESS + suffix, data[size:]))
                break
        native = native_order(byte_order, data)
        if native is not None:
            found.append(_hash(SWAPPED + suffix, native))
    return found
