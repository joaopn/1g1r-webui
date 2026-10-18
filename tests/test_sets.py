from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient

from g1r import automatch
from g1r.web.app import create_app

# The maintainer's own romset folders (RomM names), 2026-10-16.
MAINTAINER = {
    "3ds": "3ds", "amiga": "amiga", "atari2600": "atari2600", "atari5200": "atari5200",
    "atari7800": "atari7800", "c64": "c64", "colecovision": "colecovision", "dc": "dc",
    "gamegear": "gamegear", "gb": "gb", "gba": "gba", "gbc": "gbc", "genesis": "genesis",
    "jaguar": "jaguar", "lynx": "lynx", "n64": "n64", "nds": "nds", "neo-geo-cd": "neo-geo-cd",
    "neo-geo-pocket": "neo-geo-pocket", "neo-geo-pocket-color": "neo-geo-pocket-color",
    "neogeomvs": "neogeomvs", "nes": "nes", "ps2": "ps2", "psp": "psp", "psx": "psx",
    "saturn": "saturn", "segacd": "segacd", "sega32": "sega32", "sms": "sms", "snes": "snes",
    "switch": "switch", "tg16": "tg16", "virtualboy": "virtualboy", "wonderswan": "wonderswan",
    "wonderswan-color": "wonderswan-color", "wii": "wii",
}  # fmt: skip


@pytest.fixture
def matcher(make_settings):
    settings = make_settings()
    return automatch.Matcher(
        settings.platforms.enabled_profiles(), settings.folders.unsupported_names
    )


def test_every_platform_name_belongs_to_one_platform(matcher):
    assert matcher.ambiguous == {}


def test_folder_names_are_matched_exactly(matcher):
    for name, platform in MAINTAINER.items():
        assert matcher.match(name).platform == platform, name
    # ES-DE / Batocera folders, display names, No-Intro / Redump DAT names, any case.
    others = {
        "megadrive": "genesis", "MasterSystem": "sms", "pcengine": "tg16", "gc": "ngc",
        "Dreamcast": "dc", "Nintendo 64": "n64", "Nintendo - Game Boy": "gb",
        "Sony - PlayStation": "psx", "sega32x": "sega32", "wswanc": "wonderswan-color",
    }  # fmt: skip
    for name, platform in others.items():
        assert matcher.match(name).platform == platform, name
    vita = matcher.match("psvita")
    assert vita.platform is None and vita.note == "PlayStation Vita is not supported yet"
    assert matcher.match("atari-jaguar-cd").note == "Atari Jaguar CD is not supported yet"
    # Never a guess: a near name is not a match.
    assert matcher.match("Mega Drive Hacks").platform is None
    assert matcher.match("misc").platform is None


@pytest.fixture
def library(make_settings, roms_root):
    (roms_root / "discarded").mkdir()
    for name in ("nes", "Mega Drive", "psvita", "misc", "gb", "other/nes"):
        (roms_root / "roms" / name).mkdir(parents=True)
    (roms_root / "roms" / "nes" / "Game (USA).zip").write_bytes(b"z")
    with TestClient(create_app(make_settings(), report_runner=lambda *a: [])) as client:
        body = {"platform": "gb", "mount": "roms", "path": "roms/gb", "label": "gb"}
        assert client.post("/api/folders", json=body).status_code == HTTPStatus.CREATED
        # A set elsewhere already uses the label "nes".
        body = {"platform": "nes", "mount": "roms", "path": "roms/other/nes", "label": "nes"}
        assert client.post("/api/folders", json=body).status_code == HTTPStatus.CREATED
        yield client


def test_a_folders_subfolders_come_with_their_platform_and_a_free_label(library):
    data = library.get("/api/set-candidates", params={"mount": "roms", "path": "roms"}).json()
    rows = {r["name"]: r for r in data["rows"]}
    assert (rows["nes"]["platform"], rows["nes"]["label"], rows["nes"]["items"]) == (
        "nes",
        "nes-2",
        1,
    )
    assert (rows["Mega Drive"]["platform"], rows["Mega Drive"]["label"]) == (
        "genesis",
        "mega-drive",
    )
    assert rows["psvita"]["platform"] is None and "not supported yet" in rows["psvita"]["note"]
    assert rows["misc"]["platform"] is None
    # A folder already a set, or holding one, cannot be another.
    assert rows["gb"]["problem"] == "that folder is already added as 'gb'"
    assert "may not be nested" in rows["other"]["problem"]


def test_sets_are_added_together_or_not_at_all(library):
    bad = library.post(
        "/api/sets",
        json={
            "mount": "roms",
            "sets": [
                {"path": "roms/nes", "platform": "nes", "label": "nes-2"},
                {"path": "roms/Mega Drive", "platform": "genesis", "label": "nes-2"},
                {"path": "roms/gb", "platform": "gb", "label": "gb-2"},
            ],
        },
    )
    assert bad.status_code == HTTPStatus.BAD_REQUEST
    problems = {p["rel_path"]: p["problem"] for p in bad.json()["detail"]["problems"]}
    assert problems == {
        "roms/Mega Drive": "the label 'nes-2' is already used",
        "roms/gb": "that folder is already added as 'gb'",
    }
    assert [f["label"] for f in library.get("/api/folders").json()] == ["gb", "nes"]

    ok = library.post(
        "/api/sets",
        json={
            "mount": "roms",
            "sets": [
                {"path": "roms/nes", "platform": "nes", "label": "nes-2"},
                {"path": "roms/Mega Drive", "platform": "genesis", "label": "mega-drive"},
            ],
        },
    )
    assert ok.status_code == HTTPStatus.CREATED
    assert [f["label"] for f in ok.json()] == ["nes-2", "mega-drive"]
    labels = [f["label"] for f in library.get("/api/folders").json()]
    assert labels == ["gb", "nes", "nes-2", "mega-drive"]


def test_a_set_can_be_hidden_and_removed(library, roms_root):
    hidden = library.put("/api/folders/gb/hidden", json={"hidden": True}).json()
    assert hidden["hidden"] is True
    sets = {f["label"]: f for f in library.get("/api/folders").json()}
    assert sets["gb"]["hidden"] is True and sets["nes"]["hidden"] is False
    # Hidden, it is still a set: its folder cannot be added again.
    rows = library.get("/api/set-candidates", params={"mount": "roms", "path": "roms"}).json()
    assert {r["name"]: r for r in rows["rows"]}["gb"]["problem"] is not None
    assert library.delete("/api/folders/gb").status_code == HTTPStatus.NO_CONTENT
    assert [f["label"] for f in library.get("/api/folders").json()] == ["nes"]
    # Removing a set touches no file.
    assert (roms_root / "roms" / "gb").is_dir()
