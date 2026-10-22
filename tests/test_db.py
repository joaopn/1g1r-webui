import sqlite3

import pytest

from g1r import db


def test_migrations_are_numbered_without_gaps():
    numbers = [number for number, _, _ in db.migrations()]
    assert numbers == list(range(1, len(numbers) + 1))


def test_migrate_applies_once_and_is_idempotent(tmp_path):
    conn = db.connect(tmp_path / "state.db", busy_timeout_ms=0)
    latest = len(db.migrations())
    assert db.migrate(conn) == latest
    assert db.migrate(conn) == latest
    assert conn.execute("SELECT value FROM app_meta WHERE key = 'created_at'").fetchone()


def test_newer_database_is_refused(tmp_path):
    conn = db.connect(tmp_path / "state.db", busy_timeout_ms=0)
    conn.execute(f"PRAGMA user_version = {len(db.migrations()) + 1}")
    with pytest.raises(db.MigrationError, match="newer"):
        db.migrate(conn)


def test_failed_migration_rolls_back(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "state.db", busy_timeout_ms=0)
    broken = [(1, "0001_broken.sql", "CREATE TABLE t (x); INSERT INTO nope VALUES (1);")]
    monkeypatch.setattr(db, "migrations", lambda: broken)
    with pytest.raises(db.MigrationError, match="0001_broken"):
        db.migrate(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("SELECT * FROM t")


def test_every_write_to_a_folder_s_data_moves_its_change_counter(tmp_path):
    conn = db.connect(tmp_path / "state.db", busy_timeout_ms=0)
    db.migrate(conn)
    tables = [
        name
        for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        if "folder_label" in {row["name"] for row in conn.execute(f"PRAGMA table_info({name})")}
        and name != "folder_change"
    ]
    triggers = {
        (row["tbl_name"], row["name"].rsplit("_", 1)[-1])
        for row in conn.execute("SELECT name, tbl_name FROM sqlite_master WHERE type = 'trigger'")
    }
    for table in [*tables, "dat_version"]:
        for event in ("insert", "update", "delete"):
            assert (table, event) in triggers, f"{table} has no {event} trigger"

    def counter(label):
        row = conn.execute(
            "SELECT n FROM folder_change WHERE folder_label = ?", (label,)
        ).fetchone()
        return row["n"] if row else None

    conn.execute("INSERT INTO scan (folder_label, status) VALUES ('nes', 'running')")
    first = counter("nes")
    conn.execute("UPDATE scan SET status = 'done'")
    assert counter("nes") > first
    assert counter("gb") is None
