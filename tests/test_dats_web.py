from http import HTTPStatus
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from g1r.library import LibraryStore
from g1r.web.app import create_app

DATA = Path(__file__).parent / "data"


@pytest.fixture
def setup(make_settings):
    settings = make_settings()
    libretro = (DATA / "nes-libretro.dat").read_bytes()
    with TestClient(create_app(settings, fetch=lambda url: libretro)) as client:
        yield client, LibraryStore(settings)


def test_dats_page_lists_enabled_platforms(setup):
    client, _ = setup
    page = client.get("/settings/dats").text
    assert 'id="nes"' in page and 'id="gb"' in page and 'id="psx"' not in page
    assert "DAT-o-MATIC" in page


def test_download_then_upload_then_activate(setup):
    client, store = setup
    response = client.post("/dats/nes/download", follow_redirects=False)
    assert response.status_code == HTTPStatus.SEE_OTHER
    page = client.get("/settings/dats").text
    assert "identification only" in page and "2026.10.07" in page
    files = {"file": ("nes.dat", (DATA / "nes-nointro.dat").read_bytes())}
    client.post("/dats/nes/upload", files=files)
    assert store.load().dats["nes"].source == "libretro"
    version_ids = [
        line.split('value="')[1].split('"')[0]
        for line in client.get("/settings/dats").text.splitlines()
        if 'name="version_id"' in line
    ]
    client.post("/dats/nes/activate", data={"version_id": version_ids[0]})
    assert store.load().dats["nes"].source == "nointro"


def test_errors_are_shown(setup):
    client, _ = setup
    page = client.post("/dats/nes/upload", files={"file": ("x.dat", b"junk")}).text
    assert "not a usable DAT" in page


def test_pin_toggle(setup):
    client, store = setup
    client.post("/dats/nes/download")
    client.post("/dats/nes/pin", data={"pinned": "on"})
    assert store.load().dats["nes"].pinned
    client.post("/dats/nes/pin", data={})
    assert not store.load().dats["nes"].pinned
