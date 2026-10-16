"""SQLite access and schema migrations.

Migrations are the numbered files in g1r/migrations (`NNNN_name.sql`). The number of the
last applied one is kept in `PRAGMA user_version`; each newer file runs once, in order,
inside its own transaction.
"""

import re
import sqlite3
from importlib import resources
from pathlib import Path

from g1r.config import Settings

_MIGRATION_NAME = re.compile(r"^(?P<number>\d+)_[a-z0-9_]+\.sql$")


class MigrationError(RuntimeError):
    """The migration files are inconsistent with each other or with the database."""


def migrations() -> list[tuple[int, str, str]]:
    """All migrations as (number, file name, SQL), sorted by number."""
    found = []
    for entry in resources.files("g1r").joinpath("migrations").iterdir():
        match = _MIGRATION_NAME.match(entry.name)
        if match:
            found.append((int(match["number"]), entry.name, entry.read_text(encoding="utf-8")))
    found.sort()
    numbers = [number for number, _, _ in found]
    if numbers != list(range(1, len(numbers) + 1)):
        raise MigrationError(f"migration numbers must run 1..n without gaps, found {numbers}")
    return found


def connect(path: Path, busy_timeout_ms: int) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def migrate(conn: sqlite3.Connection) -> int:
    """Apply every pending migration; return the schema version afterwards."""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    available = migrations()
    if current > len(available):
        raise MigrationError(
            f"database schema version {current} is newer than this build ({len(available)})"
        )
    for number, name, sql in available:
        if number <= current:
            continue
        try:
            conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {number};\nCOMMIT;")
        except sqlite3.Error as exc:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise MigrationError(f"migration {name} failed: {exc}") from exc
        current = number
    return current


def open_database(settings: Settings) -> sqlite3.Connection:
    conn = connect(settings.paths.database_path, settings.database.busy_timeout_ms)
    migrate(conn)
    return conn
