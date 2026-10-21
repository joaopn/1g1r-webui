"""CSO (CISO v0/v1), the compressed ISO of PlayStation 2 and PSP games: decoding it back to
the ISO, which chdman can read. The format is lossless block deflate, so the ISO decoded is
the image that was compressed; the converter still checks it against the CHD's round trip.
"""

import struct
import zlib
from pathlib import Path

from g1r import stopping
from g1r.config import CsoConfig

CSO = "cso"


class CsoError(Exception):
    """The file is not a CSO this app reads, or it is damaged."""


def decode(config: CsoConfig, source: Path, output: Path) -> int:
    """Write the ISO that `source` holds to `output` (a new file); return its size."""
    header_bytes = struct.calcsize(config.header)
    entry_bytes = struct.calcsize(config.index_entry)
    plain = 1 << config.plain_bit
    with source.open("rb") as handle:
        header = handle.read(header_bytes)
        if len(header) < header_bytes:
            raise CsoError(f"{source.name} is too short to be a CSO")
        magic, header_size, total, block, version, shift = struct.unpack(config.header, header)
        if magic != config.magic.encode():
            raise CsoError(f"{source.name} is not a CSO")
        if version not in config.versions:
            raise CsoError(f"{source.name} is CSO version {version}, which is not read")
        if block <= 0:
            raise CsoError(f"{source.name} has a block size of {block}")
        blocks = (total + block - 1) // block
        handle.seek(max(header_size, header_bytes))
        raw = handle.read(entry_bytes * (blocks + 1))
        if len(raw) < entry_bytes * (blocks + 1):
            raise CsoError(f"{source.name} is cut short (its block index)")
        index = [e[0] for e in struct.iter_unpack(config.index_entry, raw)]
        written = 0
        with output.open("xb") as out:
            for n in range(blocks):
                stopping.check()
                start = (index[n] & ~plain) << shift
                end = (index[n + 1] & ~plain) << shift
                handle.seek(start)
                data = handle.read(end - start)
                want = min(block, total - written)
                if not index[n] & plain:
                    try:
                        data = zlib.decompress(data, config.window_bits, block)
                    except zlib.error as exc:
                        raise CsoError(f"{source.name}: block {n} is damaged") from exc
                if len(data) < want:
                    raise CsoError(f"{source.name}: block {n} is cut short")
                out.write(data[:want])
                written += want
    if written != total:
        raise CsoError(f"{source.name} decoded to {written} bytes, its header says {total}")
    return written
