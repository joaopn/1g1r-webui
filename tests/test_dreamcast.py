import os
import zipfile
from http import HTTPStatus
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from g1r import discs, igir
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


def test_cdi_images_are_kept_as_they_are(dc, roms_root):
    client, folder = dc
    (folder / "Homebrew (2020)(Dev).cdi").write_bytes(b"cdi")
    with zipfile.ZipFile(folder / "Indie [CDI].zip", "w") as z:
        z.writestr("Indie.cdi", b"cdi image")
        z.writestr("Indie.url", b"[InternetShortcut]")
    scan(client)
    found = rows(client)
    for name in ("Homebrew (2020)(Dev).cdi", "Indie [CDI].zip"):
        assert found[name]["status"] == "accepted", found[name]
        assert found[name]["output"] is None
        assert "never converted" in found[name]["note"]
    assert client.get("/api/folders/dc").json()["unsupported"] == []
    unmatched = {f["rel_path"] for f in client.get("/api/folders/dc/unmatched").json()}
    assert unmatched == {"Homebrew (2020)(Dev).cdi", "Indie [CDI].zip"}
    assert client.post("/api/folders/dc/convert/preview", json={}).json()["conversions"] == []


def dc_dat(names: list[str]) -> bytes:
    games = "".join(
        f'<game name="{n}"><rom name="{n}.bin" size="1" crc="{i:08x}"/></game>'
        for i, n in enumerate(names)
    )
    return (
        f"<?xml version='1.0'?><datafile><header><name>Sega - Dreamcast</name></header>"
        f"{games}</datafile>"
    ).encode()


@pytest.fixture
def identified(make_settings, roms_root):
    """A Dreamcast folder whose files igir identifies as `found` says (path -> DAT game)."""
    folder = roms_root / "dc"
    folder.mkdir()
    (roms_root / "discarded").mkdir()
    found: dict[str, str] = {}

    def report(settings_, dat_file, input_dir, **_):
        return [igir.ReportRow(g, "FOUND", (str(input_dir / p),)) for p, g in found.items()]

    settings = make_settings({"grouping": {"retool_clonelists_dir": "/nonexistent"}})
    with TestClient(create_app(settings, report_runner=report)) as client:
        body = {"platform": "dc", "mount": "roms", "path": "dc", "label": "dc"}
        assert client.post("/api/folders", json=body).status_code == HTTPStatus.CREATED
        yield client, folder, found


def games(client):
    return {g["name"]: g for g in client.get("/api/folders/dc/games").json()}


def proposed(game):
    return {v["rel_path"]: v["discard_reason"] for v in game["versions"]}


def zipped_gdi(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("disc.gdi", "1\n1 0 4 2352 disc.bin 0\n")
        z.writestr("disc.bin", path.name)


def test_a_cdi_is_never_discarded_for_a_disc_nor_the_reason_one_is(identified):
    client, folder, found = identified
    names = ["Game (USA)", "Game (Europe)", "Game (Japan)", "Other (USA)", "Other (Japan)"]
    client.post("/api/dats/dc/upload", files={"file": ("dc.dat", dc_dat(names))})
    zipped_gdi(folder / "Game (USA).zip")
    zipped_gdi(folder / "Game (Europe).zip")
    (folder / "Game (Japan).cdi").write_bytes(b"rip")
    (folder / "Other (USA).cdi").write_bytes(b"usa")
    (folder / "Other (Japan).cdi").write_bytes(b"jpn")
    found.update(
        {f"{n}.{'cdi' if n.startswith('Other') or 'Japan' in n else 'zip'}": n for n in names}
    )
    scan(client)
    by_name = games(client)
    # The discs are ranked among themselves; the CDI of the same game stays.
    game = by_name["Game"]
    assert (game["status"], game["kept"]) == ("decided", "Game (USA).zip")
    assert proposed(game) == {
        "Game (USA).zip": None,
        "Game (Europe).zip": "1g1r",
        "Game (Japan).cdi": None,
    }
    # CDIs identified by checksum, with no disc of their game: ranked like any version.
    other = by_name["Other"]
    assert (other["status"], other["kept"]) == ("decided", "Other (USA).cdi")
    assert proposed(other) == {"Other (USA).cdi": None, "Other (Japan).cdi": "1g1r"}


def test_a_cdi_matched_by_name_is_never_discarded(identified):
    client, folder, found = identified
    names = ["Other (USA)", "Other (Japan)"]
    client.post("/api/dats/dc/upload", files={"file": ("dc.dat", dc_dat(names))})
    (folder / "Other (USA).cdi").write_bytes(b"usa")
    (folder / "my rip.cdi").write_bytes(b"rip")
    found["Other (USA).cdi"] = "Other (USA)"
    scan(client)
    body = {"rel_path": "my rip.cdi", "game_name": "Other (Japan)"}
    assert client.put("/api/folders/dc/assign", json=body).status_code == HTTPStatus.OK
    scan(client)
    other = games(client)["Other"]
    assert other["kept"] == "Other (USA).cdi"
    assert proposed(other) == {"Other (USA).cdi": None, "my rip.cdi": None}
