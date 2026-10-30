"""Running igir as an external program and reading its report.

igir does the format work (archives, CHD tracks, RVZ) and the checksum matching against a
DAT; we only read which input file it found as which DAT game.
"""

import csv
import fcntl
import os
import pty
import select
import shlex
import struct
import subprocess
import tempfile
import termios
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from g1r.config import Settings
from g1r.terminal import Screen, Segment

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
    drawn: Callable[[list[list[Segment]], bool], None] | None = None,
) -> list[ReportRow]:
    """`cache`: igir's cache file (`cache_path`). `merge`: igir's --merge-roms mode, for
    arcade sets. `threads`: files read at once and Node's worker pool size (None: igir's
    own). `excess`: an archive holding other files besides the game's ROMs still matches.
    `files`: only these files of `input_dir`, by exact path (igir takes an existing path as
    it is, so brackets in ROM names need no escaping; checked with igir 5.8.0). Its cache
    is keyed by path, so a file read in a run over the whole folder is not read again.
    `started`: told the command (`shown_command`) just before igir starts; `drawn`: igir's
    screen as it draws it (`_run`)."""
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
        if started is not None:
            started(shown_command(program, options, pool))
        lines, returncode = _run(settings, command, pool, timeout, drawn)
        if returncode != 0 or not report.is_file():
            tail = [line for line in lines if line.strip()][-1:]
            raise IgirError(f"igir failed ({returncode}): {' '.join(tail)}")
        return parse_report(report)


def _run(
    settings: Settings,
    command: list[str],
    env: dict[str, str],
    timeout: float,
    drawn: Callable[[list[list[Segment]], bool], None] | None,
) -> tuple[list[str], int]:
    """Runs igir on a pseudo-terminal (it draws its progress bars only on one), handing the
    screen it draws to `drawn` on this thread each time it changes, and once more with
    `True` when igir is done; killed after `timeout` seconds. Its screen as text, and its
    exit code."""
    config = settings.igir.terminal
    master, slave = pty.openpty()
    size = struct.pack("HHHH", config.rows, config.columns, 0, 0)
    fcntl.ioctl(slave, termios.TIOCSWINSZ, size)
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=slave,
            stderr=slave,
            env={**os.environ, **config.env, **env},
        )
    except OSError as exc:
        os.close(master)
        raise IgirError(f"could not run igir: {exc}") from exc
    finally:
        os.close(slave)
    screen = Screen(config)
    deadline = time.monotonic() + timeout
    shown: list[list[Segment]] | None = None
    try:
        while (left := deadline - time.monotonic()) > 0:
            if not select.select([master], [], [], left)[0]:
                continue
            try:
                data = os.read(master, config.read_bytes)
            except OSError:  # every end of the terminal on igir's side is closed
                data = b""
            if not data:
                break
            screen.feed(data)
            if drawn is not None and screen.drawn and (lines := screen.lines()) != shown:
                drawn(lines, False)
                shown = lines
        returncode = process.wait(max(deadline - time.monotonic(), 0))
    except subprocess.TimeoutExpired:
        returncode = None
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        os.close(master)
        if drawn is not None:
            drawn(screen.lines(), True)
    if returncode is None:
        raise IgirError(f"could not run igir: timed out after {timeout:g} seconds")
    return screen.text(), returncode
