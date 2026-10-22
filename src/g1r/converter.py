"""Carrying out one conversion step: write the output beside the source, prove it holds the
same ROM, then give it its name without ever replacing a file (design §4).

Wrap: the ROM goes into a new zip as its only member; the zip is re-read and its member's
name, size and CRC32 must equal the ROM's. Unwrap: the archive's ROM member is extracted;
its size and CRC32 must equal what the scan listed. Byteswap: the ROM is written in the
native byte order (bare or zipped), read back and swapped again, and must equal the original.
Either way the source is left as it was: moving or deleting it is the journal's next step.
"""

import hashlib
import os
import shutil
import subprocess
import zipfile
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

from g1r import cards, conversion, cso, decrypt, discs, hashing, moves, stopping
from g1r.config import Settings

CRC_FORMAT = "08x"
# Inside a disc conversion's work directory: the files unpacked or decoded for chdman.
UNPACKED = "source"

# Writes one archive member's bytes to a new file: (settings, archive, member, output).
Extractor = Callable[[Settings, Path, str, Path], None]


def crc_and_size(chunk_bytes: int, path: Path) -> tuple[str, int]:
    crc, size = 0, 0
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_bytes):
            stopping.check()
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
            result = stopping.run(
                command,
                settings.apply.extract_timeout_seconds,
                stdout=dst,
                stderr=subprocess.PIPE,
                text=True,
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise moves.MoveError(f"7-Zip could not extract {member}: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip().splitlines()
        raise moves.MoveError(detail[-1] if detail else f"7-Zip exited with {result.returncode}")


def _drop_unpacked(work: Path) -> None:
    """Remove what was unpacked for the conversion as soon as the output is written."""
    shutil.rmtree(work / UNPACKED, ignore_errors=True)


@dataclass(frozen=True)
class Swapped:
    """What a byteswap pass read: the SHA1 of the source and of the swapped data, the
    source's CRC32 and size, and any trailing bytes short of a word."""

    sha1: str
    swapped_sha1: str
    crc32: str
    size: int
    rest: bytes


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
            elif step.recipe == conversion.RECIPE_BYTESWAP:
                self._byteswap(step, temp)
            elif step.recipe == conversion.RECIPE_DECRYPT:
                self._decrypt(step, temp)
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

    def _byteswap(self, step, temp: Path) -> None:
        """Write the ROM in the native byte order; reading the result back and swapping it
        again must give the original's SHA1. Both passes stream, a chunk at a time."""
        word = step.word_bytes
        if not word:
            raise moves.MoveError(f"{step.source.name} is not a whole number of {word}-byte words")
        size = step.member_size if step.member is not None else step.source.stat().st_size
        try:
            with cards.open_payload(step.source, step.member) as source:
                if step.output_member is None:
                    with temp.open("xb") as out:
                        read = self._swap_copy(source, out, word)
                else:
                    now = datetime.now()
                    entry = zipfile.ZipInfo(
                        step.output_member,
                        (now.year, now.month, now.day, now.hour, now.minute, now.second),
                    )
                    entry.compress_type = zipfile.ZIP_DEFLATED
                    entry.compress_level = self.config.zip_compress_level
                    entry.file_size = size or 0
                    with (
                        zipfile.ZipFile(temp, "x", strict_timestamps=False) as z,
                        z.open(entry, "w") as out,
                    ):
                        read = self._swap_copy(source, out, word)
        except (zipfile.BadZipFile, KeyError) as exc:
            raise moves.MoveError(f"cannot read {step.member} from {step.source}") from exc
        if step.member is not None and (read.crc32, read.size) != (
            (step.member_crc32 or "").lower(),
            step.member_size,
        ):
            raise moves.MoveError(f"{step.member} is not the data the scan listed")
        if read.rest:
            raise moves.MoveError(f"{step.source.name} is not a whole number of {word}-byte words")
        try:
            if step.output_member is None:
                with temp.open("rb") as back:
                    again = self._swap_copy(back, None, word)
            else:
                with zipfile.ZipFile(temp) as z:
                    if z.namelist() != [step.output_member]:
                        raise moves.MoveError(f"the new file for {step.source.name} is unreadable")
                    with z.open(step.output_member) as back:
                        again = self._swap_copy(back, None, word)
        except (zipfile.BadZipFile, KeyError) as exc:
            raise moves.MoveError(f"the new file for {step.source.name} is unreadable") from exc
        if again.rest or again.swapped_sha1 != read.sha1:
            raise moves.MoveError(f"the rewritten {step.source.name} does not hold the same ROM")

    def _swap_copy(self, source, out, word: int) -> Swapped:
        """Stream `source` into `out` (None: nowhere) with each `word`-byte word reversed."""
        sha1 = hashlib.sha1(usedforsecurity=False)
        swapped_sha1 = hashlib.sha1(usedforsecurity=False)
        crc, size, rest = 0, 0, b""
        while block := source.read(self.config.copy_chunk_bytes):
            stopping.check()
            sha1.update(block)
            crc = zlib.crc32(block, crc)
            size += len(block)
            data = rest + block
            whole = len(data) - len(data) % word
            swapped = hashing.swap_words(data[:whole], word)
            swapped_sha1.update(swapped)
            if out is not None:
                out.write(swapped)
            rest = data[whole:]
        return Swapped(
            sha1.hexdigest(), swapped_sha1.hexdigest(), format(crc, CRC_FORMAT), size, rest
        )

    def _decrypt(self, step, temp: Path) -> None:
        """Decrypt the card image with the user's keys (from an archive: its one ROM, unpacked
        to a work folder first and checked against the listing); the result must match the
        hashes its partitions carry (`cards.prove_decrypted`)."""
        source = step.source
        work = moves.work_path(self.config, step.destination)
        try:
            if step.member is not None:
                try:
                    work.mkdir()
                except FileExistsError as exc:
                    raise moves.MoveError(
                        f"{work} already exists (left by an interrupted run?)"
                    ) from exc
                source = work / UNPACKED / PurePosixPath(step.member).name
                source.parent.mkdir()
                self.extract(self.settings, step.source, step.member, source)
                listed = ((step.member_crc32 or "").lower(), step.member_size)
                if crc_and_size(self.config.copy_chunk_bytes, source) != listed:
                    raise moves.MoveError(f"{step.member} did not extract as the archive lists it")
            config = self.settings.card_images.get(step.card_image or "")
            if config is None:
                raise moves.MoveError(f"no card image format to check {step.source.name} with")
            try:
                decrypt.decrypt_cci(self.settings, config, source, temp)
            except decrypt.DecryptError as exc:
                temp.unlink(missing_ok=True)
                raise moves.MoveError(str(exc)) from exc
            _drop_unpacked(work)
            name = Path(step.member or step.source.name).name
            try:
                cards.prove_decrypted(config, temp, stopping.check)
            except cards.ProofError as exc:
                if exc.damaged:
                    unit, unit_bytes = config.proof.report_unit, config.proof.report_unit_bytes
                    if (found := self._trailing_fill(step)) and found[0] <= exc.offset:
                        fill, value = found
                        raise moves.MoveError(
                            f"{name} is cut short: from about {max(1, fill // unit_bytes)} {unit}"
                            f" to its end it holds only {value:02x} bytes where data belongs"
                            f" (likely an incomplete copy or download; {exc}); nothing was"
                            " changed"
                        ) from exc
                    raise moves.MoveError(
                        f"{name} is damaged about {max(1, exc.offset // unit_bytes)} {unit} in:"
                        f" {exc}, though the keys proved right (likely a bad dump); nothing was"
                        " changed"
                    ) from exc
                raise moves.MoveError(
                    f"the decrypted {name} is not right ({exc}): nothing was changed"
                ) from exc
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _trailing_fill(self, step) -> tuple[int, int] | None:
        """`cards.trailing_fill` of the original, read again (an unpacked copy is gone): a
        file or a zip member. None for a 7z member, which 7-Zip streams only for a while."""
        if step.member is not None and step.source.suffix.lower() != conversion.ZIP_SUFFIX:
            return None
        try:
            with cards.open_payload(step.source, step.member) as stream:
                return cards.trailing_fill(stream, self.config.copy_chunk_bytes, stopping.check)
        except (OSError, zipfile.BadZipFile, KeyError) as exc:
            raise moves.MoveError(f"cannot read {step.source.name} again: {exc}") from exc

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
            if disc.suffix.lower().lstrip(".") == cso.CSO:
                disc = self._decode_cso(disc, work)
            sheet = disc.suffix.lower().lstrip(".") in discs.SHEETS
            originals = discs.sheet_paths(disc) if sheet else [disc]
            each, whole = self._digests(originals)
            if step.disc_mode == discs.RVZ:
                self._rvz(step, disc, whole, temp, work)
                return
            discs.create(chdman, step.disc_mode, disc, temp)
            # The checks below compare with the digests above: the unpacked copy goes now.
            _drop_unpacked(work)
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
        except (discs.DiscError, cso.CsoError) as exc:
            temp.unlink(missing_ok=True)
            raise moves.MoveError(str(exc)) from exc
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _decode_cso(self, source: Path, work: Path) -> Path:
        """The ISO a CSO holds, decoded into `work/source`; the CHD is made from it and
        checked against it."""
        if self.settings.cso is None:
            raise moves.MoveError("no cso settings: CSO images cannot be read")
        image = work / UNPACKED / f"{source.stem}.{discs.ISO}"
        image.parent.mkdir(parents=True, exist_ok=True)
        cso.decode(self.settings.cso, source, image)
        return image

    def _rvz(self, step, image: Path, sha1: str, temp: Path, work: Path) -> None:
        """dolphin-tool makes the RVZ; the disc it holds must have the image's SHA1."""
        dolphin = self.settings.dolphin
        user_dir = self.settings.paths.data_dir / dolphin.user_dir
        # dolphin-tool would replace an existing file: claim the temporary name first.
        temp.open("xb").close()
        discs.make_rvz(dolphin, user_dir, image, temp)
        _drop_unpacked(work)
        if discs.rvz_sha1(dolphin, user_dir, temp) != sha1:
            raise moves.MoveError(f"the RVZ of {step.source.name} does not hold the same disc")

    def _unpack(self, step, work: Path) -> Path:
        """Extract an archive's disc files to `work/source`, each checked against the CRC32
        and size the scan listed; return the cue sheet or ISO among them."""
        source = work / UNPACKED
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
            if relative.suffix.lower().lstrip(".") in (*discs.SHEETS, *discs.IMAGES):
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
                    stopping.check()
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
