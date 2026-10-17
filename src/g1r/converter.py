"""Carrying out one conversion step: write the output beside the source, prove it holds the
same ROM, then give it its name without ever replacing a file (design §4).

Wrap: the ROM goes into a new zip as its only member; the zip is re-read and its member's
name, size and CRC32 must equal the ROM's. Unwrap: the archive's ROM member is extracted;
its size and CRC32 must equal what the scan listed. Either way the source is left as it was:
moving or deleting it is the journal's next step.
"""

import os
import shutil
import subprocess
import zipfile
import zlib
from collections.abc import Callable
from pathlib import Path

from g1r import conversion, moves
from g1r.config import Settings

CRC_FORMAT = "08x"

# Writes one archive member's bytes to a new file: (settings, archive, member, output).
Extractor = Callable[[Settings, Path, str, Path], None]


def crc_and_size(chunk_bytes: int, path: Path) -> tuple[str, int]:
    crc, size = 0, 0
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_bytes):
            crc = zlib.crc32(chunk, crc)
            size += len(chunk)
    return format(crc, CRC_FORMAT), size


def _fsync(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def extract_member(settings: Settings, archive: Path, member: str, output: Path) -> None:
    """Extract one member to `output`, which must not exist yet. Raises MoveError."""
    if archive.suffix.lower() == conversion.ZIP_SUFFIX:
        try:
            with zipfile.ZipFile(archive) as z, z.open(member) as src, output.open("xb") as dst:
                shutil.copyfileobj(src, dst, settings.apply.copy_chunk_bytes)
        except (zipfile.BadZipFile, KeyError) as exc:
            raise moves.MoveError(f"cannot extract {member} from {archive}: {exc}") from exc
        return
    command = [settings.archives.seven_zip_binary, "e", "-so", "-spd", "--", str(archive), member]
    try:
        with output.open("xb") as dst:
            result = subprocess.run(
                command,
                stdout=dst,
                stderr=subprocess.PIPE,
                text=True,
                timeout=settings.apply.extract_timeout_seconds,
                check=False,
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise moves.MoveError(f"7-Zip could not extract {member}: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip().splitlines()
        raise moves.MoveError(detail[-1] if detail else f"7-Zip exited with {result.returncode}")


class Converter:
    def __init__(self, settings: Settings, extract: Extractor = extract_member):
        self.settings = settings
        self.config = settings.apply
        self.extract = extract

    def __call__(self, step) -> os.stat_result:
        """Write `step.destination` from `step.source` (a journal.Move); return its stat."""
        if os.path.lexists(step.destination):
            raise moves.MoveError(f"{step.destination} already exists")
        temp = moves.temp_path(self.config, step.destination)
        try:
            if step.member is None:
                self._wrap(step.source, temp)
            else:
                self._unwrap(step, temp)
            _fsync(temp)
            moves.place(temp, step.destination)
        except FileExistsError as exc:
            raise moves.MoveError(f"{temp} already exists") from exc
        except OSError as exc:
            temp.unlink(missing_ok=True)
            raise moves.MoveError(f"converting {step.source} failed: {exc.strerror}") from exc
        except moves.MoveError:
            temp.unlink(missing_ok=True)
            raise
        moves.fsync_dir(step.destination.parent)
        return step.destination.stat()

    def _wrap(self, source: Path, temp: Path) -> None:
        crc, size = crc_and_size(self.config.copy_chunk_bytes, source)
        with zipfile.ZipFile(
            temp,
            "x",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=self.config.zip_compress_level,
            strict_timestamps=False,
        ) as z:
            z.write(source, arcname=source.name)
        try:
            with zipfile.ZipFile(temp) as z:
                infos = z.infolist()
                bad = z.testzip()
        except zipfile.BadZipFile as exc:
            raise moves.MoveError(f"the new zip of {source} is unreadable: {exc}") from exc
        if (
            len(infos) != 1
            or infos[0].filename != source.name
            or infos[0].file_size != size
            or format(infos[0].CRC, CRC_FORMAT) != crc
            or bad is not None
        ):
            raise moves.MoveError(f"the new zip of {source} does not hold the same data")

    def _unwrap(self, step, temp: Path) -> None:
        if not step.member_crc32:
            raise moves.MoveError(f"the scan listed no CRC32 for {step.member}")
        self.extract(self.settings, step.source, step.member, temp)
        crc, size = crc_and_size(self.config.copy_chunk_bytes, temp)
        if (crc, size) != (step.member_crc32.lower(), step.member_size):
            raise moves.MoveError(
                f"{step.member} extracted with CRC32 {crc} and {size} bytes; "
                f"the archive lists {step.member_crc32} and {step.member_size}"
            )
