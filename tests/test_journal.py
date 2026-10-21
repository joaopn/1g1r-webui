import errno
import os
from http import HTTPStatus
from pathlib import Path

import pytest

from g1r import db, journal, moves
from g1r.config import ApplyConfig

from .test_api import scanned, setup  # noqa: F401  (fixture)

CONFIG = ApplyConfig(
    copy_chunk_bytes=4,
    temp_suffix=".part",
    zip_compress_level=6,
    extract_timeout_seconds=5,
    work_suffix=".work",
    stop_poll_seconds=0.05,
)


# The move engine ------------------------------------------------------------------


def test_move_same_disk_keeps_content_and_never_overwrites(tmp_path):
    src = tmp_path / "a" / "x.zip"
    src.parent.mkdir()
    src.write_bytes(b"0123456789")
    dst = tmp_path / "d" / "sub" / "x.zip"
    moves.move(CONFIG, src, dst)
    assert not src.exists() and dst.read_bytes() == b"0123456789"

    src.write_bytes(b"new")
    with pytest.raises(moves.MoveError, match="already exists"):
        moves.move(CONFIG, src, dst)
    assert src.read_bytes() == b"new" and dst.read_bytes() == b"0123456789"


def test_move_to_another_disk_copies_verifies_and_cleans_up(tmp_path, monkeypatch):
    monkeypatch.setattr(moves, "same_device", lambda a, b: False)
    src = tmp_path / "x.bin"
    src.write_bytes(b"abcdefghij")
    os.utime(src, ns=(1_000_000_000, 1_000_000_000))
    dst = tmp_path / "other" / "x.bin"
    moved = moves.move(CONFIG, src, dst)
    assert not src.exists() and dst.read_bytes() == b"abcdefghij"
    assert moved.st_mtime_ns == 1_000_000_000
    assert not moves.temp_path(CONFIG, dst).exists()


def test_a_bad_copy_leaves_the_source(tmp_path, monkeypatch):
    monkeypatch.setattr(moves, "same_device", lambda a, b: False)
    monkeypatch.setattr(moves, "sha1_of", lambda config, path: "different")
    src = tmp_path / "x.bin"
    src.write_bytes(b"abc")
    dst = tmp_path / "other" / "x.bin"
    with pytest.raises(moves.MoveError, match="does not match"):
        moves.move(CONFIG, src, dst)
    assert src.read_bytes() == b"abc" and not dst.exists()
    assert not moves.temp_path(CONFIG, dst).exists()


def test_without_hard_links_it_renames(tmp_path, monkeypatch):
    def no_link(a, b):
        raise OSError(errno.EPERM, "not permitted")

    monkeypatch.setattr(os, "link", no_link)
    src = tmp_path / "x.bin"
    src.write_bytes(b"abc")
    moves.move(CONFIG, src, tmp_path / "d" / "x.bin")
    assert (tmp_path / "d" / "x.bin").read_bytes() == b"abc"


# Apply and restore through the API --------------------------------------------------


def wait_run(client, label="nes"):
    for _ in range(500):
        run = client.get(f"/api/folders/{label}/run").json()
        if run and run["status"] != journal.RUNNING:
            return run
    raise AssertionError("run did not finish")


def versions(client):
    return {
        v["rel_path"]: v for g in client.get("/api/folders/nes/games").json() for v in g["versions"]
    }


def test_apply_and_restore_a_folder(setup, roms_root):  # noqa: F811
    client, _, _ = setup
    scanned(client)
    folder = roms_root / "NES Set"
    preview = client.post("/api/folders/nes/apply/preview", json={}).json()
    assert [m["rel_path"] for m in preview["moves"]] == ["Contra (Japan).zip"]
    assert preview["problems"] == [] and preview["busy"] is None

    stale = client.post("/api/folders/nes/apply", json={"token": "nope"})
    assert stale.status_code == HTTPStatus.CONFLICT
    assert "changed since you reviewed" in stale.json()["detail"]["message"]
    assert (folder / "Contra (Japan).zip").exists()

    started = client.post("/api/folders/nes/apply", json={"token": preview["token"]})
    assert started.status_code == HTTPStatus.ACCEPTED
    run = wait_run(client)
    assert (run["status"], run["message"]) == ("done", "1 file moved to discarded/")
    moved = roms_root / "discarded" / "nes" / "1g1r" / "Contra (Japan).zip"
    assert moved.exists() and not (folder / "Contra (Japan).zip").exists()

    contra = next(g for g in client.get("/api/folders/nes/games").json() if g["name"] == "Contra")
    assert contra["status"] == "applied"
    gone = next(v for v in contra["versions"] if v["rel_path"] == "Contra (Japan).zip")
    assert gone["discarded"] and gone["operation"] is None
    # 6 ROM files were scanned (5 zips and odd.nes); one is now in discarded/.
    assert client.get("/api/folders/nes").json()["summary"]["roms"] == 5
    listing = client.get("/api/folders/nes/discarded").json()
    assert listing["reasons"][0]["files"][0]["operation_id"] == gone["discarded"]

    # A rescan keeps the discarded version in the table.
    assert client.post("/api/folders/nes/scan").status_code == HTTPStatus.ACCEPTED
    for _ in range(500):
        if client.get("/api/folders/nes/scan").json()["status"] != "running":
            break
    assert versions(client)["Contra (Japan).zip"]["discarded"] == gone["discarded"]
    assert client.post("/api/folders/nes/apply/preview", json={}).json()["moves"] == []

    restored = client.post("/api/folders/nes/restore", json={"group_key": contra["key"]})
    assert restored.status_code == HTTPStatus.ACCEPTED
    assert wait_run(client)["message"] == "1 file restored"
    assert (folder / "Contra (Japan).zip").exists() and not moved.exists()
    assert versions(client)["Contra (Japan).zip"]["discarded"] is None
    again = client.post("/api/folders/nes/apply/preview", json={}).json()
    assert [m["rel_path"] for m in again["moves"]] == ["Contra (Japan).zip"]


def test_preflight_refuses_changed_files_and_taken_places(setup, roms_root):  # noqa: F811
    client, _, _ = setup
    scanned(client)
    source = roms_root / "NES Set" / "Contra (Japan).zip"
    source.write_bytes(b"changed after the scan")
    preview = client.post("/api/folders/nes/apply/preview", json={}).json()
    assert "changed since it was scanned" in preview["problems"][0]["problem"]
    refused = client.post("/api/folders/nes/apply", json={"token": preview["token"]})
    assert refused.status_code == HTTPStatus.CONFLICT
    assert refused.json()["detail"]["problems"][0]["rel_path"] == "Contra (Japan).zip"
    assert source.exists()

    scanned_again = client.post("/api/folders/nes/scan")
    assert scanned_again.status_code == HTTPStatus.ACCEPTED
    for _ in range(500):
        if client.get("/api/folders/nes/scan").json()["status"] != "running":
            break
    taken = roms_root / "discarded" / "nes" / "1g1r" / "Contra (Japan).zip"
    taken.parent.mkdir(parents=True)
    taken.write_bytes(b"someone else's")
    preview = client.post("/api/folders/nes/apply/preview", json={}).json()
    assert "already exists" in preview["problems"][0]["problem"]


def test_per_game_apply_moves_only_that_game(setup, roms_root):  # noqa: F811
    client, _, _ = setup
    scanned(client)
    # Tick Gradius (USA) so the undecided Gradius group proposes a move too.
    gradius = next(g for g in client.get("/api/folders/nes/games").json() if g["name"] == "Gradius")
    client.put(
        "/api/folders/nes/keep", json={"group_key": gradius["key"], "rel_path": "Gradius (USA).zip"}
    )
    whole = client.post("/api/folders/nes/apply/preview", json={}).json()
    assert len(whole["moves"]) == 1 + 1
    one = client.post("/api/folders/nes/apply/preview", json={"group_key": gradius["key"]}).json()
    assert [m["rel_path"] for m in one["moves"]] == ["Gradius (USA) (Rev 1).zip"]
    client.post("/api/folders/nes/apply", json={"group_key": gradius["key"], "token": one["token"]})
    wait_run(client)
    assert (roms_root / "NES Set" / "Contra (Japan).zip").exists()
    assert not (roms_root / "NES Set" / "Gradius (USA) (Rev 1).zip").exists()


# Start-up recovery ----------------------------------------------------------------


def _started(conn, run_id, source: Path, destination: Path):
    stat = source.stat() if source.exists() else destination.stat()
    return conn.execute(
        "INSERT INTO operation (run_id, folder_label, rel_path, reason, source, destination, "
        "size, mtime_ns, state) VALUES (?, 'f', ?, '1g1r', ?, ?, ?, ?, 'started')",
        (run_id, source.name, str(source), str(destination), stat.st_size, stat.st_mtime_ns),
    ).lastrowid


def test_recovery_settles_interrupted_moves(tmp_path):
    conn = db.connect(tmp_path / "state.db", 1000)
    db.migrate(conn)
    run_id = journal.start_run(conn, "f", journal.APPLY, "", 1 + 1 + 1 + 1)
    folder, gone = tmp_path / "folder", tmp_path / "discarded"
    folder.mkdir()
    gone.mkdir()

    (folder / "untouched.zip").write_bytes(b"a")
    untouched = _started(conn, run_id, folder / "untouched.zip", gone / "untouched.zip")
    (gone / "finished.zip").write_bytes(b"b")
    finished = _started(conn, run_id, folder / "finished.zip", gone / "finished.zip")
    (folder / "linked.zip").write_bytes(b"c")
    os.link(folder / "linked.zip", gone / "linked.zip")
    linked = _started(conn, run_id, folder / "linked.zip", gone / "linked.zip")
    (folder / "both.zip").write_bytes(b"d")
    (gone / "both.zip").write_bytes(b"different")
    both = _started(conn, run_id, folder / "both.zip", gone / "both.zip")
    (gone / ("untouched.zip" + CONFIG.temp_suffix)).write_bytes(b"partial")

    assert journal.recover(CONFIG, conn) == 1 + 1 + 1 + 1
    state = dict(conn.execute("SELECT id, state FROM operation").fetchall())
    assert state[untouched] == "failed" and (folder / "untouched.zip").exists()
    assert state[finished] == "done"
    assert state[linked] == "done" and not (folder / "linked.zip").exists()
    assert state[both] == "failed"
    assert (folder / "both.zip").exists() and (gone / "both.zip").exists()
    assert not (gone / ("untouched.zip" + CONFIG.temp_suffix)).exists()
    run = conn.execute("SELECT status, message FROM apply_run").fetchone()
    assert run["status"] == "failed" and "restart" in run["message"]


def test_running_conversion_counts_finished_steps_and_failed_files(tmp_path):
    conn = db.connect(tmp_path / "state.db", 1000)
    db.migrate(conn)
    assert journal.running_conversion(conn, "f") is None
    moves_run = journal.start_run(conn, "f", journal.APPLY, "", 1)
    assert journal.running_conversion(conn, "f") is None  # a 1G1R apply is not a conversion
    conn.execute("UPDATE apply_run SET status = 'done' WHERE id = ?", (moves_run,))
    run_id = journal.start_run(conn, "f", journal.APPLY, journal.CONVERT, 1 + 1 + 1 + 1)
    for state, action in (
        ("done", journal.CONVERT),
        ("done", journal.DELETE),
        ("failed", journal.CONVERT),
        ("started", journal.CONVERT),
    ):
        conn.execute(
            "INSERT INTO operation (run_id, folder_label, rel_path, reason, source, "
            "destination, size, mtime_ns, state, action) "
            "VALUES (?, 'f', 'a.iso', 'convert', 'a', 'b', 1, 1, ?, ?)",
            (run_id, state, action),
        )
    assert journal.running_conversion(conn, "f") == {
        "done": 1 + 1 + 1,
        "total": 1 + 1 + 1 + 1,
        "failed": 1,
        "stopping": False,
    }
    assert journal.running_conversion(conn, "other") is None
    conn.execute("UPDATE apply_run SET status = 'failed' WHERE id = ?", (run_id,))
    assert journal.running_conversion(conn, "f") is None
