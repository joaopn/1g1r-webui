import zipfile
from http import HTTPStatus
from pathlib import Path

from g1r import db, journal

from .test_api import scanned, setup  # noqa: F401  (fixture)
from .test_dvds import proposals
from .test_journal import CONFIG, versions, wait_run

MANUAL = Path("discarded") / "nes" / "manual"


def unmatched(client):
    return [f["rel_path"] for f in client.get("/api/folders/nes/unmatched").json()]


def preview(client, path, **body):
    return client.post(f"/api/folders/nes/{path}/preview", json=body).json()


# Unmatched content ------------------------------------------------------------------


def test_move_unmatched_to_discarded_and_back(setup, roms_root):  # noqa: F811
    client, _, _ = setup
    scanned(client)
    assert unmatched(client) == ["odd.nes"]
    plan = preview(client, "unmatched", rel_paths=["odd.nes"])
    assert plan["irreversible"] == 0 and plan["problems"] == []
    assert plan["files"][0]["destination"] == str(roms_root / MANUAL / "odd.nes")

    body = {"rel_paths": ["odd.nes"], "token": plan["token"]}
    assert client.post("/api/folders/nes/unmatched", json=body).status_code == HTTPStatus.ACCEPTED
    assert wait_run(client)["message"] == "1 file moved to discarded/"
    assert (roms_root / MANUAL / "odd.nes").exists() and unmatched(client) == []

    listing = client.get("/api/folders/nes/discarded").json()
    moved = listing["reasons"][0]
    assert moved["id"] == "manual" and moved["files"][0]["operation_id"]
    client.post(
        "/api/folders/nes/restore", json={"operation_ids": [moved["files"][0]["operation_id"]]}
    )
    assert wait_run(client)["message"] == "1 file restored"
    assert unmatched(client) == ["odd.nes"]


def test_deleting_unmatched_needs_the_typed_label(setup, roms_root):  # noqa: F811
    client, _, _ = setup
    scanned(client)
    plan = preview(client, "unmatched", rel_paths=["odd.nes"], delete=True)
    assert plan["irreversible"] == 1 and plan["files"][0]["destination"] is None
    body = {"rel_paths": ["odd.nes"], "delete": True, "token": plan["token"]}
    refused = client.post("/api/folders/nes/unmatched", json=body)
    assert refused.status_code == HTTPStatus.CONFLICT
    assert "type the folder label" in refused.json()["detail"]["message"]
    assert (roms_root / "NES Set" / "odd.nes").exists()

    client.post("/api/folders/nes/unmatched", json=body | {"confirm": "nes"})
    assert wait_run(client)["message"] == "1 file deleted"
    assert not (roms_root / "NES Set" / "odd.nes").exists() and unmatched(client) == []


def test_only_unmatched_files_can_be_moved_out_this_way(setup):  # noqa: F811
    client, _, _ = setup
    scanned(client)
    refused = client.post(
        "/api/folders/nes/unmatched/preview", json={"rel_paths": ["Contra (USA).zip"]}
    )
    assert refused.status_code == HTTPStatus.CONFLICT
    assert refused.json()["detail"]["problems"][0]["rel_path"] == "Contra (USA).zip"


# Emptying discarded/ ----------------------------------------------------------------


def test_empty_discarded_deletes_everything_there_behind_the_guard(setup, roms_root):  # noqa: F811
    client, _, _ = setup
    scanned(client)
    apply = client.post("/api/folders/nes/apply/preview", json={}).json()
    client.post("/api/folders/nes/apply", json={"token": apply["token"]})
    wait_run(client)
    operation = versions(client)["Contra (Japan).zip"]["discarded"]
    stray = roms_root / "discarded" / "nes" / "elsewhere" / "deep" / "x.bin"
    stray.parent.mkdir(parents=True)
    stray.write_bytes(b"not the app's")

    plan = preview(client, "discarded/empty")
    assert [f["rel_path"] for f in plan["files"]] == [
        "1g1r/Contra (Japan).zip",
        "elsewhere/deep/x.bin",
    ]
    assert plan["irreversible"] == 1 + 1
    refused = client.post("/api/folders/nes/discarded/empty", json={"token": plan["token"]})
    assert refused.status_code == HTTPStatus.CONFLICT

    started = client.post(
        "/api/folders/nes/discarded/empty", json={"token": plan["token"], "confirm": "nes"}
    )
    assert started.status_code == HTTPStatus.ACCEPTED
    assert wait_run(client)["message"] == "2 files deleted"
    root = roms_root / "discarded" / "nes"
    assert root.is_dir() and list(root.iterdir()) == []
    # Games show discarded versions until discarded/ is emptied; then they are gone.
    assert "Contra (Japan).zip" not in versions(client)
    gone = client.post("/api/folders/nes/restore", json={"operation_ids": [operation]})
    assert gone.status_code == HTTPStatus.CONFLICT
    assert client.post("/api/folders/nes/apply/preview", json={}).json()["moves"] == []
    assert preview(client, "discarded/empty")["files"] == []


def test_a_changed_discarded_file_refuses_emptying(setup, roms_root):  # noqa: F811
    client, _, _ = setup
    scanned(client)
    stray = roms_root / "discarded" / "nes" / "x.bin"
    stray.parent.mkdir(parents=True)
    stray.write_bytes(b"a")
    plan = preview(client, "discarded/empty")
    stray.write_bytes(b"changed")
    refused = client.post(
        "/api/folders/nes/discarded/empty", json={"token": plan["token"], "confirm": "nes"}
    )
    assert refused.status_code == HTTPStatus.CONFLICT
    assert stray.exists()


def test_recovery_settles_a_cut_off_empty(tmp_path):
    conn = db.connect(tmp_path / "state.db", 1000)
    db.migrate(conn)
    gone = tmp_path / "discarded"
    gone.mkdir()
    conn.execute(
        "INSERT INTO folder_file (folder_label, rel_path, size, mtime_ns, kind, place) "
        "VALUES ('f', 'a.zip', 1, 1, 'archive', 'discarded')"
    )
    moved_run = journal.start_run(conn, "f", journal.APPLY, "", 1)
    move = conn.execute(
        "INSERT INTO operation (run_id, folder_label, rel_path, reason, source, destination, "
        "size, mtime_ns, state) VALUES (?, 'f', 'a.zip', '1g1r', ?, ?, 1, 1, 'done')",
        (moved_run, str(tmp_path / "a.zip"), str(gone / "1g1r" / "a.zip")),
    ).lastrowid
    empty_run = journal.start_run(conn, "f", journal.APPLY, journal.SCOPE_EMPTY, 1 + 1)
    # Already deleted when the restart came: done, and the table forgets it.
    deleted = conn.execute(
        "INSERT INTO operation (run_id, folder_label, rel_path, reason, source, destination, "
        "size, mtime_ns, state, action, step_of) "
        "VALUES (?, 'f', '1g1r/a.zip', '1g1r', ?, '', 1, 1, 'started', 'delete', ?)",
        (empty_run, str(gone / "1g1r" / "a.zip"), move),
    ).lastrowid
    # Not deleted yet: kept, never finished after a restart.
    (gone / "b.bin").write_bytes(b"b")
    kept = conn.execute(
        "INSERT INTO operation (run_id, folder_label, rel_path, reason, source, destination, "
        "size, mtime_ns, state, action) "
        "VALUES (?, 'f', 'b.bin', 'b.bin', ?, '', 1, 1, 'started', 'delete')",
        (empty_run, str(gone / "b.bin")),
    ).lastrowid

    assert journal.recover(CONFIG, conn) == 1 + 1
    state = dict(conn.execute("SELECT id, state FROM operation").fetchall())
    assert state[deleted] == "done" and state[kept] == "failed" and (gone / "b.bin").exists()
    assert conn.execute("SELECT COUNT(*) FROM folder_file").fetchone()[0] == 0
    assert journal.active_discards(conn, "f") == []


# Flagged and unsupported files --------------------------------------------------------


def amiga_with_leftovers(folder_of):
    client, folder = folder_of("amiga")
    with zipfile.ZipFile(folder / "C (Europe).zip", "w") as z:
        z.writestr("C (Europe).scp", b"SCP")
    (folder / "B (Europe).scp").write_bytes(b"SCP")
    (folder / "D (Europe).adf").write_bytes(b"ADF")
    rows = proposals(client, "amiga")
    assert rows["C (Europe).zip"]["status"] == "flagged"
    assert {f["rel_path"] for f in client.get("/api/folders/amiga").json()["unsupported"]} == {
        "B (Europe).scp",
        "C (Europe).zip",
    }
    return client, folder


def test_set_aside_moves_flagged_and_unsupported_files_and_restores_them(folder_of, roms_root):
    client, folder = amiga_with_leftovers(folder_of)
    wanted = ["B (Europe).scp", "C (Europe).zip"]
    plan = client.post("/api/folders/amiga/set-aside/preview", json={"rel_paths": wanted}).json()
    assert plan["irreversible"] == 0 and plan["problems"] == []
    manual = roms_root / "discarded" / "amiga" / "manual"
    assert [f["destination"] for f in plan["files"]] == [str(manual / rel) for rel in wanted]

    body = {"rel_paths": wanted, "token": plan["token"]}
    started = client.post("/api/folders/amiga/set-aside", json=body)
    assert started.status_code == HTTPStatus.ACCEPTED
    assert wait_run(client, "amiga")["message"] == "2 files moved to discarded/"
    assert all((manual / rel).exists() and not (folder / rel).exists() for rel in wanted)
    assert client.get("/api/folders/amiga").json()["unsupported"] == []
    feed = client.get("/api/notifications").json()
    assert "Flagged and unsupported files" in {i["title"] for i in feed}

    listing = client.get("/api/folders/amiga/discarded").json()
    ids = [f["operation_id"] for f in listing["reasons"][0]["files"]]
    client.post("/api/folders/amiga/restore", json={"operation_ids": ids})
    assert wait_run(client, "amiga")["message"] == "2 files restored"
    assert all((folder / rel).exists() for rel in wanted)


def test_set_aside_refuses_files_that_are_neither_flagged_nor_unsupported(folder_of):
    client, folder = amiga_with_leftovers(folder_of)
    refused = client.post(
        "/api/folders/amiga/set-aside/preview", json={"rel_paths": ["D (Europe).adf"]}
    )
    assert refused.status_code == HTTPStatus.CONFLICT
    assert refused.json()["detail"]["problems"][0]["rel_path"] == "D (Europe).adf"
    assert (folder / "D (Europe).adf").exists()
