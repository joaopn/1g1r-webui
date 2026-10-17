import os
import shutil
import zipfile
from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient

from g1r.web.app import create_app

DVD_SECTOR = 2048
SECTORS = 600


@pytest.fixture
def folder_of(make_settings, roms_root):
    """A started app with one folder of the given platform (label = platform)."""
    (roms_root / "discarded").mkdir()
    clients = []

    def make(platform: str):
        folder = roms_root / platform
        folder.mkdir()
        client = TestClient(create_app(make_settings(), report_runner=lambda *a: []))
        client.__enter__()
        clients.append(client)
        body = {"platform": platform, "mount": "roms", "path": platform, "label": platform}
        assert client.post("/api/folders", json=body).status_code == HTTPStatus.CREATED
        return client, folder

    yield make
    for client in clients:
        client.__exit__(None, None, None)


def proposals(client, label):
    client.post(f"/api/folders/{label}/scan")
    for _ in range(500):
        if client.get(f"/api/folders/{label}/scan").json()["status"] != "running":
            break
    return {r["rel_path"]: r for r in client.get(f"/api/folders/{label}/conversion").json()["rows"]}


def test_wii_images_become_rvz_and_stripped_ones_are_left_alone(folder_of):
    client, folder = folder_of("wii")
    with zipfile.ZipFile(folder / "A (Europe).zip", "w") as z:
        z.writestr("A (Europe).rvz", b"RVZ\x01")
    with zipfile.ZipFile(folder / "B (Europe).zip", "w") as z:
        z.writestr("B (Europe).iso", b"\0" * 2048)
    (folder / "C (Europe).iso").write_bytes(b"\0" * 2048)
    (folder / "D (Europe).wbfs").write_bytes(b"WBFS")
    (folder / "E (Europe).nkit.iso").write_bytes(b"\0" * 2048)
    (folder / "F (Europe).rvz").write_bytes(b"RVZ\x01")
    rows = proposals(client, "wii")
    assert (rows["A (Europe).zip"]["status"], rows["A (Europe).zip"]["output"]) == (
        "unwrap",
        "A (Europe).rvz",
    )
    b = rows["B (Europe).zip"]
    assert (b["status"], b["recipe"], b["output"]) == ("make rvz", "archive-disc", "B (Europe).rvz")
    c = rows["C (Europe).iso"]
    assert (c["status"], c["disc_mode"], c["output"]) == ("make rvz", "rvz", "C (Europe).rvz")
    assert rows["D (Europe).wbfs"]["status"] == "flagged"
    assert "stripped" in rows["E (Europe).nkit.iso"]["note"]
    assert rows["F (Europe).rvz"]["status"] == "done"


def test_dvd_platforms_make_dvd_chds_from_isos(folder_of):
    client, folder = folder_of("ps2")
    (folder / "A (USA).iso").write_bytes(b"\0" * 2048)
    (folder / "B (USA).cue").write_text('FILE "B (USA).bin" BINARY\n  TRACK 01 MODE2/2352\n')
    (folder / "B (USA).bin").write_bytes(b"\0" * 2352)
    rows = proposals(client, "ps2")
    assert (rows["A (USA).iso"]["status"], rows["A (USA).iso"]["disc_mode"]) == (
        "make chd",
        "createdvd",
    )
    assert (rows["B (USA).cue"]["status"], rows["B (USA).cue"]["disc_mode"]) == (
        "make chd",
        "createcd",
    )

    client, folder = folder_of("psp")
    (folder / "P (USA).iso").write_bytes(b"\0" * 2048)
    (folder / "Q (USA).cso").write_bytes(b"CISO")
    rows = proposals(client, "psp")
    assert rows["P (USA).iso"]["disc_mode"] == "createdvd"
    assert rows["Q (USA).cso"]["status"] == "flagged"


@pytest.mark.skipif(shutil.which("chdman") is None, reason="chdman is not installed")
def test_a_dvd_iso_becomes_a_verified_chd(folder_of, roms_root):
    client, folder = folder_of("ps2")
    image = os.urandom(DVD_SECTOR * SECTORS)
    (folder / "A (USA).iso").write_bytes(image)
    proposals(client, "ps2")
    plan = client.post("/api/folders/ps2/convert/preview", json={}).json()
    client.post("/api/folders/ps2/convert", json={"token": plan["token"]})
    for _ in range(5000):
        run = client.get("/api/folders/ps2/run").json()
        if run and run["status"] != "running":
            break
    assert (run["status"], run["message"]) == ("done", "1 file converted"), run["failed"]
    assert (folder / "A (USA).chd").is_file() and not (folder / "A (USA).iso").exists()
    assert (roms_root / "discarded/ps2/originals/A (USA).iso").read_bytes() == image


def test_an_rvz_is_known_by_its_disc_header(tmp_path):
    import struct

    from g1r.hashing import RVZ_HEADERS, RVZ_TAG, rvz_identity

    def rvz(game_id: bytes, disc: int) -> bytes:
        return struct.pack(
            RVZ_HEADERS,
            RVZ_TAG,
            1,
            1,
            0,
            b"\0" * 20,
            4699979776,
            1,
            b"\0" * 20,
            1,
            5,
            5,
            131072,
            game_id,
            disc,
            0,
        )

    (tmp_path / "a.rvz").write_bytes(rvz(b"RF4P6M", 0) + b"one way")
    (tmp_path / "b.rvz").write_bytes(rvz(b"RF4P6M", 0) + b"another")
    (tmp_path / "c.rvz").write_bytes(rvz(b"RF4P6M", 1))
    assert rvz_identity(tmp_path / "a.rvz") == rvz_identity(tmp_path / "b.rvz")
    assert rvz_identity(tmp_path / "a.rvz") != rvz_identity(tmp_path / "c.rvz")
    (tmp_path / "d.rvz").write_bytes(b"WIA\x01")
    assert rvz_identity(tmp_path / "d.rvz") is None
