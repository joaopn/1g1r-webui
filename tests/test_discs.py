import os
import shutil
import struct
import zipfile
from http import HTTPStatus
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from g1r import db, discs
from g1r.web.app import create_app

SECTOR = 2352
# A CD track lasts at least 4 seconds of 75 sectors. (chdman makes an unreadable CHD from a
# few sectors of random audio, which its verify catches; real discs never are that short.)
MIN_TRACK_SECTORS = 300
HAS_CHDMAN = shutil.which("chdman") is not None


def test_cue_sheets_name_their_track_files():
    text = (
        'FILE "Game (USA) (Track 1).bin" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n'
        "file track2.wav WAVE\n  TRACK 02 AUDIO\nREM FILE nope\n"
    )
    assert discs.cue_files(text) == ["Game (USA) (Track 1).bin", "track2.wav"]


def audio_cue(folder: Path, stem: str, tracks: int, sectors: int = MIN_TRACK_SECTORS) -> list[Path]:
    """A small disc of audio tracks (any bytes are valid audio), one file per track."""
    lines, paths = [], []
    for n in range(1, tracks + 1):
        name = f"{stem} (Track {n}).bin"
        (folder / name).write_bytes(os.urandom(SECTOR * sectors))
        lines += [f'FILE "{name}" BINARY', f"  TRACK {n:02d} AUDIO", "    INDEX 01 00:00:00"]
        paths.append(folder / name)
    (folder / f"{stem}.cue").write_text("\n".join(lines) + "\n")
    return paths


@pytest.fixture
def psx(make_settings, roms_root):
    folder = roms_root / "psx"
    folder.mkdir()
    (roms_root / "discarded").mkdir()
    settings = make_settings({"chdman": {"timeout_seconds": 60}})
    with TestClient(create_app(settings, report_runner=lambda *a, **_: [])) as client:
        added = client.post(
            "/api/folders", json={"platform": "psx", "mount": "roms", "path": "psx", "label": "psx"}
        )
        assert added.status_code == HTTPStatus.CREATED
        yield client, folder


def scan(client):
    client.post("/api/folders/psx/scan")
    for _ in range(500):
        result = client.get("/api/folders/psx/scan").json()
        if result["status"] != "running":
            return result
    raise AssertionError("scan did not finish")


def rows(client):
    return {r["rel_path"]: r for r in client.get("/api/folders/psx/conversion").json()["rows"]}


def test_disc_proposals(psx):
    client, folder = psx
    audio_cue(folder, "A (USA)", 2)
    (folder / "B (USA).cue").write_text('FILE "B (USA).bin" BINARY\n  TRACK 01 AUDIO\n')
    (folder / "orphan.bin").write_bytes(b"\0" * SECTOR)
    (folder / "C (USA).chd").write_bytes(b"MComprHD")
    with zipfile.ZipFile(folder / "D (USA).zip", "w") as z:
        z.writestr("D (USA).cue", 'FILE "D (USA).bin" BINARY\n  TRACK 01 AUDIO\n')
        z.writestr("D (USA).bin", b"\0" * SECTOR)
    with zipfile.ZipFile(folder / "E (USA).zip", "w") as z:
        z.writestr("E (USA).chd", b"MComprHD")
    (folder / "F (USA).iso").write_bytes(b"\0" * 2048)
    scan(client)
    found = rows(client)
    a = found["A (USA).cue"]
    assert (a["status"], a["output"], a["recipe"]) == ("make chd", "A (USA).chd", "disc")
    assert a["parts"] == ["A (USA) (Track 1).bin", "A (USA) (Track 2).bin"]
    assert found["A (USA) (Track 1).bin"]["status"] == "part"
    assert "missing" in found["B (USA).cue"]["note"] and found["B (USA).cue"]["status"] == "flagged"
    assert found["orphan.bin"]["status"] == "flagged"
    assert found["C (USA).chd"]["status"] == "done"
    d = found["D (USA).zip"]
    assert (d["status"], d["output"], d["recipe"]) == ("make chd", "D (USA).chd", "archive-disc")
    assert (found["E (USA).zip"]["status"], found["E (USA).zip"]["output"]) == (
        "unwrap",
        "E (USA).chd",
    )
    f = found["F (USA).iso"]
    assert (f["status"], f["disc_mode"]) == ("make chd", "createcd")


def test_parts_are_not_versions_or_unmatched(psx):
    client, folder = psx
    audio_cue(folder, "A (USA)", 2)
    scan(client)
    summary = client.get("/api/folders/psx").json()["summary"]
    assert summary["waiting"] == 1 + 1 + 1 and summary["unmatched"] == 0
    assert client.get("/api/folders/psx/unmatched").json() == []
    refused = client.post(
        "/api/folders/psx/unmatched/preview", json={"rel_paths": ["A (USA) (Track 1).bin"]}
    )
    assert refused.status_code == HTTPStatus.CONFLICT


def test_the_plan_moves_every_original_of_a_cue_sheet(psx, roms_root):
    client, folder = psx
    (folder / "sub").mkdir()
    audio_cue(folder / "sub", "A (USA)", 2)
    scan(client)
    plan = client.post("/api/folders/psx/convert/preview", json={}).json()
    (conversion,) = plan["conversions"]
    assert conversion["output"] == "sub/A (USA).chd"
    assert conversion["original_to"] == str(roms_root / "discarded/psx/originals/sub/A (USA).cue")


def wait_run(client):
    for _ in range(5000):
        run = client.get("/api/folders/psx/run").json()
        if run and run["status"] != "running":
            return run
    raise AssertionError("run did not finish")


def convert_all(client):
    plan = client.post("/api/folders/psx/convert/preview", json={}).json()
    assert plan["problems"] == [], plan["problems"]
    started = client.post("/api/folders/psx/convert", json={"token": plan["token"]})
    assert started.status_code == HTTPStatus.ACCEPTED, started.json()
    return wait_run(client)


@pytest.mark.skipif(not HAS_CHDMAN, reason="chdman is not installed (it is in the image)")
def test_a_cue_sheet_becomes_a_verified_chd_and_restores(psx, roms_root):
    client, folder = psx
    tracks = audio_cue(folder, "A (USA)", 3)
    data = [t.read_bytes() for t in tracks]
    with zipfile.ZipFile(folder / "Z (USA).zip", "w") as z:
        for path in audio_cue(roms_root, "Z (USA)", 2):
            z.write(path, path.name)
        z.write(roms_root / "Z (USA).cue", "Z (USA).cue")
    scan(client)
    run = convert_all(client)
    assert (run["status"], run["message"]) == ("done", "2 files converted"), (
        run["message"],
        run["failed"],
    )
    assert (folder / "A (USA).chd").is_file() and (folder / "Z (USA).chd").is_file()
    originals = roms_root / "discarded" / "psx" / "originals"
    assert sorted(p.name for p in originals.iterdir()) == sorted(
        [*(t.name for t in tracks), "A (USA).cue", "Z (USA).zip"]
    )
    assert not list(folder.glob("*.g1r-*"))
    assert rows(client)["A (USA).chd"]["status"] == "done"

    # Restoring one track brings the whole set back and removes the CHD.
    listing = client.get("/api/folders/psx/discarded").json()["reasons"][0]["files"]
    track = next(f for f in listing if f["rel_path"] == tracks[0].name)
    client.post("/api/folders/psx/restore", json={"operation_ids": [track["operation_id"]]})
    assert wait_run(client)["status"] == "done"
    assert [t.read_bytes() for t in tracks] == data
    assert (folder / "A (USA).cue").is_file() and not (folder / "A (USA).chd").exists()
    assert (folder / "Z (USA).chd").exists()


def test_a_chd_is_known_by_its_header_not_its_bytes(tmp_path):
    from g1r.hashing import CHD_TAG, CHD_V5, chd_identity

    sha1 = bytes(range(20))
    header = struct.pack(
        CHD_V5,
        CHD_TAG,
        struct.calcsize(CHD_V5),
        5,
        b"\0" * 16,
        4096,
        0,
        0,
        2048,
        2448,
        b"\0" * 20,
        sha1,
        b"\0" * 20,
    )
    (tmp_path / "a.chd").write_bytes(header + b"compressed one way")
    (tmp_path / "b.chd").write_bytes(header + b"and another")
    assert (
        chd_identity(tmp_path / "a.chd") == chd_identity(tmp_path / "b.chd") == (4096, sha1.hex())
    )
    (tmp_path / "c.chd").write_bytes(b"not a chd")
    assert chd_identity(tmp_path / "c.chd") is None


def test_parts_are_not_hashed_or_looked_up(psx):
    client, folder = psx
    audio_cue(folder, "A (USA)", 2)
    dat = (
        "<?xml version='1.0'?><datafile><header><name>Sony - PlayStation</name></header>"
        '<game name="Other (USA)"><rom name="Other (USA).bin" size="1" crc="00000000"/></game>'
        "</datafile>"
    )
    client.post("/api/dats/psx/upload", files={"file": ("psx.dat", dat.encode())})
    assert scan(client)["status"] == "done"
    assert client.get("/api/folders/psx/unmatched").json() == []
    # content_hash rows are what an online lookup would send.
    conn = db.open_database(client.app.state.settings)
    assert conn.execute("SELECT COUNT(*) FROM content_hash").fetchone()[0] == 0


def test_a_flagged_cue_sheet_and_its_tracks_can_be_set_aside(psx):
    client, folder = psx
    tracks = audio_cue(folder, "A (USA)", 2)
    (folder / "A (USA).chd").write_bytes(b"MComprHD")
    scan(client)
    rows = {r["rel_path"]: r for r in client.get("/api/folders/psx/conversion").json()["rows"]}
    flagged = [rel for rel, r in rows.items() if r["status"] == "flagged"]
    assert sorted(flagged) == sorted(["A (USA).cue", *(t.name for t in tracks)])
    plan = client.post("/api/folders/psx/set-aside/preview", json={"rel_paths": flagged}).json()
    assert [f["rel_path"] for f in plan["files"]] == sorted(flagged)
