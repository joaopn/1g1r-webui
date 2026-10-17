"""Disc images: reading cue sheets, and the chdman runs that make and check a CHD.

A cue sheet names the files holding the disc's tracks (`FILE "name" BINARY`). chdman makes
the CHD from the cue sheet (or from an ISO, a single data track), checks the CHD's own
hashes (`verify`), and gives the tracks back (`extractcd`), so a conversion is proven
lossless by comparing those tracks with the originals.
"""

import re
import subprocess
from pathlib import Path, PurePosixPath

from g1r.config import ChdmanConfig

CUE = "cue"
ISO = "iso"
# chdman's modes for making a CHD.
CREATECD = "createcd"
CREATEDVD = "createdvd"
# The extracted copy's names inside a work directory; %t is chdman's track number.
EXTRACTED_CUE = "disc.cue"
EXTRACTED_TRACKS = "track%t.bin"

_FILE_LINE = re.compile(r'^\s*FILE\s+(?:"(?P<quoted>[^"]+)"|(?P<bare>\S+))\s+\S+\s*$', re.I)


class DiscError(RuntimeError):
    """chdman failed, or the cue sheet cannot be used; the message says why."""


def cue_files(text: str) -> list[str]:
    """The file names a cue sheet refers to, in order."""
    names = []
    for line in text.splitlines():
        match = _FILE_LINE.match(line)
        if match:
            names.append(match.group("quoted") or match.group("bare"))
    return names


def read_cue(path: Path) -> list[str]:
    try:
        return cue_files(path.read_text(encoding="utf-8", errors="replace"))
    except OSError as exc:
        raise DiscError(f"cannot read {path.name}: {exc.strerror}") from exc


def cue_paths(cue: Path) -> list[Path]:
    """The track files of a cue sheet, beside it; raises when one is missing or outside."""
    paths = []
    for name in read_cue(cue):
        relative = PurePosixPath(name.replace("\\", "/"))
        if relative.is_absolute() or ".." in relative.parts:
            raise DiscError(f"{cue.name} refers to {name}, outside its folder")
        path = cue.parent / relative
        if not path.is_file():
            raise DiscError(f"{cue.name} refers to {name}, which is missing")
        paths.append(path)
    if not paths:
        raise DiscError(f"{cue.name} names no track files")
    return paths


def _run(config: ChdmanConfig, args: list[str]) -> None:
    try:
        result = subprocess.run(
            [config.binary, *args],
            capture_output=True,
            text=True,
            timeout=config.timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DiscError(f"chdman could not run: {exc}") from exc
    if result.returncode != 0:
        lines = (result.stderr or result.stdout).strip().splitlines()
        raise DiscError(f"chdman {args[0]} failed: {lines[-1] if lines else result.returncode}")


def create(config: ChdmanConfig, mode: str, source: Path, output: Path) -> None:
    """`createcd` or `createdvd`; chdman refuses an existing output, so nothing is replaced."""
    _run(config, [mode, "-i", str(source), "-o", str(output), *config.create_args])


def verify(config: ChdmanConfig, chd: Path) -> None:
    _run(config, ["verify", "-i", str(chd)])


def extract_cd(config: ChdmanConfig, chd: Path, work: Path) -> list[Path]:
    """The CHD's tracks as files in `work`, in disc order."""
    cue = work / EXTRACTED_CUE
    _run(
        config,
        [
            "extractcd",
            "-i",
            str(chd),
            "-o",
            str(cue),
            "-ob",
            str(work / EXTRACTED_TRACKS),
            "--splitbin",
        ],
    )
    return cue_paths(cue)


def extract_dvd(config: ChdmanConfig, chd: Path, output: Path) -> None:
    _run(config, ["extractdvd", "-i", str(chd), "-o", str(output)])
