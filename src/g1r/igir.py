"""Running igir as an external program and reading its report.

igir does the format work (archives, CHD tracks, RVZ) and the checksum matching against a
DAT; we only read which input file it found as which DAT game.
"""

import csv
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from g1r.config import Settings

# Node's worker pool (file reads, CHD decoding in igir's chdman library).
POOL_SIZE_ENV = "UV_THREADPOOL_SIZE"


class IgirError(RuntimeError):
    """igir could not be run or its report could not be read."""


@dataclass(frozen=True)
class ReportRow:
    game_name: str
    status: str
    files: tuple[str, ...]


def parse_report(path: Path) -> list[ReportRow]:
    rows = []
    with path.open(newline="", encoding="utf-8") as handle:
        for record in csv.DictReader(handle):
            files = tuple(f for f in (record.get("ROM Files") or "").split("|") if f)
            rows.append(ReportRow(record.get("Game Name") or "", record.get("Status") or "", files))
    return rows


def identified_files(rows: list[ReportRow]) -> dict[str, set[str]]:
    """Absolute input path -> the DAT game names igir found it as."""
    found: dict[str, set[str]] = {}
    for row in rows:
        if not row.game_name or not row.files:
            continue
        for path in row.files:
            found.setdefault(path, set()).add(row.game_name)
    return found


def cache_path(settings: Settings, label: str) -> Path:
    """The folder's igir cache: a full scan deletes it, so igir hashes every file again."""
    return settings.paths.data_dir / settings.igir.cache_dir / f"{label}.cache"


def time_limit(settings: Settings, size_bytes: int) -> float:
    """How long one igir run over a folder of this size may take, at most
    `max_timeout_seconds` (subprocess cannot wait longer than about 24.8 days)."""
    config = settings.igir
    limit = config.timeout_seconds + size_bytes / config.min_bytes_per_second
    return min(limit, config.max_timeout_seconds)


def run_report(
    settings: Settings,
    dat_file: Path,
    input_dir: Path,
    *,
    cache: Path,
    timeout: float,
    merge: str | None = None,
    threads: int | None = None,
    excess: bool = False,
) -> list[ReportRow]:
    """`cache`: igir's cache file (`cache_path`). `merge`: igir's --merge-roms mode, for
    arcade sets. `threads`: files read at once and Node's worker pool size (None: igir's
    own). `excess`: an archive holding other files besides the game's ROMs still matches."""
    work = settings.paths.data_dir / settings.igir.work_dir
    work.mkdir(parents=True, exist_ok=True)
    cache.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=work) as tmp:
        report = Path(tmp) / "report.csv"
        command = [
            settings.igir.binary,
            "report",
            "--dat",
            str(dat_file),
            "--input",
            str(input_dir),
            "--cache-path",
            str(cache),
            "--report-output",
            str(report),
            *(["--merge-roms", merge] if merge else []),
            *(["--reader-threads", str(threads)] if threads else []),
            *(["--allow-excess-sets"] if excess else []),
        ]
        env = {**os.environ, POOL_SIZE_ENV: str(threads)} if threads else None
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=timeout, env=env
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise IgirError(f"could not run igir: {exc}") from exc
        if result.returncode != 0 or not report.is_file():
            tail = (result.stderr or result.stdout).strip().splitlines()[-1:]
            raise IgirError(f"igir failed ({result.returncode}): {' '.join(tail)}")
        return parse_report(report)
