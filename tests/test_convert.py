import zipfile
from http import HTTPStatus
from pathlib import Path

import pytest

from g1r import db, journal, moves
from g1r.converter import Converter, crc_and_size

from .test_api import scanned, setup  # noqa: F401  (fixture)
from .test_journal import CONFIG, versions, wait_run
from .test_scanner import write_zip

ORIGINALS = Path("discarded") / "nes" / "originals"


def step(source: Path, output: Path, **extra) -> journal.Move:
    stat = source.stat()
    return journal.Move(
        source.name,
        "",
        "originals",
        source,
        output,
        stat.st_size,
        stat.st_mtime_ns,
        action=journal.CONVERT,
        **extra,
    )


# The converter ----------------------------------------------------------------------


def test_wrap_writes_a_verified_zip_and_never_overwrites(make_settings, tmp_path):
    convert = Converter(make_settings())
    rom = tmp_path / "Game (USA).nes"
    rom.write_bytes(b"NES\x1a" + bytes(range(64)))
    output = tmp_path / "Game (USA).zip"
    convert(step(rom, output))
    with zipfile.ZipFile(output) as z:
        assert z.namelist() == ["Game (USA).nes"] and z.read("Game (USA).nes") == rom.read_bytes()
    assert rom.exists()
    with pytest.raises(moves.MoveError, match="already exists"):
        convert(step(rom, output))


def test_unwrap_checks_the_listed_crc_and_cleans_up(make_settings, tmp_path):
    settings = make_settings()
    archive = tmp_path / "Game (USA).zip"
    write_zip(archive, "Game (USA).nes", b"rom data")
    crc = format(zipfile.ZipFile(archive).getinfo("Game (USA).nes").CRC, "08x")
    output = tmp_path / "Game (USA).nes"
    member = {"member": "Game (USA).nes", "member_size": len(b"rom data")}

    with pytest.raises(moves.MoveError, match="the archive lists"):
        Converter(settings)(step(archive, output, **member, member_crc32="00000000"))
    assert not output.exists()
    assert not moves.temp_path(settings.apply, output).exists()

    Converter(settings)(step(archive, output, **member, member_crc32=crc))
    assert output.read_bytes() == b"rom data" and archive.exists()


def test_a_failed_extract_leaves_nothing_behind(make_settings, tmp_path):
    def broken(settings, archive, member, out):
        out.write_bytes(b"half")
        raise moves.MoveError("7-Zip exited with 2")

    settings = make_settings()
    archive = tmp_path / "Game.7z"
    archive.write_bytes(b"7z")
    output = tmp_path / "Game.nes"
    extra = {"member": "Game.nes", "member_size": 1, "member_crc32": "abcd0123"}
    with pytest.raises(moves.MoveError, match="7-Zip"):
        Converter(settings, extract=broken)(step(archive, output, **extra))
    assert not output.exists() and not moves.temp_path(settings.apply, output).exists()


# Conversions through the API ----------------------------------------------------------


def preview(client, **body):
    return client.post("/api/folders/nes/convert/preview", json=body).json()


def test_wrap_a_folder_then_restore_the_original(setup, roms_root):  # noqa: F811
    client, _, _ = setup
    scanned(client)
    folder = roms_root / "NES Set"
    plan = preview(client)
    assert plan["conversions"] == [
        {
            "rel_path": "odd.nes",
            "output": "odd.zip",
            "size": 1,
            "original_to": str(roms_root / ORIGINALS / "odd.nes"),
        }
    ]
    assert plan["irreversible"] == 0 and plan["problems"] == []

    stale = client.post("/api/folders/nes/convert", json={"token": "nope"})
    assert stale.status_code == HTTPStatus.CONFLICT
    started = client.post("/api/folders/nes/convert", json={"token": plan["token"]})
    assert started.status_code == HTTPStatus.ACCEPTED
    run = wait_run(client)
    assert (run["status"], run["message"]) == ("done", "1 file converted")
    with zipfile.ZipFile(folder / "odd.zip") as z:
        assert z.read("odd.nes") == b"?"
    assert not (folder / "odd.nes").exists() and (roms_root / ORIGINALS / "odd.nes").exists()

    # The table knows the output at once, without a rescan.
    rows = {r["rel_path"]: r for r in client.get("/api/folders/nes/conversion").json()["rows"]}
    assert "odd.nes" not in rows and rows["odd.zip"]["status"] == "done"
    original_crc = crc_and_size(CONFIG.copy_chunk_bytes, roms_root / ORIGINALS / "odd.nes")[0]
    assert rows["odd.zip"]["members"] == [{"name": "odd.nes", "size": 1, "crc32": original_crc}]
    assert client.get("/api/folders/nes").json()["summary"]["roms"] == len(rows)
    assert preview(client)["conversions"] == []

    listing = client.get("/api/folders/nes/discarded").json()
    original = listing["reasons"][0]["files"][0]
    assert original["rel_path"] == "odd.nes" and original["operation_id"]
    restored = client.post(
        "/api/folders/nes/restore", json={"operation_ids": [original["operation_id"]]}
    )
    assert restored.status_code == HTTPStatus.ACCEPTED, restored.json()
    assert wait_run(client)["message"] == "1 file restored"
    assert (folder / "odd.nes").read_bytes() == b"?" and not (folder / "odd.zip").exists()
    assert [c["rel_path"] for c in preview(client)["conversions"]] == ["odd.nes"]


def test_unwrap_carries_the_identity_and_the_pick(setup, roms_root):  # noqa: F811
    client, _, _ = setup
    scanned(client)
    client.put("/api/settings/targets", json={"targets": {"nes": "plain"}})
    contra = next(g for g in client.get("/api/folders/nes/games").json() if g["name"] == "Contra")
    client.put(
        "/api/folders/nes/keep",
        json={"group_key": contra["key"], "rel_path": "Contra (Japan).zip"},
    )
    plan = preview(client, rel_paths=["Contra (Japan).zip"])
    assert [c["output"] for c in plan["conversions"]] == ["Contra (Japan).nes"]
    client.post(
        "/api/folders/nes/convert",
        json={"rel_paths": ["Contra (Japan).zip"], "token": plan["token"]},
    )
    assert wait_run(client)["status"] == "done"
    assert (roms_root / "NES Set" / "Contra (Japan).nes").read_bytes() == b"x"

    found = versions(client)
    assert "Contra (Japan).zip" not in found
    assert found["Contra (Japan).nes"]["game_name"] == "Contra (Japan)"
    contra = next(g for g in client.get("/api/folders/nes/games").json() if g["name"] == "Contra")
    assert contra["kept"] == "Contra (Japan).nes"


def test_deleting_originals_needs_the_typed_label(setup, roms_root):  # noqa: F811
    client, _, _ = setup
    scanned(client)
    client.put("/api/folders/nes/conversion", json={"delete_originals": True})
    plan = preview(client)
    assert plan["irreversible"] == 1 and plan["conversions"][0]["original_to"] is None

    unconfirmed = client.post("/api/folders/nes/convert", json={"token": plan["token"]})
    assert unconfirmed.status_code == HTTPStatus.CONFLICT
    assert "type the folder label" in unconfirmed.json()["detail"]["message"]
    wrong = client.post("/api/folders/nes/convert", json={"token": plan["token"], "confirm": "x"})
    assert wrong.status_code == HTTPStatus.CONFLICT
    assert (roms_root / "NES Set" / "odd.nes").exists()

    client.post("/api/folders/nes/convert", json={"token": plan["token"], "confirm": "nes"})
    assert wait_run(client)["message"] == "1 file converted"
    assert not (roms_root / "NES Set" / "odd.nes").exists()
    assert (roms_root / "NES Set" / "odd.zip").exists()
    assert not (roms_root / ORIGINALS).exists()


def test_a_changed_source_refuses_the_whole_conversion(setup, roms_root):  # noqa: F811
    client, _, _ = setup
    scanned(client)
    (roms_root / "NES Set" / "odd.nes").write_bytes(b"changed")
    plan = preview(client)
    assert "changed since it was scanned" in plan["problems"][0]["problem"]
    refused = client.post("/api/folders/nes/convert", json={"token": plan["token"]})
    assert refused.status_code == HTTPStatus.CONFLICT
    assert not (roms_root / "NES Set" / "odd.zip").exists()


# Start-up recovery ----------------------------------------------------------------


def _op(conn, run_id, action, rel, source: Path, destination: Path | None, **extra):
    stat = source.stat() if source.exists() else None
    return conn.execute(
        "INSERT INTO operation (run_id, folder_label, rel_path, reason, source, destination, "
        "size, mtime_ns, state, action, step_of) "
        "VALUES (?, 'f', ?, 'originals', ?, ?, ?, ?, 'started', ?, ?)",
        (
            run_id,
            rel,
            str(source),
            str(destination) if destination else "",
            stat.st_size if stat else 0,
            stat.st_mtime_ns if stat else 0,
            action,
            extra.get("step_of"),
        ),
    ).lastrowid


def test_recovery_settles_cut_off_conversions(tmp_path):
    conn = db.connect(tmp_path / "state.db", 1000)
    db.migrate(conn)
    folder = tmp_path / "folder"
    folder.mkdir()
    conn.execute(
        "INSERT INTO folder_file (folder_label, rel_path, size, mtime_ns, kind) "
        "VALUES ('f', 'a.nes', 1, 1, 'rom'), ('f', 'b.nes', 1, 1, 'rom'), "
        "('f', 'c.nes', 1, 1, 'rom')"
    )
    conn.execute(
        "INSERT INTO identity (folder_label, rel_path, game_name, method, dat_sha1) "
        "VALUES ('f', 'a.nes', 'A', 'dat-checksum', 's')"
    )
    run_id = journal.start_run(conn, "f", journal.APPLY, journal.CONVERT, 1 + 1 + 1)

    # Output named: verified before it got its name, so the step is done.
    (folder / "a.nes").write_bytes(b"a")
    with zipfile.ZipFile(folder / "a.zip", "w") as z:
        z.writestr("a.nes", b"a")
    written = _op(conn, run_id, journal.CONVERT, "a.nes", folder / "a.nes", folder / "a.zip")
    # No output yet: nothing happened.
    (folder / "b.nes").write_bytes(b"b")
    (folder / ("b.zip" + CONFIG.temp_suffix)).write_bytes(b"partial")
    unwritten = _op(conn, run_id, journal.CONVERT, "b.nes", folder / "b.nes", folder / "b.zip")
    # A delete cut off: the file is kept, never finished after a restart.
    (folder / "c.nes").write_bytes(b"c")
    kept = _op(conn, run_id, journal.DELETE, "c.nes", folder / "c.nes", None)

    assert journal.recover(CONFIG, conn) == 1 + 1 + 1
    state = dict(conn.execute("SELECT id, state FROM operation").fetchall())
    assert state[written] == "done" and state[unwritten] == "failed" and state[kept] == "failed"
    assert (folder / "c.nes").exists()
    assert not (folder / ("b.zip" + CONFIG.temp_suffix)).exists()
    carried = conn.execute("SELECT game_name FROM identity WHERE rel_path = 'a.zip'").fetchone()
    assert carried[0] == "A"
    member = conn.execute("SELECT member FROM archive_member WHERE rel_path = 'a.zip'").fetchone()
    assert member[0] == "a.nes"
