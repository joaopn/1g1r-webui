"""Switch NSZ packages converted to NSP (NCZ members back to NCAs), every content archive
(NCA) written byte for byte as the console has it.

An NCZ is an NCA decrypted and compressed with zstd (nsz's format, see `switch_package` in
defaults.yaml); its header lists the key and counter of each section, so decompressing needs
no keys. The output proves itself: each NCA is named after its content ID, the first half of
its SHA-256, and the written NSP is read back to check every one (other members, such as a
ticket, must read back as they were in the source). A package holding more than one title (a
game and an update) is not converted, so one NSP stays one title.
"""

import bisect
import hashlib
import struct
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO

import zstandard
from Cryptodome.Cipher import AES

from g1r import titles
from g1r.config import Settings, SwitchPackageConfig

NSP = "nsp"
NSZ = "nsz"


class PackageError(Exception):
    """The package cannot be converted; the message says why."""


@dataclass(frozen=True)
class Member:
    name: str  # in the NSP
    offset: int  # in the source file
    size: int  # in the source file
    out_size: int
    ncz: bool


@dataclass(frozen=True)
class _Section:
    offset: int
    size: int
    crypto: int
    key: bytes
    counter: bytes


def _source_members(handle: BinaryIO, settings: Settings):
    handle.seek(0)
    found = titles.pfs0_members(handle, settings.title_ids)
    if found is None:
        raise PackageError("not an NSP/NSZ (no PFS0)")
    start, members = found
    return [(name, start + offset, size) for name, offset, size in members]


def _ncz_sections(
    handle: BinaryIO, offset: int, size: int, config: SwitchPackageConfig
) -> list[_Section]:
    """The NCZ's section table, by offset. An update's patch archive has one section per
    patch subsection, often thousands, so the count is bounded only by the member's size."""
    handle.seek(offset + config.ncz_header_bytes)
    if handle.read(len(config.section_magic)) != config.section_magic.encode():
        raise PackageError("an NCZ without its section header")
    (count,) = struct.unpack(config.count, handle.read(struct.calcsize(config.count)))
    entry = struct.calcsize(config.section)
    room = (
        size - config.ncz_header_bytes - len(config.section_magic) - struct.calcsize(config.count)
    )
    if count * entry > room:
        raise PackageError("an NCZ with more sections than it has room for")
    sections = [_Section(*struct.unpack(config.section, handle.read(entry))) for _ in range(count)]
    return sorted(sections, key=lambda s: s.offset)


def plan(path: Path, settings: Settings) -> list[Member]:
    """The NSP's members, read from the source package."""
    config = settings.switch_package
    try:
        with path.open("rb") as handle:
            result = []
            for name, offset, size in _source_members(handle, settings):
                if name.lower().endswith(config.ncz_suffix):
                    sections = _ncz_sections(handle, offset, size, config)
                    out = max([config.ncz_header_bytes, *(s.offset + s.size for s in sections)])
                    stem = name[: -len(config.ncz_suffix)]
                    result.append(Member(stem + config.nca_suffix, offset, size, out, True))
                else:
                    result.append(Member(name, offset, size, size, False))
    except (OSError, struct.error) as exc:
        raise PackageError(f"the package could not be read: {exc}") from exc
    titles_in = sum(1 for m in result if m.name.lower().endswith(config.cnmt_suffix))
    if titles_in > 1:
        raise PackageError(
            f"it holds {titles_in} titles (a game with its update or DLC): one NSP holds one"
            " title, so it is not converted"
        )
    if not any(m.name.lower().endswith(config.nca_suffix) for m in result):
        raise PackageError("no content archive (NCA) inside")
    return result


class _Bounded:
    """A file read up to an end offset (a zstd stream ends at its member's end)."""

    def __init__(self, handle: BinaryIO, end: int):
        self.handle, self.end = handle, end

    def read(self, size: int = -1) -> bytes:
        left = self.end - self.handle.tell()
        if left <= 0:
            return b""
        return self.handle.read(left if size < 0 else min(size, left))


def _decompressed(handle: BinaryIO, member: Member, config: SwitchPackageConfig) -> Iterator[bytes]:
    """An NCZ's NCA data after its own first bytes, decompressed (blocks or one stream)."""
    end = member.offset + member.size
    mark = handle.tell()
    if handle.read(len(config.block_magic)) == config.block_magic.encode():
        head = struct.calcsize(config.block_header)
        _, _, _, exponent, blocks, _ = struct.unpack(config.block_header, handle.read(head))
        size = struct.calcsize(config.block_size)
        sizes = [struct.unpack(config.block_size, handle.read(size))[0] for _ in range(blocks)]
        block = 1 << exponent
        for compressed in sizes:
            data = handle.read(compressed)
            if compressed < block:
                data = zstandard.ZstdDecompressor().decompressobj().decompress(data)
            yield data
        return
    handle.seek(mark)
    with zstandard.ZstdDecompressor().stream_reader(_Bounded(handle, end)) as reader:
        while chunk := reader.read(config.chunk_bytes):
            yield chunk


class _Sections:
    """An NCZ's sections by offset, found by binary search."""

    def __init__(self, sections: list[_Section]):
        self.sections = sections
        self.starts = [s.offset for s in sections]

    def at(self, pos: int) -> tuple[_Section | None, int | None]:
        """The section holding `pos`, else None and where the next section starts (None
        when no section follows)."""
        index = bisect.bisect_right(self.starts, pos) - 1
        if index >= 0 and pos < self.sections[index].offset + self.sections[index].size:
            return self.sections[index], None
        following = index + 1
        return None, self.starts[following] if following < len(self.starts) else None


def _encrypt(sections: _Sections, at: int, data: bytes, config) -> bytes:
    """`data` at NCA offset `at`, its parts in CTR sections encrypted again."""
    out = bytearray()
    pos = at
    end = at + len(data)
    while pos < end:
        section, following = sections.at(pos)
        if section is None:
            # Up to the next section (or the end) the data is as it is.
            stop = end if following is None else min(end, following)
            out += data[pos - at : stop - at]
            pos = stop
            continue
        stop = min(end, section.offset + section.size)
        part = data[pos - at : stop - at]
        if section.crypto in config.ctr_crypto_types:
            block = AES.block_size
            skip = pos % block
            prefix = section.counter[: config.counter_prefix_bytes]
            counter = ((pos - skip) // block).to_bytes(block - config.counter_prefix_bytes, "big")
            cipher = AES.new(section.key, AES.MODE_CTR, nonce=b"", initial_value=prefix + counter)
            part = cipher.encrypt(bytes(skip) + part)[skip:]
        out += part
        pos = stop
    return bytes(out)


def _header(members: list[Member], settings: Settings) -> bytes:
    title_config = settings.title_ids
    names = b"".join(m.name.encode() + b"\0" for m in members)
    entry = struct.calcsize(title_config.pfs0_entry)
    head = struct.calcsize(title_config.pfs0_header)
    names += bytes(-(head + entry * len(members) + len(names)) % settings.switch_package.pfs0_align)
    out = struct.pack(
        title_config.pfs0_header, title_config.pfs0_magic.encode(), len(members), len(names), 0
    )
    offset, name_at = 0, 0
    for m in members:
        out += struct.pack(title_config.pfs0_entry, offset, m.out_size, name_at, 0)
        offset += m.out_size
        name_at += len(m.name.encode()) + 1
    return out + names


def build(source: Path, output: Path, settings: Settings, check: Callable[[], None]) -> None:
    """Write the NSP of `source` to `output` (a new file), then read it back to prove it."""
    config = settings.switch_package
    members = plan(source, settings)
    copied: dict[str, str] = {}
    try:
        with source.open("rb") as handle, output.open("xb") as out:
            out.write(_header(members, settings))
            for m in members:
                written = 0
                digest = hashlib.sha256()
                handle.seek(m.offset)
                if m.ncz:
                    head = handle.read(config.ncz_header_bytes)
                    sections = _Sections(_ncz_sections(handle, m.offset, m.size, config))
                    out.write(head)
                    written = len(head)
                    for chunk in _decompressed(handle, m, config):
                        check()
                        data = _encrypt(sections, written, chunk, config)
                        out.write(data)
                        written += len(data)
                else:
                    while written < m.size:
                        check()
                        data = handle.read(min(config.chunk_bytes, m.size - written))
                        if not data:
                            break
                        digest.update(data)
                        out.write(data)
                        written += len(data)
                    copied[m.name] = digest.hexdigest()
                if written != m.out_size:
                    raise PackageError(f"{m.name} came out {written} bytes, not {m.out_size}")
    except (OSError, struct.error, zstandard.ZstdError) as exc:
        raise PackageError(f"writing the NSP failed: {exc}") from exc
    prove(output, members, copied, settings, check)


def prove(output, members: list[Member], copied: dict[str, str], settings, check) -> None:
    """Read the written NSP back: the same members, each NCA hashing to its content ID, each
    other member to what was copied."""
    config = settings.switch_package
    with output.open("rb") as handle:
        found = titles.pfs0_members(handle, settings.title_ids)
        if found is None:
            raise PackageError("the written NSP does not read back")
        start, listed = found
        if [(n, s) for n, _, s in listed] != [(m.name, m.out_size) for m in members]:
            raise PackageError("the written NSP does not list what was written")
        for name, offset, size in listed:
            digest = hashlib.sha256()
            handle.seek(start + offset)
            left = size
            while left:
                check()
                data = handle.read(min(config.chunk_bytes, left))
                if not data:
                    raise PackageError(f"{name} is cut short in the written NSP")
                digest.update(data)
                left -= len(data)
            if name in copied:
                if digest.hexdigest() != copied[name]:
                    raise PackageError(f"{name} does not read back as it was copied")
                continue
            content_id = PurePosixPath(name).name.split(".")[0].lower()
            if digest.hexdigest()[: config.content_id_digits] != content_id:
                raise PackageError(
                    f"{name} does not match its content ID: the NCZ did not give the NCA back"
                )
