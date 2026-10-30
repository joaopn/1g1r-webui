"""Running igir as an external program and reading its report.

igir does the format work (archives, CHD tracks, RVZ) and the checksum matching against a
DAT; we only read which input file it found as which DAT game.
"""

import csv
import os
import shlex
import subprocess
import tempfile
import threading
from collections.abc import Callable
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


def shown_command(program: list[str], options: list[str], env: dict[str, str]) -> str:
    """A command as a shell would run it: `env` first, then the program (and subcommand),
    then each option with its values on a continued line of its own."""
    first = [*(f"{k}={shlex.quote(v)}" for k, v in env.items()), *map(shlex.quote, program)]
    lines: list[list[str]] = [first]
    for arg in options:
        if arg.startswith("--") or len(lines) == 1:
            lines.append([])
        lines[-1].append(shlex.quote(arg))
    return " \\\n  ".join(" ".join(line) for line in lines)


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
    files: list[Path] | None = None,
    started: Callable[[str], None] | None = None,
    printed: Callable[[str], None] | None = None,
) -> list[ReportRow]:
    """`cache`: igir's cache file (`cache_path`). `merge`: igir's --merge-roms mode, for
    arcade sets. `threads`: files read at once and Node's worker pool size (None: igir's
    own). `excess`: an archive holding other files besides the game's ROMs still matches.
    `files`: only these files of `input_dir`, by exact path (igir takes an existing path as
    it is, so brackets in ROM names need no escaping; checked with igir 5.8.0). Its cache
    is keyed by path, so a file read in a run over the whole folder is not read again.
    `started`: told the command (`shown_command`) just before igir starts; `printed`: each
    line igir prints, as it prints it (without a terminal: its banner, then a line per step
    as the step ends)."""
    work = settings.paths.data_dir / settings.igir.work_dir
    work.mkdir(parents=True, exist_ok=True)
    cache.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=work) as tmp:
        report = Path(tmp) / "report.csv"
        program = [settings.igir.binary, "report"]
        options = [
            "--dat",
            str(dat_file),
            *[arg for path in files or [input_dir] for arg in ("--input", str(path))],
            "--cache-path",
            str(cache),
            "--report-output",
            str(report),
            *(["--merge-roms", merge] if merge else []),
            *(["--reader-threads", str(threads)] if threads else []),
            *(["--allow-excess-sets"] if excess else []),
        ]
        command = [*program, *options]
        pool = {POOL_SIZE_ENV: str(threads)} if threads else {}
        env = {**os.environ, **pool} if pool else None
        if started is not None:
            started(shown_command(program, options, pool))
        lines, returncode = _run(command, env, timeout, printed)
        if returncode != 0 or not report.is_file():
            tail = [line for line in lines if line.strip()][-1:]
            raise IgirError(f"igir failed ({returncode}): {' '.join(tail)}")
        return parse_report(report)


def _run(
    command: list[str],
    env: dict[str, str] | None,
    timeout: float,
    printed: Callable[[str], None] | None,
) -> tuple[list[str], int]:
    """Runs igir, handing each line of its output (both streams) to `printed` on this thread
    as it comes; killed after `timeout` seconds. Its lines and exit code."""
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            env=env,
        )
    except OSError as exc:
        raise IgirError(f"could not run igir: {exc}") from exc
    timed_out = threading.Event()

    def stop() -> None:
        timed_out.set()
        process.kill()

    timer = threading.Timer(timeout, stop)
    timer.start()
    lines = []
    try:
        for raw in process.stdout or []:
            line = raw.rstrip("\n")
            lines.append(line)
            if printed is not None:
                printed(line)
        returncode = process.wait()
    finally:
        timer.cancel()
        if process.poll() is None:
            process.kill()
            process.wait()
    if timed_out.is_set():
        raise IgirError(f"could not run igir: timed out after {timeout:g} seconds")
    return lines, returncode
