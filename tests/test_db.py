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
