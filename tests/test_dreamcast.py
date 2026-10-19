import os
import zipfile
from http import HTTPStatus
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from g1r import discs
from g1r.web.app import create_app

from .test_discs import HAS_CHDMAN, MIN_TRACK_SECTORS, SECTOR

# Where a GD-ROM's high-density area starts (the third track of a .gdi).
HIGH_DENSITY_LBA = 45000


def test_gdi_files_name_their_tracks():
    text = '3\n1 0 4 2352 track01.bin 0\n2 750 0 2352 "track 02.raw" 0\n3 45000 4 2352 t3.bin 0\n'
    assert discs.gdi_files(text) == ["track01.bin", "track 02.raw", "t3.bin"]


def gdi(folder: Path, stem: str) -> list[Path]:
    """A small GD-ROM as a .gdi: a data track, an audio track, then the high-density area."""
    names = [f"{stem}01.bin", f"{stem}02.raw", f"{stem}03.bin"]
    for name in names:
        (folder / name).write_bytes(os.urandom(SECTOR * MIN_TRACK_SECTORS))
    lines = [
        f"1 0 4 {SECTOR} {names[0]} 0",
        f"2 {MIN_TRACK_SECTORS + MIN_TRACK_SECTORS} 0 {SECTOR} {names[1]} 0",
        f"3 {HIGH_DENSITY_LBA} 4 {SECTOR} {names[2]} 0",
    ]
    (folder / f"{stem}.gdi").write_text(f"{len(names)}\n" + "\n".join(lines) + "\n")
    return [folder / n for n in names]


@pytest.fixture
def dc(make_settings, roms_root):
    folder = roms_root / "dc"
    folder.mkdir()
    (roms_root / "discarded").mkdir()
    settings = make_settings({"chdman": {"timeout_seconds": 60}})
    with TestClient(create_app(settings, report_runner=lambda *a, **_: [])) as client:
        body = {"platform": "dc", "mount": "roms", "path": "dc", "label": "dc"}
        assert client.post("/api/folders", json=body).status_code == HTTPStatus.CREATED
        yield client, folder


def scan(client):
    client.post("/api/folders/dc/scan")
    for _ in range(500):
        if client.get("/api/folders/dc/scan").json()["status"] != "running":
            return
    raise AssertionError("scan did not finish")


def rows(client):
    return {r["rel_path"]: r for r in client.get("/api/folders/dc/conversion").json()["rows"]}


def test_gdi_sets_loose_or_zipped_are_proposed_as_chds(dc, roms_root):
    client, folder = dc
    tracks = gdi(folder, "A")
    zipped = roms_root / "zipped"
    zipped.mkdir()
    with zipfile.ZipFile(folder / "B (USA).zip", "w") as z:
        for path in [*gdi(zipped, "B"), zipped / "B.gdi"]:
            z.write(path, path.name)
    scan(client)
    found = rows(client)
    a = found["A.gdi"]
    assert (a["status"], a["output"], a["disc_mode"]) == ("make chd", "A.chd", "createcd")
    assert a["parts"] == [t.name for t in tracks]
    assert {found[t.name]["status"] for t in tracks} == {"part"}
    b = found["B (USA).zip"]
    assert (b["status"], b["recipe"], b["output"]) == ("make chd", "archive-disc", "B.chd")
    # Loose sheets and tracks are parts: not unmatched, not looked up (the zip is a file).
    unmatched = [f["rel_path"] for f in client.get("/api/folders/dc/unmatched").json()]
    assert unmatched == ["B (USA).zip"]


@pytest.mark.skipif(not HAS_CHDMAN, reason="chdman is not installed (it is in the image)")
def test_a_gdi_becomes_a_verified_chd(dc, roms_root):
    client, folder = dc
    tracks = gdi(folder, "A")
    data = [t.read_bytes() for t in tracks]
    scan(client)
    plan = client.post("/api/folders/dc/convert/preview", json={}).json()
    assert plan["problems"] == []
    client.post("/api/folders/dc/convert", json={"token": plan["token"]})
    for _ in range(5000):
        run = client.get("/api/folders/dc/run").json()
        if run and run["status"] != "running":
            break
    assert (run["status"], run["message"]) == ("done", "1 file converted"), run["failed"]
    assert (folder / "A.chd").is_file() and not (folder / "A.gdi").exists()
    originals = roms_root / "discarded" / "dc" / "originals"
    assert [(originals / t.name).read_bytes() for t in tracks] == data
