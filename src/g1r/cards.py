"""Card image headers the scan reads: Nintendo 3DS NCSD (.3ds/.cci).

From the header alone (no keys): whether the game partition is encrypted (emulators need a
decrypted image), and the card's full size, which tells a trimmed image (its padding cut
off). A trimmed image matches the DAT once padded back, without writing anything.
"""

import struct
import zipfile
import zlib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from g1r.config import NcsdConfig

ENCRYPTED = "encrypted"
TRIMMED = "trimmed"
U32 = "<I"
U8 = "<B"


@dataclass(frozen=True)
class CardInfo:
    image_size: int
    data_size: int
    encrypted: bool
    product_code: str = ""

    @property
    def trimmed(self) -> bool:
        return self.data_size < self.image_size

    def notes(self) -> list[str]:
        return [n for n, on in ((ENCRYPTED, self.encrypted), (TRIMMED, self.trimmed)) if on]


@contextmanager
def open_payload(path: Path, member: str | None) -> Iterator[BinaryIO]:
    """The ROM's bytes as a stream: the file, or one member of a zip."""
    if member is None:
        with path.open("rb") as handle:
            yield handle
    else:
        with zipfile.ZipFile(path) as archive, archive.open(member) as handle:
            yield handle  # type: ignore[misc]


def _u(fmt: str, data: bytes, offset: int) -> int | None:
    end = offset + struct.calcsize(fmt)
    return struct.unpack(fmt, data[offset:end])[0] if len(data) >= end else None


def read_ncsd(config: NcsdConfig, path: Path, member: str | None, size: int) -> CardInfo | None:
    """The card's facts, or None when this is not an NCSD image."""
    header_end = config.flags_offset + config.media_unit_flag + struct.calcsize(U8)
    try:
        with open_payload(path, member) as stream:
            header = stream.read(header_end)
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
            )
            # Streams (zip members) only read forward: skip to the partition.
            stream.read(max(first * unit - len(header), 0))
            ncch = stream.read(ncch_end)
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
    return CardInfo(units * unit, size, encrypted, product)


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
