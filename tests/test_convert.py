import subprocess
import threading
import time
import zipfile
import zlib
from http import HTTPStatus
from pathlib import Path

import pytest

from g1r import conversion, converter, db, discs, journal, moves, stopping
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
            "originals": 1,
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
    contra = next(g for g in client.get("/api/folders/nes/games").json() if g["name"] == "Contra")
    client.put(
        "/api/folders/nes/keep",
        json={"group_key": contra["key"], "rel_path": "Contra (Japan).zip"},
    )
    client.put("/api/settings/targets", json={"targets": {"nes": "plain"}})
    # Every zip now waits to be unpacked: out of 1G1R until converted (P10, Q3).
    assert client.get("/api/folders/nes/games").json() == []
    plan = preview(client, rel_paths=["Contra (Japan).zip"])
    assert [c["output"] for c in plan["conversions"]] == ["Contra (Japan).nes"]
    client.post(
        "/api/folders/nes/convert",
        json={"rel_paths": ["Contra (Japan).zip"], "token": plan["token"]},
    )
    assert wait_run(client)["status"] == "done"
    assert (roms_root / "NES Set" / "Contra (Japan).nes").read_bytes() == b"Contra (Japan)"

    # The output carries the identity (no scan needed) and the pick.
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


def test_the_unpacked_disc_is_deleted_once_the_chd_is_written(make_settings, tmp_path, monkeypatch):
    """Only the CHD and the tracks extracted back from it share the disk, never the unpacked
    copy too: the check compares with the digests taken before chdman ran."""
    settings = make_settings()
    image = b"disc data" * 64
    archive = tmp_path / "Game.7z"
    archive.write_bytes(b"7z")
    output = tmp_path / "Game.chd"
    work = moves.work_path(settings.apply, output)
    unpacked = work / converter.UNPACKED

    def extract(settings_, archive_, member, out):
        out.write_bytes(image)

    def create(chdman, mode, disc, chd):
        assert disc.read_bytes() == image
        chd.write_bytes(image)

    def verify(chdman, chd):
        assert not unpacked.exists()

    def extract_dvd(chdman, chd, out):
        assert not unpacked.exists()
        out.write_bytes(chd.read_bytes())

    monkeypatch.setattr(discs, "create", create)
    monkeypatch.setattr(discs, "verify", verify)
    monkeypatch.setattr(discs, "extract_dvd", extract_dvd)
    crc, size = format(zlib.crc32(image), "08x"), len(image)
    Converter(settings, extract=extract)(
        step(
            archive,
            output,
            recipe=conversion.RECIPE_ARCHIVE_DISC,
            disc_mode=discs.CREATEDVD,
            inner=(("Game.iso", size, crc),),
        )
    )
    assert output.read_bytes() == image and not work.exists()


# Parallel conversion runs --------------------------------------------------------------


def _conversion_plan(folder: Path, names: list[str]) -> list[journal.Move]:
    plan = []
    for name in names:
        rom = folder / f"{name}.nes"
        rom.write_bytes(name.encode())
        plan.append(step(rom, folder / f"{name}.zip", paired_rel=f"{name}.zip"))
        stat = rom.stat()
        common = (rom.name, "", "originals", rom, None, stat.st_size, stat.st_mtime_ns)
        plan.append(journal.Move(*common, action=journal.DELETE, follows=True))
    return plan


def _conversion_run(tmp_path, plan):
    conn = db.connect(tmp_path / "state.db", 1000)
    db.migrate(conn)
    return conn, journal.start_run(conn, "f", journal.APPLY, journal.CONVERT, len(plan))


def test_a_conversion_run_converts_several_files_at_a_time(make_settings, tmp_path):
    """Each conversion waits until the other has started too: one at a time, both fail."""
    folder = tmp_path / "folder"
    folder.mkdir()
    names = ["a", "b"]
    plan = _conversion_plan(folder, names)
    conn, run_id = _conversion_run(tmp_path, plan)
    both = threading.Barrier(len(names), timeout=1)
    wrap = Converter(make_settings())

    def convert(m):
        both.wait()
        return wrap(m)

    journal.run(CONFIG, conn, run_id, "f", plan, convert, workers=len(names))
    run = journal.progress(conn, run_id)
    assert (run["status"], run["message"]) == ("done", "2 files converted")
    for name in names:
        assert (folder / f"{name}.zip").exists() and not (folder / f"{name}.nes").exists()
    # Each delete finishes the conversion of its own file.
    steps = conn.execute("SELECT id, rel_path, action, step_of FROM operation").fetchall()
    converts = {s["rel_path"]: s["id"] for s in steps if s["action"] == journal.CONVERT}
    for s in steps:
        if s["action"] == journal.DELETE:
            assert s["step_of"] == converts[s["rel_path"]]


def test_a_failed_conversion_keeps_its_original_and_the_run_goes_on(
    make_settings, tmp_path, monkeypatch
):
    """B12: b fails while a is converting; a, c and d are still converted, b is listed."""
    folder = tmp_path / "folder"
    folder.mkdir()
    plan = _conversion_plan(folder, ["a", "b", "c", "d"])
    conn, run_id = _conversion_run(tmp_path, plan)
    wrap = Converter(make_settings())
    started = []

    def convert(m):
        started.append(m.rel_path)
        if m.rel_path == "b.nes":
            raise moves.MoveError("chdman exited with 1")
        return wrap(m)

    journal.run(CONFIG, conn, run_id, "f", plan, convert, workers=1 + 1)
    run = journal.progress(conn, run_id)
    assert (run["status"], run["message"]) == ("failed", "3 files converted; 1 failed")
    assert run["failed"] == [
        {"rel_path": "b.nes", "error": "chdman exited with 1", "action": "convert"}
    ]
    assert sorted(started) == ["a.nes", "b.nes", "c.nes", "d.nes"]
    for name in ("a", "c", "d"):
        assert (folder / f"{name}.zip").exists() and not (folder / f"{name}.nes").exists()
    assert (folder / "b.nes").exists() and not (folder / "b.zip").exists()


def test_a_restore_keeps_an_output_whose_original_did_not_come_back(
    setup,  # noqa: F811
    roms_root,
    monkeypatch,
):
    """B12: the run goes on after a failed move back, but never removes that conversion's
    output: the original is still in discarded/, the output the only copy in the folder."""
    client, _, _ = setup
    scanned(client)
    folder = roms_root / "NES Set"
    client.post("/api/folders/nes/convert", json={"token": preview(client)["token"]})
    assert wait_run(client)["message"] == "1 file converted"
    original = client.get("/api/folders/nes/discarded").json()["reasons"][0]["files"][0]
    move = moves.move

    def failing(config, source, destination):
        if source.name == "odd.nes":
            raise moves.MoveError("the disk went away")
        return move(config, source, destination)

    monkeypatch.setattr(moves, "move", failing)
    client.post("/api/folders/nes/restore", json={"operation_ids": [original["operation_id"]]})
    run = wait_run(client)
    assert (run["status"], run["message"]) == ("failed", "0 files restored; 2 failed")
    assert [f["error"] for f in run["failed"]] == [
        "the disk went away",
        "kept: not every original came back",
    ]
    assert (folder / "odd.zip").exists() and (roms_root / ORIGINALS / "odd.nes").exists()


# Stopping a conversion run -------------------------------------------------------------

LONG = ["sleep", "30"]


def test_an_armed_tool_is_killed_when_the_stop_comes():
    stop = threading.Event()
    threading.Timer(0.1, stop.set).start()
    started = time.monotonic()
    with stopping.armed(stop, CONFIG.stop_poll_seconds), pytest.raises(stopping.Stopped):
        stopping.run(LONG, 60)
    assert time.monotonic() - started < 5
    # Unarmed (a scan), or armed with no stop, a tool runs as before.
    assert stopping.run(["true"], 5).returncode == 0
    with stopping.armed(threading.Event(), CONFIG.stop_poll_seconds):
        assert stopping.run(["sh", "-c", "echo hi"], 5, stdout=subprocess.PIPE).stdout == b"hi\n"
        with pytest.raises(subprocess.TimeoutExpired):
            stopping.run(LONG, 0.2)


def test_a_stopped_run_keeps_converted_files_and_deletes_the_one_under_way(make_settings, tmp_path):
    """a is converted, b is cut off while 7-Zip extracts it, c never starts."""
    settings = make_settings()
    folder = tmp_path / "folder"
    folder.mkdir()
    plan = _conversion_plan(folder, ["a"])
    archive = folder / "b.zip"
    write_zip(archive, "b.nes", b"rom data")
    crc = format(zipfile.ZipFile(archive).getinfo("b.nes").CRC, "08x")
    member = {"member": "b.nes", "member_size": len(b"rom data"), "member_crc32": crc}
    plan.append(step(archive, folder / "b.nes", paired_rel="b.nes", **member))
    stat = archive.stat()
    plan.append(
        journal.Move(
            "b.zip", "", "originals", archive, None, stat.st_size, stat.st_mtime_ns,
            action=journal.DELETE, follows=True,
        )
    )  # fmt: skip
    plan += _conversion_plan(folder, ["c"])
    conn, run_id = _conversion_run(tmp_path, plan)
    stop = threading.Event()
    output = folder / "b.nes"

    def slow_extract(settings, archive, member, out):
        out.write_bytes(b"half")
        stop.set()  # the user presses Stop while 7-Zip works
        stopping.run(LONG, 60)

    started = time.monotonic()
    journal.run(CONFIG, conn, run_id, "f", plan, Converter(settings, slow_extract), 1, stop)
    assert time.monotonic() - started < 5
    run = journal.progress(conn, run_id)
    assert (run["status"], run["message"]) == (
        "done",
        "stopped: 1 file converted, 2 not converted",
    )
    assert run["failed"] == []
    assert (folder / "a.zip").exists() and not (folder / "a.nes").exists()
    assert archive.exists() and not output.exists()
    assert not moves.temp_path(settings.apply, output).exists()
    assert (folder / "c.nes").exists() and not (folder / "c.zip").exists()
    states = conn.execute("SELECT rel_path, action, state FROM operation ORDER BY id").fetchall()
    # b was cut off: nothing of it is left to restore or to recover.
    assert [tuple(r) for r in states] == [("a.nes", "convert", "done"), ("a.nes", "delete", "done")]


def test_stop_through_the_api(setup, roms_root, monkeypatch):  # noqa: F811
    client, _, _ = setup
    scanned(client)
    stop = client.post("/api/folders/nes/convert/stop")
    assert stop.status_code == HTTPStatus.CONFLICT
    jobs = client.app.state.jobs
    running = threading.Event()

    def slow(m):
        running.set()
        stopping.run(LONG, 60)

    monkeypatch.setattr(jobs, "converter", slow)
    plan = preview(client)
    started = client.post("/api/folders/nes/convert", json={"token": plan["token"]})
    assert started.status_code == HTTPStatus.ACCEPTED
    assert running.wait(5)
    card = {f["label"]: f for f in client.get("/api/folders").json()}["nes"]
    assert card["converting"]["stopping"] is False
    stop = client.post("/api/folders/nes/convert/stop")
    assert stop.status_code == HTTPStatus.ACCEPTED and stop.json()["stopping"] is True
    run = wait_run(client)
    assert (run["status"], run["stopping"], run["message"]) == (
        "done",
        True,
        "stopped: 0 files converted, 1 not converted",
    )
    assert (roms_root / "NES Set" / "odd.nes").exists()
    assert {f["label"]: f for f in client.get("/api/folders").json()}["nes"]["converting"] is None


# Repack: another archive rewritten as a zip --------------------------------------------


def slt(members) -> str:
    """7-Zip's technical listing of an archive holding `members` (a dict, or (name, data)
    pairs when a name repeats)."""
    pairs = members.items() if isinstance(members, dict) else members
    blocks = [
        f"Path = {name}\nSize = {len(data)}\nCRC = {zlib.crc32(data):08X}\nAttributes = A"
        for name, data in pairs
    ]
    return "Path = x.7z\nType = 7z\n\n----------\n" + "\n\n".join(blocks) + "\n"


def repacker(make_settings, members: dict[str, bytes], unpacked=None, listing=None):
    """A Converter whose 7-Zip lists `listing` (default: the members) and unpacks `unpacked`
    (default: the members; a name ending in a slash is an empty folder)."""

    def unpack(settings, archive, directory):
        for name, data in (unpacked if unpacked is not None else members).items():
            target = directory / name
            if name.endswith("/"):
                target.mkdir(parents=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

    return Converter(
        make_settings(),
        unpack=unpack,
        seven_zip=lambda settings, path: listing or slt(members),
    )


def test_repack_zips_every_member_and_checks_them(make_settings, tmp_path):
    here = tmp_path / "set"
    here.mkdir()
    members = {"Game (Disc 1).gb": b"one", "Game (Disc 2).gb": b"two", "extra/info.txt": b""}
    archive = here / "Game.7z"
    archive.write_bytes(b"7z data")
    output = here / "Game.zip"
    convert = repacker(make_settings, members, unpacked={**members, "empty/": b""})
    convert(step(archive, output, recipe=conversion.RECIPE_REPACK))
    with zipfile.ZipFile(output) as z:
        assert {i.filename: z.read(i) for i in z.infolist() if not i.is_dir()} == members
        assert "empty/" in z.namelist()
    # The original stays (the journal moves it); the work folder is gone.
    assert sorted(p.name for p in here.iterdir()) == ["Game.7z", "Game.zip"]


@pytest.mark.parametrize(
    ("unpacked", "listing"),
    [
        # A member that comes out different from what the archive lists.
        ({"a.gb": b"changed"}, None),
        # Two members of one name: 7-Zip keeps only the last.
        ({"a.gb": b"two"}, slt([("a.gb", b"one"), ("a.gb", b"two")])),
    ],
)
def test_a_repack_that_does_not_round_trip_leaves_nothing(
    make_settings, tmp_path, unpacked, listing
):
    here = tmp_path / "set"
    here.mkdir()
    archive = here / "A.7z"
    archive.write_bytes(b"7z data")
    convert = repacker(make_settings, {"a.gb": b"one"}, unpacked=unpacked, listing=listing)
    with pytest.raises(moves.MoveError):
        convert(step(archive, here / "A.zip", recipe=conversion.RECIPE_REPACK))
    assert sorted(p.name for p in here.iterdir()) == ["A.7z"]


def test_a_repack_refuses_links(make_settings, tmp_path):
    here = tmp_path / "set"
    here.mkdir()
    archive = here / "L.7z"
    archive.write_bytes(b"7z data")

    def unpack(settings, archive_, directory):
        (directory / "a.gb").write_bytes(b"one")
        (directory / "link.gb").symlink_to(directory / "a.gb")

    members = {"a.gb": b"one", "link.gb": b"one"}
    convert = Converter(make_settings(), unpack=unpack, seven_zip=lambda s, p: slt(members))
    with pytest.raises(moves.MoveError, match="link"):
        convert(step(archive, here / "L.zip", recipe=conversion.RECIPE_REPACK))
    assert sorted(p.name for p in here.iterdir()) == ["L.7z"]
