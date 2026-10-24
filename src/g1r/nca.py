"""Reading Switch content archives (NCA) inside an NSP/NSZ with the user's own prod.keys.

Two things are read, nothing is written: the content metadata (title ID and version) when the
dump has no unencrypted cnmt.xml, and the version shown to players ("1.0.2") from the control
data's control.nacp. The layout follows hactool: the header is AES-XTS with Nintendo's tweak
(the sector number, big-endian); a section is AES-CTR, keyed from the header's key area
(decrypted with the key area key of its generation) or, when the NCA has a rights ID, from the
ticket's title key (decrypted with the title KEK). Anything unexpected reads as nothing.
"""

import hashlib
import io
import struct
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from Cryptodome.Cipher import AES

from g1r import titles
from g1r.config import NcaConfig, Settings, TitleIdConfig


class KeysError(Exception):
    """An uploaded file is not a usable prod.keys; the message is shown to the user."""


@dataclass(frozen=True)
class Keys:
    header: bytes
    # By key generation.
    key_area: dict[int, bytes] = field(default_factory=dict)
    titlekek: dict[int, bytes] = field(default_factory=dict)


def parse_keys(text: str, config: NcaConfig) -> Keys:
    values: dict[str, bytes] = {}
    for line in text.splitlines():
        name, sep, value = line.partition("=")
        if not sep:
            continue
        try:
            values[name.strip().lower()] = bytes.fromhex(value.strip())
        except ValueError:
            continue
    header = values.get(config.header_key)
    if header is None or len(header) != config.header_key_bytes:
        raise KeysError(f"no {config.header_key} in this file: is it prod.keys?")

    def generations(prefix: str) -> dict[int, bytes]:
        found = {}
        for name, value in values.items():
            if name.startswith(prefix) and len(value) == config.key_bytes:
                try:
                    found[int(name[len(prefix) :], config.generation_radix)] = value
                except ValueError:
                    continue
        return found

    area = generations(config.key_area_key_prefix)
    if not area:
        raise KeysError(f"no {config.key_area_key_prefix}… keys in this file: is it prod.keys?")
    return Keys(header, area, generations(config.titlekek_prefix))


def keys_path(settings: Settings) -> Path:
    return settings.paths.data_dir / settings.decryption.keys_dir / settings.nca.keys_file


@cache
def _loaded(path: Path, mtime_ns: int, config: NcaConfig) -> Keys | None:
    try:
        return parse_keys(path.read_text(encoding="utf-8", errors="replace"), config)
    except (OSError, KeysError):
        return None


def keys_fingerprint(settings: Settings) -> str | None:
    """Changes when the stored prod.keys does (a scan then reads the files again)."""
    try:
        return hashlib.sha1(keys_path(settings).read_bytes()).hexdigest()
    except OSError:
        return None


def load_keys(settings: Settings) -> Keys | None:
    """The stored prod.keys, or None."""
    path = keys_path(settings)
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return None
    return _loaded(path, mtime, settings.nca)


def _xor(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b, strict=True))


def xts_decrypt(key: bytes, data: bytes, config: NcaConfig, first_sector: int = 0) -> bytes:
    """AES-XTS with Nintendo's tweak: the sector number big-endian."""
    half = len(key) >> 1
    data_cipher = AES.new(key[:half], AES.MODE_ECB)
    tweak_cipher = AES.new(key[half:], AES.MODE_ECB)
    block = config.aes_block_bytes
    top = 1 << config.xts_tweak_bits
    out = bytearray()
    for sector, at in enumerate(range(0, len(data), config.sector_bytes), first_sector):
        tweak = int.from_bytes(tweak_cipher.encrypt(sector.to_bytes(block, "big")), "little")
        for start in range(at, at + config.sector_bytes, block):
            mask = tweak.to_bytes(block, "little")
            out += _xor(data_cipher.decrypt(_xor(data[start : start + block], mask)), mask)
            tweak <<= 1
            if tweak >= top:
                tweak = (tweak - top) ^ config.xts_reduction
    return bytes(out)


@dataclass(frozen=True)
class Header:
    """The decrypted header of one NCA at `base` in its container."""

    base: int
    data: bytes

    def byte(self, offset: int) -> int:
        return self.data[offset]

    def rights_id(self, config: NcaConfig) -> bytes:
        return self.data[config.rights_id_offset : config.rights_id_offset + config.key_bytes]

    def generation(self, config: NcaConfig) -> int:
        """The key generation as keys are numbered (0 and 1 are both the first)."""
        found = max(
            self.byte(config.key_generation_offset), self.byte(config.key_generation2_offset)
        )
        return found - 1 if found else 0

    def section(self, index: int, config: NcaConfig) -> tuple[int, bytes]:
        """A section's start in the NCA, and its filesystem header."""
        entry = config.section_table_offset + index * struct.calcsize(config.section_entry)
        start, _ = struct.unpack_from(config.section_entry, self.data, entry)
        fs = config.fs_header_offset + index * config.fs_header_bytes
        return start * config.sector_bytes, self.data[fs : fs + config.fs_header_bytes]


def read_header(handle: BinaryIO, base: int, keys: Keys, config: NcaConfig) -> Header | None:
    handle.seek(base)
    raw = handle.read(config.header_bytes)
    if len(raw) != config.header_bytes:
        return None
    data = xts_decrypt(keys.header, raw, config)
    magic = config.magic.encode()
    if data[config.magic_offset : config.magic_offset + len(magic)] != magic:
        return None
    return Header(base, data)


def _section_key(header: Header, keys: Keys, title_key: bytes | None, config: NcaConfig):
    """The section key: from the key area, or the ticket's title key (rights ID)."""
    generation = header.generation(config)
    if any(header.rights_id(config)):
        kek = keys.titlekek.get(generation)
        if kek is None or title_key is None:
            return None
        return AES.new(kek, AES.MODE_ECB).decrypt(title_key)
    if header.byte(config.key_area_index_offset) != 0:
        return None  # only application keys are read
    area_key = keys.key_area.get(generation)
    if area_key is None:
        return None
    at = config.key_area_offset + config.ctr_key_index * config.key_bytes
    return AES.new(area_key, AES.MODE_ECB).decrypt(header.data[at : at + config.key_bytes])


def _read_section(
    handle: BinaryIO, header: Header, index: int, key: bytes, offset: int, size: int, config
) -> bytes:
    """`size` bytes at `offset` in a CTR section, decrypted."""
    start, fs = header.section(index, config)
    at = start + offset
    aligned = at - at % config.aes_block_bytes
    handle.seek(header.base + aligned)
    data = handle.read(size + at - aligned)
    upper = fs[config.section_ctr_offset : config.section_ctr_offset + config.section_ctr_bytes]
    lower = (aligned >> config.ctr_shift).to_bytes(config.section_ctr_bytes, "big")
    cipher = AES.new(key, AES.MODE_CTR, nonce=b"", initial_value=upper[::-1] + lower)
    return cipher.decrypt(data)[at - aligned :]


def _ctr_range(header: Header, index: int, range_offset: int, config) -> tuple[int, int] | None:
    """(offset, size) of a CTR section's data, from its fs header."""
    _, fs = header.section(index, config)
    _, _, crypt = struct.unpack_from(config.fs_kinds, fs)
    if crypt != config.crypt_ctr:
        return None
    return struct.unpack_from(config.range, fs, range_offset)


def _members(handle: BinaryIO, title_config: TitleIdConfig):
    found = titles.pfs0_members(handle, title_config)
    return ([], 0) if found is None else (found[1], found[0])


def _title_key(handle, members, start, header: Header, config: NcaConfig, title_config):
    """The encrypted title key from the NSP's common ticket for this NCA's rights ID."""
    rights = header.rights_id(config).hex()
    for name, offset, size in members:
        if PurePosixPath(name).stem.lower() == rights and name.endswith(title_config.ticket_suffix):
            handle.seek(start + offset)
            ticket = handle.read(size)
            if len(ticket) <= config.ticket_type_offset:
                return None
            if ticket[config.ticket_type_offset] != config.ticket_common:
                return None
            at = config.ticket_titlekey_offset
            return ticket[at : at + config.key_bytes]
    return None


def read_meta(
    path: Path, keys: Keys, config: NcaConfig, title_config: TitleIdConfig
) -> tuple[int, int] | None:
    """(title ID, version) from the NSP's encrypted content metadata."""
    try:
        with path.open("rb") as handle:
            members, start = _members(handle, title_config)
            suffix = config.cnmt_suffix + config.nca_suffix
            for name, offset, _ in members:
                if not name.lower().endswith(suffix):
                    continue
                header = read_header(handle, start + offset, keys, config)
                if header is None or header.byte(config.content_type_offset) != config.meta_type:
                    continue
                key = _section_key(header, keys, None, config)
                found = _ctr_range(header, 0, config.pfs0_range_offset, config)
                if key is None or found is None or found[1] > config.max_read_bytes:
                    continue
                pfs0 = io.BytesIO(_read_section(handle, header, 0, key, *found, config))
                inner = titles.pfs0_members(pfs0, title_config)
                if inner is None:
                    continue
                for inner_name, inner_offset, _ in inner[1]:
                    if inner_name.lower().endswith(config.cnmt_suffix):
                        pfs0.seek(inner[0] + inner_offset)
                        head = pfs0.read(struct.calcsize(config.cnmt_header))
                        return struct.unpack(config.cnmt_header, head)
    except (OSError, struct.error, ValueError):
        return None
    return None


def read_display_version(
    path: Path, keys: Keys, config: NcaConfig, title_config: TitleIdConfig
) -> str | None:
    """The version shown to players, from the control data's control.nacp."""
    try:
        with path.open("rb") as handle:
            members, start = _members(handle, title_config)
            suffix = config.cnmt_suffix + config.nca_suffix
            for name, offset, _ in members:
                lower = name.lower()
                if not lower.endswith(config.nca_suffix) or lower.endswith(suffix):
                    continue
                header = read_header(handle, start + offset, keys, config)
                if header is None or header.byte(config.content_type_offset) != config.control_type:
                    continue
                title_key = _title_key(handle, members, start, header, config, title_config)
                key = _section_key(header, keys, title_key, config)
                found = _ctr_range(header, 0, config.romfs_range_offset, config)
                if key is None or found is None:
                    continue
                return _nacp_version(handle, header, key, found[0], config)
    except (OSError, struct.error, ValueError, UnicodeDecodeError):
        return None
    return None


def _nacp_version(handle, header: Header, key: bytes, romfs: int, config: NcaConfig) -> str | None:
    def read(offset: int, size: int) -> bytes:
        if size > config.max_read_bytes:
            raise ValueError("too large")
        return _read_section(handle, header, 0, key, romfs + offset, size, config)

    table, table_size, data = struct.unpack(
        config.romfs_header, read(0, struct.calcsize(config.romfs_header))
    )
    files = read(table, table_size)
    entry = struct.calcsize(config.romfs_file)
    at = 0
    while at + entry <= len(files):
        _, _, offset, size, _, name_size = struct.unpack_from(config.romfs_file, files, at)
        name = files[at + entry : at + entry + name_size].decode("utf-8")
        if name == config.nacp_name:
            end = config.display_version_offset + config.display_version_bytes
            if size < end:
                return None
            raw = read(data + offset + config.display_version_offset, config.display_version_bytes)
            text = raw.split(b"\0", 1)[0].decode("utf-8").strip()
            return text or None
        at += entry + -(-name_size // config.romfs_name_align) * config.romfs_name_align
    return None
