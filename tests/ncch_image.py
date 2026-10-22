"""Small but complete 3DS card images for tests: one NCCH partition with an extended header,
an ExeFS holding one file and a RomFS with its three-level hash tree, every hash right, laid
out from the same config fields `cards` reads (so a test image is checked like a real one)."""

import hashlib
import os
import struct

from g1r import cards

UNIT = 512  # media unit with exponent 0 (the config's media_unit_bytes)
PARTITION_UNITS = 4  # the NCCH starts here
EXHEADER = 0x400
ACCESS_DESC = 0x400
EXEFS_FILE = 700
ROMFS_DATA = 3000
BLOCK_LOG2 = 9  # every IVFC level in 512-byte blocks
BLANK_UNITS = 2  # a blank partition's size
CONTENT_SIZE = 0x104  # in the NCCH header, in media units
MEDIA_ID = 0x108  # in the card header; all zeros would make it a NAND to pyctr

# What a real card holds after its data: 0xFF bytes.
CARD_PADDING = b"\xff"


def _put(buf: bytearray, at: int, data: bytes) -> None:
    buf[at : at + len(data)] = data


def _units(size: int) -> int:
    return -(-size // UNIT)


def _blocks_hashed(data: bytes, block: int) -> bytes:
    return b"".join(
        hashlib.sha256(data[i : i + block].ljust(block, b"\0")).digest()
        for i in range(0, len(data), block)
    )


def ncch(config, *, encrypted: bool, product: str, seed: bool, program_id: str) -> bytes:
    p = config.proof
    block = 1 << BLOCK_LOG2
    # ExeFS: header (one entry, its hash at the end) then the file.
    code = os.urandom(EXEFS_FILE)
    exefs_header = bytearray(p.exefs_header_bytes)
    _put(exefs_header, 0, b".code")
    struct.pack_into("<II", exefs_header, p.exefs_name_bytes, 0, len(code))
    _put(exefs_header, p.exefs_header_bytes - p.hash_bytes, hashlib.sha256(code).digest())
    exefs = bytes(exefs_header) + code
    # RomFS: IVFC header, master hash, then level 3 (data), level 1, level 2.
    level3 = os.urandom(ROMFS_DATA)
    level2 = _blocks_hashed(level3, block)
    level1 = _blocks_hashed(level2, block)
    master = _blocks_hashed(level1, block)
    ivfc = bytearray(p.ivfc_header_bytes)
    _put(ivfc, 0, p.ivfc_magic.encode())
    struct.pack_into("<I", ivfc, p.ivfc_master_size_offset, len(master))
    for i, level in enumerate((level1, level2, level3)):
        at = p.ivfc_levels_offset + i * p.ivfc_level_bytes
        struct.pack_into("<Q", ivfc, at + p.ivfc_level_size_offset, len(level))
        struct.pack_into("<I", ivfc, at + p.ivfc_level_block_offset, BLOCK_LOG2)
    romfs = bytearray(ivfc + master)
    for level in (level3, level1, level2):
        romfs += bytes(-len(romfs) % block) + level
    romfs = bytes(romfs)
    # The partition: header, extended header + access descriptor, ExeFS, RomFS.
    exheader = os.urandom(EXHEADER) + os.urandom(ACCESS_DESC)
    exefs_at = _units(p.ncch_header_bytes + len(exheader))
    romfs_at = exefs_at + _units(len(exefs))
    total = romfs_at + _units(len(romfs))
    image = bytearray(total * UNIT)
    header = bytearray(p.ncch_header_bytes)
    _put(header, config.ncch_magic_offset, config.ncch_magic.encode())
    struct.pack_into("<I", header, CONTENT_SIZE, total)
    flags = 0 if encrypted else config.no_crypto_mask
    header[config.ncch_flags_offset + config.crypto_flag] = flags | (
        config.seed_mask if seed else 0
    )
    _put(header, config.product_code_offset, product.encode())
    _put(header, config.program_id_offset, bytes.fromhex(program_id)[::-1])
    struct.pack_into("<I", header, p.exheader_size_offset, EXHEADER)
    _put(header, p.exheader_hash_offset, hashlib.sha256(exheader[:EXHEADER]).digest())
    struct.pack_into("<III", header, p.exefs_region_offset, exefs_at, _units(len(exefs)), 1)
    _put(header, p.exefs_hash_offset, hashlib.sha256(exefs[: p.exefs_header_bytes]).digest())
    struct.pack_into("<III", header, p.romfs_region_offset, romfs_at, _units(len(romfs)), 1)
    _put(header, p.romfs_hash_offset, hashlib.sha256(romfs[:UNIT].ljust(UNIT, b"\0")).digest())
    _put(image, 0, header)
    _put(image, p.ncch_header_bytes, exheader)
    _put(image, exefs_at * UNIT, exefs)
    _put(image, romfs_at * UNIT, romfs)
    return bytes(image)


# Where each region of the partition starts, for tests that break one (offsets in the card).
def regions(config) -> dict[str, int]:
    p = config.proof
    base = PARTITION_UNITS * UNIT
    exefs_at = _units(p.ncch_header_bytes + EXHEADER + ACCESS_DESC) * UNIT
    exefs_size = _units(p.exefs_header_bytes + EXEFS_FILE) * UNIT
    romfs = base + exefs_at + exefs_size
    return {
        "extended header": base + p.ncch_header_bytes,
        "ExeFS header": base + exefs_at,
        "ExeFS file .code": base + exefs_at + p.exefs_header_bytes,
        "RomFS (level 3": romfs + UNIT,
    }


def card(
    make_settings,
    *,
    encrypted: bool,
    product: str = "CTR-P-AWAE",
    seed: bool = False,
    program_id: str = "0004000000031c00",
    padding_units: int = 2,
    blank: int | None = None,
    blank_byte: int = 0,
) -> bytes:
    """A full card image: NCSD header, the partition, then padding_units of card padding.
    With `blank`, that slot of the partition table holds a partition of blank_byte only,
    after the game's (as some releases leave the update partition)."""
    config = make_settings().card_images["ncsd"]
    partition = ncch(config, encrypted=encrypted, product=product, seed=seed, program_id=program_id)
    if blank is not None:
        partition += bytes([blank_byte]) * (BLANK_UNITS * UNIT)
    units = PARTITION_UNITS + len(partition) // UNIT + padding_units
    # Zeros up to the partition (unused partition-table slots are empty), card padding after.
    image = bytearray(PARTITION_UNITS * UNIT) + CARD_PADDING * ((units - PARTITION_UNITS) * UNIT)
    _put(image, config.magic_offset, config.magic.encode())
    _put(image, MEDIA_ID, bytes.fromhex(program_id)[::-1])
    struct.pack_into(cards.U32, image, config.image_size_offset, units)
    game_units = len(partition) // UNIT - (BLANK_UNITS if blank is not None else 0)
    struct.pack_into("<II", image, config.partition_table_offset, PARTITION_UNITS, game_units)
    if blank is not None:
        struct.pack_into(
            "<II",
            image,
            config.partition_table_offset + blank * config.partition_entry_bytes,
            PARTITION_UNITS + game_units,
            BLANK_UNITS,
        )
    image[config.flags_offset + config.media_unit_flag] = 0
    _put(image, PARTITION_UNITS * UNIT, partition)
    return bytes(image)
