"""Nintendo Switch title IDs: identification without a DAT, grouping by base game.

A title ID is 16 hex digits. A base game's ends in the `low_hex` bits all zero; its update
is the same ID plus `update_low_hex`; its DLC are numbered in the next block of
`dlc_step_hex`. Everything is read from inside the NSP/NSZ (a PFS0 container), never from
its file name, which is arbitrary: the unencrypted content metadata `<id>.cnmt.xml` when the
dump has one (title ID and version), else the ticket's name (the rights ID's first digits are
the title ID; no version). The file name gives only the name shown.
"""

import re
import struct
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from g1r.config import TitleIdConfig

BASE = "base"
UPDATE = "update"
DLC = "dlc"


@dataclass(frozen=True)
class Title:
    title_id: int
    version: int | None
    name: str
    # The version shown to players ("1.0.2"), read with the user's prod.keys.
    display: str | None = None

    def role(self, config: TitleIdConfig) -> str:
        low = self.title_id & int(config.low_hex, config.radix)
        if low == 0:
            return BASE
        return UPDATE if low == int(config.update_low_hex, config.radix) else DLC

    def app_id(self, config: TitleIdConfig) -> int:
        """The base game's title ID."""
        block = self.title_id & ~int(config.low_hex, config.radix)
        return block - int(config.dlc_step_hex, config.radix) if self.role(config) == DLC else block


def hex_id(value: int, config: TitleIdConfig) -> str:
    return format(value, f"0{config.digits}X")


def identity_name(title: Title, config: TitleIdConfig) -> str:
    """The name a title-ID identity is stored under: the file's name, its ID, its version and
    its shown version."""
    version = f"[v{title.version}]" if title.version is not None else ""
    display = ""
    if title.display:
        display = "[" + config.display_prefix + re.sub(r"[\[\]]", "", title.display) + "]"
    return f"{title.name} [{hex_id(title.title_id, config)}]{version}{display}"


def from_name(stored: str, config: TitleIdConfig) -> Title | None:
    """A stored identity's name (`identity_name`) read back. It has no extension, so a dot
    is part of the name ("Mr. Shifty"), never the start of one."""
    found = re.search(config.name_pattern, stored)
    if not found:
        return None
    version = re.search(config.version_pattern, stored)
    display = re.search(config.display_pattern, stored)
    name = re.split(config.name_end_pattern, stored, maxsplit=1)[0].strip() or stored
    return Title(
        int(found[1], config.radix),
        int(version[1]) if version else None,
        name,
        display[1] if display else None,
    )


def pfs0_members(
    handle: BinaryIO, config: TitleIdConfig
) -> tuple[int, list[tuple[str, int, int]]] | None:
    """A PFS0's member names with their (offset, size), and where member data starts, read
    from the handle's current position (the offsets are relative to that start)."""
    origin = handle.tell()
    header = struct.calcsize(config.pfs0_header)
    entry = struct.calcsize(config.pfs0_entry)
    try:
        magic, count, table_size, _ = struct.unpack(config.pfs0_header, handle.read(header))
        if magic != config.pfs0_magic.encode() or count > config.max_entries:
            return None
        entries = [struct.unpack(config.pfs0_entry, handle.read(entry)) for _ in range(count)]
    except struct.error:
        return None
    table = handle.read(table_size)
    members = []
    for offset, size, name_at, _ in entries:
        end = table.find(b"\0", name_at)
        raw = table[name_at : end if end >= 0 else len(table)]
        members.append((raw.decode("ascii", errors="replace"), offset, size))
    return origin + header + entry * len(entries) + table_size, members


def _pfs0(path: Path, config: TitleIdConfig) -> tuple[int, list[tuple[str, int, int]]] | None:
    try:
        with path.open("rb") as handle:
            return pfs0_members(handle, config)
    except OSError:
        return None


def from_ticket(path: Path, config: TitleIdConfig) -> int | None:
    """The title ID of an NSP/NSZ's ticket, from the PFS0 file names (no keys needed)."""
    found = _pfs0(path, config)
    if found is None:
        return None
    for name, _, _ in found[1]:
        if name.lower().endswith(config.ticket_suffix):
            rights = PurePosixPath(name).stem
            if re.fullmatch(f"[0-9A-Fa-f]{{{config.rights_id_digits}}}", rights):
                return int(rights[: config.digits], config.radix)
    return None


def from_cnmt_xml(path: Path, config: TitleIdConfig) -> tuple[int, int] | None:
    """(title ID, version) from the NSP/NSZ's unencrypted `<id>.cnmt.xml`, if it has one."""
    found = _pfs0(path, config)
    if found is None:
        return None
    start, members = found
    xml = next(
        (
            (offset, size)
            for name, offset, size in members
            if name.lower().endswith(config.cnmt_xml_suffix)
        ),
        None,
    )
    if xml is None or xml[1] > config.max_cnmt_xml_bytes:
        return None
    try:
        with path.open("rb") as handle:
            handle.seek(start + xml[0])
            root = ElementTree.fromstring(handle.read(xml[1]))
        return int(root.findtext("Id", ""), 0), int(root.findtext("Version", ""), 0)
    except (OSError, ElementTree.ParseError, ValueError):
        return None


def content_ids(path: Path, config: TitleIdConfig) -> list[str] | None:
    """The content IDs of the NSP/NSZ's content archives, from their names (the content
    metadata's own archive left out), or None when it is no readable PFS0."""
    found = _pfs0(path, config)
    if found is None:
        return None
    ids = []
    for name, _, _ in found[1]:
        lower = name.lower()
        if lower.endswith(config.cnmt_nca_suffix):
            continue
        suffix = next((s for s in config.nca_suffixes if lower.endswith(s)), None)
        if suffix is not None:
            ids.append(lower[: -len(suffix)])
    return sorted(ids)


def is_pfs0(path: Path, config: TitleIdConfig) -> bool:
    return path.suffix.lower().lstrip(".") in config.pfs0_extensions


def read_title(path: Path, file_name: str, config: TitleIdConfig) -> Title | None:
    """The file's title from its contents; its name only for the name shown."""
    if not is_pfs0(path, config):
        return None
    stem = PurePosixPath(file_name).stem
    name = re.split(config.name_end_pattern, stem, maxsplit=1)[0].strip() or stem
    meta = from_cnmt_xml(path, config)
    if meta is not None:
        return Title(meta[0], meta[1], name)
    ticket = from_ticket(path, config)
    return None if ticket is None else Title(ticket, None, name)
