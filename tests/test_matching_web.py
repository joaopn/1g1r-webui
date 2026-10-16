from http import HTTPStatus
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from g1r import igir
from g1r.library import FolderEntry, LibraryStore
from g1r.web.app import create_app

from .test_scanner import write_zip

NAMES = ["Contra (USA)", "Contra (Japan)", "Gradius (USA)", "Gradius (USA) (Rev 1)", "Solo (Japan)"]


def dat_bytes():
    games = "".join(
        f'<game name="{n}"><rom name="{n}.nes" size="1" crc="{i:08x}"/></game>'
        for i, n in enumerate(NAMES)
    )
    return (
        f"<?xml version='1.0'?><datafile><header><name>Nintendo - Nintendo Entertainment "
        f"System</name></header>{games}</datafile>"
    ).encode()


@pytest.fixture
def env(make_settings, roms_root):
    folder = roms_root / "nes"
    folder.mkdir()
    for n in NAMES:
        write_zip(folder / f"{n}.zip", f"{n}.nes", b"x")
    settings = make_settings(
        {"grouping": {"retool_clonelists_dir": str(Path(__file__).parent / "data" / "none")}}
    )
    store = LibraryStore(settings)
    store.update(
        lambda lib: lib.folders.append(
            FolderEntry(label="nes", platform="nes", mount="roms", path="nes")
        )
    )

    def report(settings_, dat_file, input_dir):
        return [igir.ReportRow(n, "FOUND", (str(input_dir / f"{n}.zip"),)) for n in NAMES]

    with TestClient(create_app(settings, report_runner=report)) as client:
        client.post("/dats/nes/upload", files={"file": ("nes.dat", dat_bytes())})
        client.post("/folders/nes/scan")
        for _ in range(200):
            if client.get("/folders/nes/scan-status", params={"polling": "true"}).headers.get(
                "HX-Refresh"
            ):
                break
        yield client, store


def test_table_shows_groups_decisions_and_proposals(env):
    client, _ = env
    page = client.get("/section/matching/nes").text
    assert "Contra" in page and "Gradius" in page and "Solo" in page
    assert "→ " in page and "discarded/nes/1g1r/Contra (Japan).zip" in page
    assert "undecided" in page  # Gradius (USA) vs (Rev 1): revision is off by default
    games = client.get("/folders/nes/games", params={"view": "undecided"}).text
    assert "Gradius" in games and "Contra (Japan).zip" not in games


def test_keep_tick_overrides_and_reset(env):
    client, _ = env
    fragment = client.post(
        "/folders/nes/keep", data={"group_key": "name:Gradius", "rel_path": "Gradius (USA).zip"}
    ).text
    assert "your pick" in fragment and "discarded/nes/1g1r/Gradius (USA) (Rev 1).zip" in fragment
    fragment = client.post(
        "/folders/nes/keep", data={"group_key": "name:Gradius", "rel_path": ""}
    ).text
    assert "undecided" in fragment


def test_leave_alone_removes_proposals(env):
    client, _ = env
    fragment = client.post(
        "/folders/nes/leave", data={"group_key": "name:Contra", "left": "on"}
    ).text
    assert "left alone" in fragment and "→ " not in fragment
    assert "Contra" in client.get("/folders/nes/games", params={"view": "left"}).text


def test_folder_ranking_is_saved_and_applied(env):
    client, store = env
    response = client.post(
        "/folders/nes/ranking",
        data={
            "pos-prerelease": "1",
            "pos-region": "2",
            "pos-revision": "3",
            "regions": "World, USA, Europe, Japan",
            "languages": "En",
            "multi_region": "best",
        },
        follow_redirects=False,
    )
    assert response.status_code == HTTPStatus.SEE_OTHER
    assert store.load().folder("nes").ranking.criteria == ["prerelease", "region", "revision"]
    games = client.get("/folders/nes/games", params={"q": "gradius"}).text
    assert "discarded/nes/1g1r/Gradius (USA).zip" in games
    client.post("/folders/nes/ranking", data={"reset": "1"})
    assert store.load().folder("nes").ranking is None


def test_search_and_pages(env):
    client, _ = env
    assert "Solo" not in client.get("/folders/nes/games", params={"q": "contra"}).text
    assert client.get("/folders/missing/games").status_code == HTTPStatus.NOT_FOUND


def test_home_shows_a_card_per_folder(env):
    client, _ = env
    page = client.get("/").text
    assert "games with several versions" in page and "proposed moves" in page
    assert 'href="/section/matching/nes?view=undecided"' in page
