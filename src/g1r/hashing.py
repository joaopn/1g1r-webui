"""Content hashes of a file's ROM data: what an online lookup sends.

The data is the bare file, or each ROM member of a zip; on platforms with copier headers
the header-stripped data is hashed too, since databases list either form. On platforms whose
dumps come in several byte orders (N64), a swapped file is hashed in the native order too.
Files are read in chunks, never whole, so their size does not matter.
A CHD stands for its largest data track (decoded by `chd_track_hashes`), never for itself;
an RVZ for its disc (decoded by `rvz_disc_hash`).
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
from typing import BinaryIO

from g1r import discs
from g1r.config import ByteOrderConfig, HeaderRule, Settings

FULL = "full"
HEADERLESS = "headerless"
SWAPPED = "native-order"


def header_size(rule: HeaderRule, head: bytes, size: int) -> int | None:
    """The copier header's length, from the data's first bytes and its total size."""
    if rule.magic_hex is not None:
        magic = bytes.fromhex(rule.magic_hex)
        end = rule.magic_offset + len(magic)
        if head[rule.magic_offset : end] == magic and size > rule.header_size:
            return rule.header_size
        return None
    if size % rule.size_modulus == rule.header_size:
        return rule.header_size
    return None


def _head_length(rule: HeaderRule) -> int:
    """How many bytes from the start `header_size` needs to see."""
    if rule.magic_hex is None:
        return 0
    return rule.magic_offset + len(bytes.fromhex(rule.magic_hex))


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


class Digest:
    """CRC32 and size of a byte stream fed in pieces, plus the named stronger hashes."""

    def __init__(self, strong: tuple[str, ...]):
        self.crc, self.size = 0, 0
        self.strong = {name: hashlib.new(name, usedforsecurity=False) for name in strong}

    def update(self, data: bytes) -> None:
        self.crc = zlib.crc32(data, self.crc)
        self.size += len(data)
        for digest in self.strong.values():
            digest.update(data)

    @property
    def crc32(self) -> str:
        return format(self.crc, "08x")

    def hexdigest(self, name: str) -> str:
        return self.strong[name].hexdigest()


@dataclass
class Payload:
    """One ROM's digests: as it is, without each copier header a rule recognises, and in
    the native byte order when it is swapped."""

    full: Digest
    headerless: list[Digest]
    native: Digest | None


def _digest(
    stream: BinaryIO,
    size: int,
    chunk: int,
    rules: list[HeaderRule],
    byte_order: ByteOrderConfig | None,
    strong: tuple[str, ...],
) -> Payload:
    """Read the stream once, `chunk` bytes at a time, feeding every variant's digest."""
    need = max([_head_length(r) for r in rules], default=0)
    if byte_order is not None:
        need = max(need, magic_length(byte_order))
    block = stream.read(max(chunk, need))
    full = Digest(strong)
    skips = [s for r in rules if (s := header_size(r, block, size)) is not None]
    headerless = [Digest(strong) for _ in skips]
    word = word_bytes(byte_order, block)
    native = Digest(strong) if word is not None and not size % word else None
    at, rest = 0, b""
    while block:
        full.update(block)
        for skip, digest in zip(skips, headerless, strict=True):
            if at + len(block) > skip:
                digest.update(block[max(skip - at, 0) :])
        if native is not None and word is not None:
            data = rest + block
            whole = len(data) - len(data) % word
            native.update(swap_words(data[:whole], word))
            rest = data[whole:]
        at += len(block)
        block = stream.read(chunk)
    return Payload(full, headerless, None if rest else native)


def payloads(
    settings: Settings,
    path: Path,
    rom_extensions: set[str],
    rules: list[HeaderRule] | None = None,
    byte_order: ByteOrderConfig | None = None,
    strong: tuple[str, ...] = (),
) -> list[Payload]:
    """The digests of the ROM data inside a file: the file itself, or each ROM member of a
    zip. Read in chunks, so a file of any size takes the same memory."""
    chunk = settings.hashing.chunk_bytes

    def read(stream: BinaryIO, size: int) -> Payload:
        return _digest(stream, size, chunk, rules or [], byte_order, strong)

    if path.suffix.lower() != ".zip":
        with path.open("rb") as stream:
            return [read(stream, path.stat().st_size)]
    found = []
    try:
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                ext = PurePosixPath(info.filename).suffix.lower().lstrip(".")
                if ext in rom_extensions:
                    with archive.open(info) as stream:
                        found.append(read(stream, info.file_size))
    except zipfile.BadZipFile:
        return []
    return found


def rom_members(path: Path, rom_extensions: set[str]) -> int:
    """How many ROM payloads `payloads` would read from the file (0 for a bad zip)."""
    if path.suffix.lower() != ".zip":
        return 1
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
    except zipfile.BadZipFile:
        return 0
    return sum(1 for n in names if PurePosixPath(n).suffix.lower().lstrip(".") in rom_extensions)


@dataclass(frozen=True)
class ContentHash:
    variant: str
    size: int
    crc32: str
    # Empty when not computed (an RVZ's disc: Hasheous answers to CRC32 and SHA1).
    md5: str
    sha1: str


MD5 = "md5"
SHA1 = "sha1"


def _hash(variant: str, digest: Digest) -> ContentHash:
    return ContentHash(
        variant, digest.size, digest.crc32, digest.hexdigest(MD5), digest.hexdigest(SHA1)
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


def _rvz_header(path: Path) -> tuple | None:
    size = struct.calcsize(RVZ_HEADERS)
    try:
        with path.open("rb") as handle:
            header = handle.read(size)
    except OSError:
        return None
    if len(header) < size:
        return None
    fields = struct.unpack(RVZ_HEADERS, header)
    return fields if fields[0] == RVZ_TAG else None


def rvz_identity(path: Path) -> str | None:
    """Which disc an RVZ holds, cheaply (no hashing): its size, game ID, disc and revision.
    Equal identities are only candidates; `payload_sha1` decides."""
    header = _rvz_header(path)
    if header is None:
        return None
    _, *_, disc_size, _, _, _, _, _, _, game_id, disc, revision = header
    return f"{disc_size}:{game_id.hex()}:{disc}:{revision}"


def payload_sha1(
    settings: Settings,
    path: Path,
    rom_extensions: set[str],
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
    if rom_members(path, rom_extensions) != 1:
        return None
    found = payloads(settings, path, rom_extensions, byte_order=byte_order, strong=(SHA1,))
    if len(found) != 1:
        return None
    native = found[0].native
    return (found[0].full if native is None else native).hexdigest(SHA1)


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


# Reads the disc an RVZ holds: its hashes, or None when the disc cannot be read.
RvzReader = Callable[[Settings, Path], ContentHash | None]


def rvz_disc_hash(settings: Settings, path: Path) -> ContentHash | None:
    """The disc's CRC32 and SHA1, decoded by dolphin-tool (no size cap, nothing on disk)."""
    header = _rvz_header(path)
    if header is None:
        return None
    dolphin = settings.dolphin
    try:
        found = discs.rvz_digests(dolphin, settings.paths.data_dir / dolphin.user_dir, path)
    except discs.DiscError:
        return None
    _, *_, disc_size, _, _, _, _, _, _, _, _, _ = header
    return ContentHash(FULL, disc_size, found[discs.CRC32], "", found[discs.SHA1])


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
    settings: Settings,
    platform: str,
    path: Path,
    read_chd: ChdReader = chd_track_hashes,
    read_rvz: RvzReader = rvz_disc_hash,
) -> list[ContentHash]:
    if path.suffix.lower() == CHD_SUFFIX:
        track = disc_track(settings, read_chd(settings, path))
        return [track] if track is not None else []
    if path.suffix.lower() == RVZ_SUFFIX:
        disc = read_rvz(settings, path)
        return [disc] if disc is not None else []
    profile = settings.platforms.profiles[platform]
    # An RVZ inside an archive cannot be decoded where it is; its bytes are a container's.
    extensions = {e.lower() for e in profile.rom_extensions} - {RVZ_SUFFIX.lstrip(".")}
    rules = settings.headers.get(platform, [])
    byte_order = settings.byte_orders.get(platform)
    found: list[ContentHash] = []
    read = payloads(settings, path, extensions, rules, byte_order, (MD5, SHA1))
    for index, payload in enumerate(read):
        suffix = f":{index}" if index else ""
        found.append(_hash(FULL + suffix, payload.full))
        if payload.headerless:
            found.append(_hash(HEADERLESS + suffix, payload.headerless[0]))
        if payload.native is not None:
            found.append(_hash(SWAPPED + suffix, payload.native))
    return found
