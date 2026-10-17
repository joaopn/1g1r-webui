"""Carrying out one conversion step: write the output beside the source, prove it holds the
same ROM, then give it its name without ever replacing a file (design §4).

Wrap: the ROM goes into a new zip as its only member; the zip is re-read and its member's
name, size and CRC32 must equal the ROM's. Unwrap: the archive's ROM member is extracted;
its size and CRC32 must equal what the scan listed. Either way the source is left as it was:
moving or deleting it is the journal's next step.
"""

import hashlib
import os
import shutil
import subprocess
import zipfile
import zlib
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from g1r import conversion, discs, moves
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
            if step.recipe in (conversion.RECIPE_DISC, conversion.RECIPE_ARCHIVE_DISC):
                self._disc(step, temp)
            elif step.member is None:
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

    def _disc(self, step, temp: Path) -> None:
        """chdman makes the CHD; it must pass `verify`, and its tracks extracted back must
        equal the originals: the same data in order, and per file when there are several.
        For GameCube and Wii, dolphin-tool makes an RVZ instead (`_rvz`)."""
        chdman = self.settings.chdman
        work = moves.work_path(self.config, step.destination)
        try:
            work.mkdir()
        except FileExistsError as exc:
            raise moves.MoveError(f"{work} already exists (left by an interrupted run?)") from exc
        try:
            disc = (
                self._unpack(step, work)
                if step.recipe == conversion.RECIPE_ARCHIVE_DISC
                else step.source
            )
            cue = disc.suffix.lower().lstrip(".") == discs.CUE
            originals = discs.cue_paths(disc) if cue else [disc]
            each, whole = self._digests(originals)
            if step.disc_mode == discs.RVZ:
                self._rvz(step, disc, whole, temp)
                return
            discs.create(chdman, step.disc_mode, disc, temp)
            discs.verify(chdman, temp)
            back = work / "back"
            back.mkdir()
            if step.disc_mode == discs.CREATEDVD:
                image = back / "disc.iso"
                discs.extract_dvd(chdman, temp, image)
                tracks = [image]
            else:
                tracks = discs.extract_cd(chdman, temp, back)
            again, whole_again = self._digests(tracks)
            if whole_again != whole or (len(originals) > 1 and again != each):
                raise moves.MoveError(
                    f"the CHD of {step.source.name} does not give back the same tracks"
                )
        except discs.DiscError as exc:
            temp.unlink(missing_ok=True)
            raise moves.MoveError(str(exc)) from exc
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _rvz(self, step, image: Path, sha1: str, temp: Path) -> None:
        """dolphin-tool makes the RVZ; the disc it holds must have the image's SHA1."""
        dolphin = self.settings.dolphin
        user_dir = self.settings.paths.data_dir / dolphin.user_dir
        # dolphin-tool would replace an existing file: claim the temporary name first.
        temp.open("xb").close()
        discs.make_rvz(dolphin, user_dir, image, temp)
        if discs.rvz_sha1(dolphin, user_dir, temp) != sha1:
            raise moves.MoveError(f"the RVZ of {step.source.name} does not hold the same disc")

    def _unpack(self, step, work: Path) -> Path:
        """Extract an archive's disc files to `work/source`, each checked against the CRC32
        and size the scan listed; return the cue sheet or ISO among them."""
        source = work / "source"
        found = None
        for name, size, crc in step.inner:
            relative = PurePosixPath(name)
            if relative.is_absolute() or ".." in relative.parts:
                raise moves.MoveError(f"{step.source.name} holds {name}, outside the archive")
            path = source.joinpath(*relative.parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            self.extract(self.settings, step.source, name, path)
            if not crc:
                raise moves.MoveError(f"the scan listed no CRC32 for {name}")
            if crc_and_size(self.config.copy_chunk_bytes, path) != (crc.lower(), size):
                raise moves.MoveError(f"{name} did not extract as the archive lists it")
            if relative.suffix.lower().lstrip(".") in (discs.CUE, *discs.IMAGES):
                found = path
        if found is None:
            raise moves.MoveError(f"{step.source.name} holds no cue sheet or disc image")
        return found

    def _digests(self, paths: list[Path]) -> tuple[list[str], str]:
        """SHA1 of each file, and of all of them in order (the disc's data)."""
        whole = hashlib.sha1(usedforsecurity=False)
        each = []
        for path in paths:
            one = hashlib.sha1(usedforsecurity=False)
            with path.open("rb") as handle:
                while chunk := handle.read(self.config.copy_chunk_bytes):
                    one.update(chunk)
                    whole.update(chunk)
            each.append(one.hexdigest())
        return each, whole.hexdigest()

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
