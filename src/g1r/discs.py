"""Disc images: reading cue sheets, the chdman runs that make and check a CHD, and the
dolphin-tool runs that make and check an RVZ.

A cue sheet names the files holding the disc's tracks (`FILE "name" BINARY`), and so does a
Dreamcast .gdi (one line per track: number, start, type, sector size, file, offset). chdman
makes the CHD from either sheet (or from an ISO, a single data track), checks the CHD's own
hashes (`verify`), and gives the tracks back (`extractcd`), so a conversion is proven
lossless by comparing those tracks with the originals.
"""

import re
import subprocess
from pathlib import Path, PurePosixPath

from g1r.config import ChdmanConfig, DolphinConfig

CUE = "cue"
GDI = "gdi"
# Track lists a disc is converted from, with its track files.
SHEETS = (CUE, GDI)
ISO = "iso"
GCM = "gcm"
# Single-file disc images a CHD or RVZ is made from.
IMAGES = (ISO, GCM)
# chdman's modes for making a CHD.
CREATECD = "createcd"
CREATEDVD = "createdvd"
# dolphin-tool convert, for GameCube and Wii.
RVZ = "rvz"

_SHA1_LINE = re.compile(r"^[0-9a-f]{40}$")
# The extracted copy's names inside a work directory; %t is chdman's track number.
EXTRACTED_CUE = "disc.cue"
EXTRACTED_TRACKS = "track%t.bin"

_FILE_LINE = re.compile(r'^\s*FILE\s+(?:"(?P<quoted>[^"]+)"|(?P<bare>\S+))\s+\S+\s*$', re.I)


# A .gdi track line; the file name is quoted when it has spaces.
_GDI_LINE = re.compile(
    r'^\s*\d+\s+\d+\s+\d+\s+\d+\s+(?:"(?P<quoted>[^"]+)"|(?P<bare>\S+))\s+-?\d+\s*$'
)


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


def gdi_files(text: str) -> list[str]:
    """The track file names a .gdi refers to, in order (the first line is the count)."""
    names = []
    for line in text.splitlines():
        match = _GDI_LINE.match(line)
        if match:
            names.append(match.group("quoted") or match.group("bare"))
    return names


def read_sheet(path: Path) -> list[str]:
    """The track file names of a cue sheet or a .gdi."""
    read = gdi_files if path.suffix.lower().lstrip(".") == GDI else cue_files
    try:
        return read(path.read_text(encoding="utf-8", errors="replace"))
    except OSError as exc:
        raise DiscError(f"cannot read {path.name}: {exc.strerror}") from exc


def sheet_paths(cue: Path) -> list[Path]:
    """The track files of a cue sheet or .gdi, beside it; raises when one is missing or
    outside."""
    paths = []
    for name in read_sheet(cue):
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


def _run(config: ChdmanConfig | DolphinConfig, args: list[str]) -> str:
    tool = Path(config.binary).name
    try:
        result = subprocess.run(
            [config.binary, *args],
            capture_output=True,
            text=True,
            timeout=config.timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DiscError(f"{tool} could not run: {exc}") from exc
    if result.returncode != 0:
        lines = (result.stderr or result.stdout).strip().splitlines()
        raise DiscError(f"{tool} {args[0]} failed: {lines[-1] if lines else result.returncode}")
    return result.stdout


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
    return sheet_paths(cue)


def extract_dvd(config: ChdmanConfig, chd: Path, output: Path) -> None:
    _run(config, ["extractdvd", "-i", str(chd), "-o", str(output)])


def make_rvz(config: DolphinConfig, user_dir: Path, image: Path, output: Path) -> None:
    """dolphin-tool replaces an existing output, so the caller claims `output` first."""
    user_dir.mkdir(parents=True, exist_ok=True)
    _run(
        config,
        ["convert", "-u", str(user_dir), "-i", str(image), "-o", str(output), *config.convert_args],
    )


def rvz_sha1(config: DolphinConfig, user_dir: Path, rvz: Path) -> str:
    """The SHA1 of the disc an RVZ holds (that of the ISO it was made from)."""
    out = _run(config, ["verify", "-u", str(user_dir), "-i", str(rvz), "-a", "sha1"])
    found = [line.strip() for line in out.splitlines() if _SHA1_LINE.match(line.strip())]
    if not found:
        raise DiscError("dolphin-tool verify gave no SHA1")
    return found[-1]
