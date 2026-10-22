"""Card image headers the scan reads: Nintendo 3DS NCSD (.3ds/.cci).

From the header alone (no keys): whether the game partition is encrypted (emulators need a
decrypted image) and with a seed, its product code and program ID, and the card's full
size, which tells a trimmed image (its padding cut off). A trimmed image matches the DAT
once padded back, without writing anything.

`prove_decrypted` checks a decrypted image against the SHA-256s its partitions carry: the
proof of a decryption, which needs no DAT.
"""

import hashlib
import struct
import zipfile
import zlib
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from g1r.config import NcchProofConfig, NcsdConfig

ENCRYPTED = "encrypted"
TRIMMED = "trimmed"
U32 = "<I"
U64 = "<Q"
U8 = "<B"
# A member of an archive other than a zip, streamed: (archive, member).
MemberOpener = Callable[[Path, str], AbstractContextManager[BinaryIO]]


@dataclass(frozen=True)
class CardInfo:
    image_size: int
    data_size: int
    encrypted: bool
    product_code: str = ""
    # Encrypted with a seed (found in seeddb by program ID, hex).
    seed: bool = False
    program_id: str = ""

    @property
    def trimmed(self) -> bool:
        return self.data_size < self.image_size

    def notes(self) -> list[str]:
        return [n for n, on in ((ENCRYPTED, self.encrypted), (TRIMMED, self.trimmed)) if on]


ZIP_SUFFIX = ".zip"


@contextmanager
def open_payload(
    path: Path, member: str | None, open_member: MemberOpener | None = None
) -> Iterator[BinaryIO]:
    """The ROM's bytes as a stream: the file, one member of a zip, or one member of another
    archive through `open_member` (7z)."""
    if member is None:
        with path.open("rb") as handle:
            yield handle
    elif path.suffix.lower() == ZIP_SUFFIX:
        with zipfile.ZipFile(path) as archive, archive.open(member) as handle:
            yield handle  # type: ignore[misc]
    elif open_member is not None:
        with open_member(path, member) as handle:
            yield handle
    else:
        raise OSError(f"no reader for the members of {path.name}")


def _u(fmt: str, data: bytes, offset: int) -> int | None:
    end = offset + struct.calcsize(fmt)
    return struct.unpack(fmt, data[offset:end])[0] if len(data) >= end else None


def _read(stream: BinaryIO, count: int) -> bytes:
    """Up to `count` bytes (a pipe may return fewer per read)."""
    parts, left = [], count
    while left > 0 and (part := stream.read(left)):
        parts.append(part)
        left -= len(part)
    return b"".join(parts)


def read_ncsd(
    config: NcsdConfig,
    path: Path,
    member: str | None,
    size: int,
    open_member: MemberOpener | None = None,
) -> CardInfo | None:
    """The card's facts, or None when this is not an NCSD image."""
    header_end = config.flags_offset + config.media_unit_flag + struct.calcsize(U8)
    try:
        with open_payload(path, member, open_member) as stream:
            header = _read(stream, header_end)
            magic = config.magic.encode()
            start = config.magic_offset
            if header[start : start + len(magic)] != magic:
                return None
            exponent = _u(U8, header, config.flags_offset + config.media_unit_flag)
            units = _u(U32, header, config.image_size_offset)
            first = _u(U32, header, config.partition_table_offset)
            if exponent is None or units is None or first is None:
                return None
            unit = config.media_unit_bytes << exponent
            ncch_end = max(
                config.ncch_flags_offset + config.crypto_flag + struct.calcsize(U8),
                config.product_code_offset + config.product_code_bytes,
                config.program_id_offset + config.program_id_bytes,
            )
            # Streams (archive members) only read forward: skip to the partition.
            _read(stream, max(first * unit - len(header), 0))
            ncch = _read(stream, ncch_end)
    except (OSError, zipfile.BadZipFile, KeyError):
        return None
    ncch_magic = config.ncch_magic.encode()
    at = config.ncch_magic_offset
    flags = _u(U8, ncch, config.ncch_flags_offset + config.crypto_flag)
    encrypted = (
        ncch[at : at + len(ncch_magic)] == ncch_magic
        and flags is not None
        and not flags & config.no_crypto_mask
    )
    code = ncch[config.product_code_offset : config.product_code_offset + config.product_code_bytes]
    product = code.split(b"\0")[0].decode("ascii", errors="replace").strip()
    seed = encrypted and flags is not None and bool(flags & config.seed_mask)
    raw = ncch[config.program_id_offset : config.program_id_offset + config.program_id_bytes]
    # Little-endian in the header; written as people read it ("00040000001b5000").
    program_id = raw[::-1].hex() if len(raw) == config.program_id_bytes and any(raw) else ""
    return CardInfo(units * unit, size, encrypted, product, seed, program_id)


def padded_crc(
    config: NcsdConfig, path: Path, member: str | None, image_size: int, chunk: int
) -> str:
    """CRC32 of the image padded back to its full size, as the DAT lists it."""
    crc, read = 0, 0
    with open_payload(path, member) as stream:
        while block := stream.read(chunk):
            crc = zlib.crc32(block, crc)
            read += len(block)
    padding = bytes.fromhex(config.padding_hex) * chunk
    while read < image_size:
        step = min(chunk, image_size - read)
        crc = zlib.crc32(padding[:step], crc)
        read += step
    return format(crc, "08x")


# Proof of a decryption -------------------------------------------------------------


class ProofError(Exception):
    """The image does not match its own hashes; the message names the first that failed.
    `damaged` is set when that region's own key had already been proven by an earlier hash
    (a RomFS block after its header): the decryption was right and the data itself is bad.
    `offset` is where the failed region starts in the image."""

    def __init__(self, message: str, offset: int = 0, damaged: bool = False):
        super().__init__(message)
        self.offset = offset
        self.damaged = damaged


def is_blank(header: bytes) -> bool:
    """A partition the dump left empty: its header is one byte value throughout (some
    releases blank the update partition but keep its entry in the partition table)."""
    return len(set(header)) == 1


def _sha256(
    handle: BinaryIO, offset: int, size: int, chunk: int, tick: Callable[[], None], pad_to: int
) -> bytes:
    """SHA-256 of `size` bytes at `offset`, zero-padded to `pad_to` bytes."""
    digest = hashlib.sha256()
    handle.seek(offset)
    left = size
    while left > 0:
        tick()
        block = handle.read(min(chunk, left))
        if not block:
            raise ProofError(f"the image ends inside a hashed region (at {offset + size - left})")
        digest.update(block)
        left -= len(block)
    if pad_to > size:
        digest.update(bytes(pad_to - size))
    return digest.digest()


def trailing_fill(stream: BinaryIO, chunk: int, tick: Callable[[], None]) -> tuple[int, int]:
    """Where the run of one byte value that ends the stream starts, and that value. An image
    copied or downloaded only in part and filled up to its size ends in a run that reaches
    back into the data; on a whole card the run is only the padding after the partitions."""
    position = start = 0
    value = -1
    while block := stream.read(chunk):
        tick()
        last = block[-1]
        kept = len(block.rstrip(bytes([last])))
        if kept or last != value:
            start, value = position + kept, last
        position += len(block)
    return start, value


def _align(value: int, block: int) -> int:
    return -(-value // block) * block


class _Proof:
    def __init__(self, config: NcsdConfig, handle: BinaryIO, tick: Callable[[], None]):
        self.config = config
        self.p: NcchProofConfig = config.proof
        self.handle = handle
        self.tick = tick
        self.checked = 0

    def same(
        self,
        what: str,
        offset: int,
        size: int,
        want: bytes,
        pad_to: int = 0,
        damaged: bool = False,
    ) -> None:
        got = _sha256(self.handle, offset, size, self.p.read_chunk_bytes, self.tick, pad_to)
        if got != want:
            raise ProofError(f"{what} does not match its hash", offset, damaged)
        self.checked += 1

    def read(self, offset: int, size: int) -> bytes:
        self.handle.seek(offset)
        data = self.handle.read(size)
        if len(data) != size:
            raise ProofError(f"the image ends at {offset + len(data)}, inside a header")
        return data

    def region(self, header: bytes, field: int, unit: int) -> tuple[int, int]:
        """A region's (offset, size) in bytes, from its pair of u32 media-unit counts."""
        start = _u(U32, header, field) or 0
        size = _u(U32, header, field + struct.calcsize(U32)) or 0
        return start * unit, size * unit

    def ncch(self, base: int, name: str) -> None:
        c, p = self.config, self.p
        header = self.read(base, p.ncch_header_bytes)
        magic = c.ncch_magic.encode()
        if header[c.ncch_magic_offset : c.ncch_magic_offset + len(magic)] != magic:
            raise ProofError(f"{name} is not an NCCH partition")
        unit = c.media_unit_bytes << header[c.ncch_flags_offset + c.media_unit_flag]
        before = self.checked

        def stored(offset: int) -> bytes:
            return header[offset : offset + p.hash_bytes]

        if _u(U32, header, p.exheader_size_offset):
            self.same(
                f"{name}'s extended header",
                base + p.ncch_header_bytes,
                p.exheader_hashed_bytes,
                stored(p.exheader_hash_offset),
            )
        logo, logo_size = self.region(header, p.logo_region_offset, unit)
        if logo_size:
            self.same(f"{name}'s logo", base + logo, logo_size, stored(p.logo_hash_offset))
        exefs, exefs_size = self.region(header, p.exefs_region_offset, unit)
        if exefs_size:
            hashed = (_u(U32, header, p.exefs_hash_region_offset) or 0) * unit
            self.same(f"{name}'s ExeFS header", base + exefs, hashed, stored(p.exefs_hash_offset))
            self.exefs(base + exefs, name)
        romfs, romfs_size = self.region(header, p.romfs_region_offset, unit)
        if romfs_size:
            hashed = (_u(U32, header, p.romfs_hash_region_offset) or 0) * unit
            self.same(f"{name}'s RomFS header", base + romfs, hashed, stored(p.romfs_hash_offset))
            self.romfs(base + romfs, name)
        if self.checked == before:
            raise ProofError(f"{name} has nothing its hashes cover")

    def exefs(self, base: int, name: str) -> None:
        p = self.p
        header = self.read(base, p.exefs_header_bytes)
        for i in range(p.exefs_files):
            entry = header[i * p.exefs_entry_bytes : (i + 1) * p.exefs_entry_bytes]
            file_name = entry[: p.exefs_name_bytes].rstrip(b"\0").decode("ascii", "replace")
            if not file_name:
                continue
            offset = _u(U32, entry, p.exefs_name_bytes) or 0
            size = _u(U32, entry, p.exefs_name_bytes + struct.calcsize(U32)) or 0
            end = p.exefs_header_bytes - p.hash_bytes * i
            self.same(
                f"{name}'s ExeFS file {file_name}",
                base + p.exefs_header_bytes + offset,
                size,
                header[end - p.hash_bytes : end],
            )

    def romfs(self, base: int, name: str) -> None:
        p = self.p
        header = self.read(base, p.ivfc_header_bytes)
        if header[: len(p.ivfc_magic)] != p.ivfc_magic.encode():
            raise ProofError(f"{name}'s RomFS has no hash tree")
        master = _u(U32, header, p.ivfc_master_size_offset) or 0
        levels = []
        for i in range(p.ivfc_levels):
            at = p.ivfc_levels_offset + i * p.ivfc_level_bytes
            size = _u(U64, header, at + p.ivfc_level_size_offset) or 0
            block = 1 << (_u(U32, header, at + p.ivfc_level_block_offset) or 0)
            levels.append((size, block))
        # In the file: the last level (the data) first, then the others in order.
        offsets = [0] * len(levels)
        data_size, data_block = levels[-1]
        offsets[-1] = _align(p.ivfc_header_bytes + master, data_block)
        end, block = offsets[-1] + data_size, data_block
        for i, (size, own_block) in enumerate(levels[:-1]):
            offsets[i] = _align(end, block)
            end, block = offsets[i] + size, own_block
        parent = self.read(base + p.ivfc_header_bytes, master)
        for i, (size, block) in enumerate(levels):
            for n in range(-(-size // block)):
                start = n * block
                self.same(
                    f"{name}'s RomFS (level {i + 1}, block {n})",
                    base + offsets[i] + start,
                    min(block, size - start),
                    parent[n * p.hash_bytes : (n + 1) * p.hash_bytes],
                    pad_to=block,
                    damaged=True,
                )
            parent = self.read(base + offsets[i], size)


def prove_decrypted(config: NcsdConfig, path: Path, tick: Callable[[], None]) -> int:
    """Check every NCCH partition of a decrypted card image against its own SHA-256s; return
    how many hashes matched. Raises ProofError at the first that does not (`tick` is called
    between reads, so a stop can cut it short). A blank partition other than the first (the
    game) holds nothing to prove: the decryption copied it as it was."""
    with path.open("rb") as handle:
        proof = _Proof(config, handle, tick)
        header = proof.read(0, config.flags_offset + config.media_unit_flag + struct.calcsize(U8))
        magic = config.magic.encode()
        if header[config.magic_offset : config.magic_offset + len(magic)] != magic:
            raise ProofError("not a 3DS card image")
        unit = config.media_unit_bytes << header[config.flags_offset + config.media_unit_flag]
        partitions = 0
        for i in range(config.partition_count):
            field = config.partition_table_offset + i * config.partition_entry_bytes
            offset, size = proof.region(header, field, unit)
            if i and size and is_blank(proof.read(offset, config.proof.ncch_header_bytes)):
                continue
            if size:
                proof.ncch(offset, f"partition {i}")
                partitions += 1
        if not partitions:
            raise ProofError("the card has no partitions")
        return proof.checked
