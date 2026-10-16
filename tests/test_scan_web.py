from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient

from g1r import igir
from g1r.library import FolderEntry, LibraryStore
from g1r.web.app import create_app

from .test_scanner import BODY, NES_HEADER, dat_xml, write_zip


@pytest.fixture
def client(make_settings, roms_root):
    (roms_root / "nes").mkdir()
    write_zip(roms_root / "nes" / "Known (USA).zip", "Known (USA).nes", NES_HEADER + BODY)
    (roms_root / "nes" / "odd.nes").write_bytes(b"?")
    settings = make_settings()
    LibraryStore(settings).update(
        lambda lib: lib.folders.append(
            FolderEntry(label="nes", platform="nes", mount="roms", path="nes")
        )
    )

    def report(settings_, dat_file, input_dir):
        return [igir.ReportRow("Known (USA)", "FOUND", (str(input_dir / "Known (USA).zip"),))]

    with TestClient(create_app(settings, report_runner=report)) as client:
        files = {"file": ("nes.dat", dat_xml({"Known (USA)": NES_HEADER + BODY}))}
        client.post("/dats/nes/upload", files=files)
        yield client


def wait_for_scan(client):
    for _ in range(200):
        response = client.get("/folders/nes/scan-status", params={"polling": "true"})
        if response.headers.get("HX-Refresh"):
            return
    raise AssertionError("scan did not finish")


def test_scan_from_the_folder_page(client):
    page = client.get("/section/matching/nes").text
    assert "Not scanned yet" in page and "Nintendo - Nintendo Entertainment System" in page
    response = client.post("/folders/nes/scan")
    assert response.status_code == HTTPStatus.OK
    wait_for_scan(client)
    page = client.get("/section/matching/nes").text
    assert "1 of 2 ROM files identified" in page
    assert "odd.nes" in page and "Unmatched content" in page


def test_scan_unknown_folder_is_404(client):
    assert client.post("/folders/nope/scan").status_code == HTTPStatus.NOT_FOUND
