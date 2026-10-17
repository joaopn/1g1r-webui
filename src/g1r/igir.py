"""Running igir as an external program and reading its report.

igir does the format work (archives, CHD tracks, RVZ) and the checksum matching against a
DAT; we only read which input file it found as which DAT game.
"""

import csv
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from g1r.config import Settings


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


def run_report(
    settings: Settings, dat_file: Path, input_dir: Path, merge: str | None = None
) -> list[ReportRow]:
    """`merge`: igir's --merge-roms mode, for arcade sets."""
    data_dir = settings.paths.data_dir
    work = data_dir / settings.igir.work_dir
    work.mkdir(parents=True, exist_ok=True)
    cache = data_dir / settings.igir.cache_file
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
        ]
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=settings.igir.timeout_seconds
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise IgirError(f"could not run igir: {exc}") from exc
        if result.returncode != 0 or not report.is_file():
            tail = (result.stderr or result.stdout).strip().splitlines()[-1:]
            raise IgirError(f"igir failed ({result.returncode}): {' '.join(tail)}")
        return parse_report(report)
