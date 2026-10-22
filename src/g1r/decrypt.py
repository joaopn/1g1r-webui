"""Decrypting Nintendo 3DS card images (CCI/NCSD) with the user's own keys.

The keys come from the user only, added on a 3DS folder's Conversion page and kept in the
data directory (`decryption.keys_dir`): the ARM9 BootROM's protected region (boot9, dumped
from their console) and, for titles encrypted with a seed, seeddb. The app ships none and
derives none, and never sends or shows them. pyctr does the AES work: each NCCH partition
is read through its crypto engine as the "full decrypted" stream, which also sets the NCCH
flags to "no crypto" the way GodMode9 does; the card header, whatever lies between and
after the partitions, and a partition the dump left blank (`cards.is_blank`) are copied as
they are. Whether the result is right is not decided
here: the converter checks it against the hashes its partitions carry
(`cards.prove_decrypted`).
"""

import hashlib
from pathlib import Path

from pyctr.common import PyCTRError
from pyctr.crypto import CryptoEngine, CryptoError, SeedDBError
from pyctr.crypto import seeddb as pyctr_seeddb
from pyctr.crypto.engine import BOOT9_PROT_HASH
from pyctr.type.cci import CCIReader
from pyctr.type.ncch import NCCHReader, NCCHSection, NCCHSeedError

from g1r import cards, stopping
from g1r.config import NcsdConfig, Settings
from g1r.private_files import write_private

BOOT9 = "boot9"
SEEDDB = "seeddb"
KEY_FILES = (BOOT9, SEEDDB)


class DecryptError(Exception):
    """The image cannot be decrypted (no keys, a seed missing, not a card image)."""


class KeyFileError(Exception):
    """An uploaded key file is not what it claims to be; the message is shown to the user."""


def keys_dir(settings: Settings) -> Path:
    return settings.paths.data_dir / settings.decryption.keys_dir


def _path(settings: Settings, kind: str) -> Path:
    config = settings.decryption
    return keys_dir(settings) / (config.boot9_file if kind == BOOT9 else config.seeddb_file)


def boot9_path(settings: Settings) -> Path | None:
    """The stored boot9, or None (decryption is then not offered)."""
    path = _path(settings, BOOT9)
    return path if path.is_file() else None


def seeddb_path(settings: Settings) -> Path | None:
    path = _path(settings, SEEDDB)
    return path if path.is_file() else None


def _seed_count(settings: Settings, data: bytes) -> int | None:
    """The number of seeds a seeddb holds, or None when the data is not one."""
    config = settings.decryption
    if len(data) < config.seeddb_header_bytes:
        return None
    count = int.from_bytes(data[: config.seeddb_count_bytes], "little")
    if len(data) != config.seeddb_header_bytes + count * config.seeddb_entry_bytes:
        return None
    return count


def seed_ids(settings: Settings) -> set[str] | None:
    """The titles (program IDs, as `cards.CardInfo.program_id` writes them) whose seed the
    stored seeddb holds, or None without a seeddb."""
    path = seeddb_path(settings)
    if path is None:
        return None
    config = settings.decryption
    data = path.read_bytes()
    count = _seed_count(settings, data)
    if count is None:
        return None
    first = config.seeddb_header_bytes
    return {
        data[at : at + config.seeddb_title_id_bytes][::-1].hex()
        for at in range(first, first + count * config.seeddb_entry_bytes, config.seeddb_entry_bytes)
    }


def _write_private(settings: Settings, path: Path, data: bytes) -> None:
    write_private(path, data, settings.decryption.file_mode)


def store_key(settings: Settings, kind: str, data: bytes) -> None:
    """Check an uploaded key file and keep it (replacing the previous one)."""
    config = settings.decryption
    if len(data) > config.max_upload_bytes:
        raise KeyFileError("the file is larger than decryption.max_upload_bytes")
    if kind == BOOT9:
        if len(data) not in config.boot9_sizes:
            raise KeyFileError(
                f"a boot9 dump is {' or '.join(map(str, config.boot9_sizes))} bytes, "
                f"this file is {len(data)}"
            )
        protected = data[-config.protected_bytes :]
        if hashlib.sha256(protected).hexdigest() != BOOT9_PROT_HASH:
            raise KeyFileError("this is not a retail 3DS boot9 dump (its checksum differs)")
        _write_private(settings, _path(settings, BOOT9), protected)
    elif kind == SEEDDB:
        if _seed_count(settings, data) is None:
            raise KeyFileError("this is not a seeddb file (its size does not match its count)")
        _write_private(settings, _path(settings, SEEDDB), data)
    else:
        raise KeyFileError(f"unknown key file {kind!r}")


def remove_key(settings: Settings, kind: str) -> None:
    if kind not in KEY_FILES:
        raise KeyFileError(f"unknown key file {kind!r}")
    _path(settings, kind).unlink(missing_ok=True)


def key_status(settings: Settings) -> dict:
    """What is stored, never the keys themselves."""
    seeds = seeddb_path(settings)
    count = _seed_count(settings, seeds.read_bytes()) if seeds else None
    return {BOOT9: boot9_path(settings) is not None, SEEDDB: count}


def decrypt_cci(settings: Settings, config: NcsdConfig, source: Path, output: Path) -> None:
    """Write the decrypted image of `source` to `output` (a new file)."""
    boot9 = boot9_path(settings)
    if boot9 is None:
        raise DecryptError("no boot9 has been added (Conversion page of a 3DS folder)")
    seeds = seeddb_path(settings)
    if seeds is not None:
        with seeds.open("rb") as handle:
            pyctr_seeddb.load_seeddb(handle)
    chunk = settings.apply.copy_chunk_bytes
    try:
        cci = CCIReader(str(source), load_contents=False)
        # Negative sections are the card's own headers: copied as they are.
        partitions = sorted(
            (r for r in cci.sections.values() if r.section >= 0), key=lambda r: r.offset
        )
        with source.open("rb") as raw, output.open("xb") as out:
            position = 0
            for region in partitions:
                raw.seek(position)
                out.write(raw.read(region.offset - position))
                position = region.offset
                raw.seek(position)
                if region.section and cards.is_blank(raw.read(config.proof.ncch_header_bytes)):
                    continue
                ncch = NCCHReader(
                    cci.open_raw_section(region.section), crypto=CryptoEngine(boot9=str(boot9))
                )
                if not ncch.content_size:
                    raise DecryptError(
                        f"{source.name}: partition {region.section} has a header but no content"
                    )
                with ncch.open_raw_section(NCCHSection.FullDecrypted) as clear:
                    while block := clear.read(chunk):
                        stopping.check()
                        out.write(block)
                position = region.offset + region.size
            raw.seek(position)
            while block := raw.read(chunk):
                stopping.check()
                out.write(block)
    except (NCCHSeedError, SeedDBError) as exc:
        hint = "its seed is not in the seeddb added" if seeds else "no seeddb has been added"
        raise DecryptError(f"{source.name} is encrypted with a seed and {hint}") from exc
    except CryptoError as exc:
        raise DecryptError(f"the boot9 added gave no usable keys: {exc}") from exc
    except FileExistsError:
        raise
    except (PyCTRError, OSError, ValueError, KeyError) as exc:
        raise DecryptError(f"{source.name} could not be decrypted: {exc}") from exc
