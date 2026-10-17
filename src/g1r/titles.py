"""Nintendo Switch title IDs: identification without a DAT, grouping by base game.

A title ID is 16 hex digits. A base game's ends in the `low_hex` bits all zero; its update
is the same ID plus `update_low_hex`; its DLC are numbered in the next block of
`dlc_step_hex`. The ID is read from an NSP/NSZ ticket (PFS0 file names: the rights ID's
first digits are the title ID) or, failing that, from the file name's "[0100...]" tag.
"""

import re
import struct
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from g1r.config import TitleIdConfig

BASE = "base"
UPDATE = "update"
DLC = "dlc"


@dataclass(frozen=True)
class Title:
    title_id: int
    version: int | None
    name: str

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
    """The name a title-ID identity is stored under: the file's name, its ID, its version."""
    version = f"[v{title.version}]" if title.version is not None else ""
    return f"{title.name} [{hex_id(title.title_id, config)}]{version}"


def from_name(file_name: str, config: TitleIdConfig) -> Title | None:
    found = re.search(config.name_pattern, file_name)
    if not found:
        return None
    version = re.search(config.version_pattern, file_name)
    stem = PurePosixPath(file_name).stem
    name = re.split(config.name_end_pattern, stem, maxsplit=1)[0].strip() or stem
    return Title(int(found[1], config.radix), int(version[1]) if version else None, name)


def from_ticket(path: Path, config: TitleIdConfig) -> int | None:
    """The title ID of an NSP/NSZ's ticket, from the PFS0 file names (no keys needed)."""
    header = struct.calcsize(config.pfs0_header)
    entry = struct.calcsize(config.pfs0_entry)
    try:
        with path.open("rb") as handle:
            magic, count, table_size, _ = struct.unpack(config.pfs0_header, handle.read(header))
            if magic != config.pfs0_magic.encode() or count > config.max_entries:
                return None
            handle.read(entry * count)
            table = handle.read(table_size)
    except (OSError, struct.error):
        return None
    for raw in table.split(b"\0"):
        name = raw.decode("ascii", errors="replace")
        if name.lower().endswith(config.ticket_suffix):
            rights = PurePosixPath(name).stem
            if re.fullmatch(f"[0-9A-Fa-f]{{{config.rights_id_digits}}}", rights):
                return int(rights[: config.digits], config.radix)
    return None


def read_title(path: Path, file_name: str, config: TitleIdConfig) -> Title | None:
    named = from_name(file_name, config)
    ticket = (
        from_ticket(path, config)
        if path.suffix.lower().lstrip(".") in config.pfs0_extensions
        else None
    )
    if ticket is None:
        return named
    stem = PurePosixPath(file_name).stem
    return Title(ticket, named.version if named else None, named.name if named else stem)
