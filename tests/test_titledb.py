import json
from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient

from g1r import db, titledb
from g1r.dat_registry import DatRegistry
from g1r.dats import parse_dat_bytes
from g1r.library import LibraryStore
from g1r.web.app import create_app
from tests.test_switch import BASE_ID, DLC_ID, FIRST_UPDATE, UPDATE_ID, nsp

JP_ONLY_ID = "0100CCCC00010000"
UNLISTED_ID = "0100DDDD00010000"

LANGUAGES = {"US": ["en", "es"], "JP": ["ja", "en"], "GB": ["en"], "XX": [7]}
US = {
    "70010000000001": {
        "id": BASE_ID.lower(),
        "name": "Super Game™: [Deluxe]",
        "publisher": "Big Publisher",
        "releaseDate": 20190315,
        "languages": ["en", "fr", "en"],
        "isDemo": False,
    },
    # The same title ID again (another shop page): the first one names it.
    "70010000000002": {"id": BASE_ID, "name": "Super Game Bundle"},
    "70010000000003": {"id": DLC_ID, "name": "Super Game: Pack", "releaseDate": None},
    # A shop page without a title ID, and one without a name.
    "70010000000004": {"id": None, "name": "A bundle"},
    "70010000000005": {"id": "0100EEEE00010000", "name": ""},
    "70010000000006": {"id": "0100FFFF00010000", "name": "Demo Game", "isDemo": True},
}
JP = {
    "70010000000101": {"id": BASE_ID, "name": "Super Game JP", "publisher": "JP Publisher"},
    "70010000000102": {"id": JP_ONLY_ID, "name": "Japan Game", "languages": ["ja"]},
}


def body(data) -> bytes:
    return json.dumps(data).encode()


def test_a_region_file_becomes_a_dat_of_its_title_ids(make_settings):
    config = make_settings().titledb
    data, count = titledb.to_dat(config, "US.en", body(US), "2026-10-24")
    dat = parse_dat_bytes(data)
    assert count == len(dat.games) == 3
    assert dat.header.name == "titledb US.en" and dat.header.version == "2026-10-24"
    games = {g.id: g for g in dat.games}
    base = games[BASE_ID]
    # Marks dropped, brackets made parentheses (they end a stored name), first entry kept.
    assert base.name == "Super Game: (Deluxe)"
    assert (base.manufacturer, base.year, base.languages) == (
        "Big Publisher",
        "2019-03-15",
        "en,fr",
    )
    assert base.category == "Games" and base.roms == []
    assert games["0100FFFF00010000"].category == "Demo"
    assert games[DLC_ID].year is None
    with pytest.raises(titledb.TitleDbError):
        titledb.to_dat(config, "US.en", b"[]", "x")
    with pytest.raises(titledb.TitleDbError):
        titledb.to_dat(config, "US.en", body({"1": {"id": None, "name": "x"}}), "x")


def test_the_file_list_comes_from_the_languages_map(make_settings):
    config = make_settings().titledb
    files = titledb.files_from_languages(config, body(LANGUAGES))
    assert files == ["GB.en", "JP.en", "JP.ja", "US.en", "US.es"]
    with pytest.raises(titledb.TitleDbError):
        titledb.files_from_languages(config, b"[1]")


@pytest.fixture
def switch(make_settings, roms_root):
    folder = roms_root / "switch"
    folder.mkdir()
    (roms_root / "discarded").mkdir()
    files = {
        "base.nsp": nsp(make_settings, BASE_ID, 0, "Application"),
        "update.nsp": nsp(make_settings, UPDATE_ID, FIRST_UPDATE),
        "pack.nsp": nsp(make_settings, DLC_ID, 0, "AddOnContent"),
        "jp.nsp": nsp(make_settings, JP_ONLY_ID, 0, "Application"),
        "Unlisted Game.nsp": nsp(make_settings, UNLISTED_ID, 0, "Application"),
    }
    for name, data in files.items():
        (folder / name).write_bytes(data)
    fetched = []

    def fetch(url, timeout=None):
        fetched.append(url)
        for name, data in (("languages", LANGUAGES), ("US.en", US), ("JP.ja", JP)):
            if url.endswith(f"/{name}.json"):
                return body(data)
        raise OSError(f"no such file: {url}")

    app = create_app(make_settings(), fetch=fetch, report_runner=lambda *a, **_: [])
    with TestClient(app) as client:
        new = {"platform": "switch", "mount": "roms", "path": "switch", "label": "switch"}
        assert client.post("/api/folders", json=new).status_code == HTTPStatus.CREATED
        yield client, fetched


def scan(client) -> dict:
    client.post("/api/folders/switch/scan")
    for _ in range(500):
        found = client.get("/api/folders/switch/scan").json()
        if found["status"] != "running":
            return found
    raise AssertionError("the scan did not finish")


def versions(client) -> dict[str, dict]:
    games = client.get("/api/folders/switch/games").json()
    return {v["rel_path"]: v | {"game": g["name"]} for g in games for v in g["versions"]}


def card(client) -> dict:
    return next(f for f in client.get("/api/folders").json() if f["label"] == "switch")


def switch_row(client) -> dict:
    return next(r for r in client.get("/api/dats").json() if r["platform"] == "switch")


def test_region_files_name_title_ids_in_their_order(switch):
    client, fetched = switch
    assert scan(client)["status"] == "done"
    # Without titledb: the file names.
    assert versions(client)["base.nsp"]["game_name"].startswith("base [")

    assert client.get("/api/titledb/files").json() == [
        "GB.en",
        "JP.en",
        "JP.ja",
        "US.en",
        "US.es",
    ]
    for file in ("US.en", "JP.ja"):
        added = client.post(f"/api/dats/switch/titledb?file={file}")
        assert added.status_code == HTTPStatus.OK
    row = switch_row(client)
    assert row["titledb"] is True
    assert [e["id"] for e in row["order"]] == ["titledb:US.en", "titledb:JP.ja", "hasheous"]
    assert [e["label"] for e in row["order"]][:2] == ["titledb US.en", "titledb JP.ja"]
    # Nothing is fetched twice for the list, and only Switch takes titledb.
    assert sum(url.endswith("/languages.json") for url in fetched) == 1
    refused = client.post("/api/dats/nes/titledb?file=US.en")
    assert refused.status_code == HTTPStatus.BAD_REQUEST
    assert client.post("/api/dats/switch/titledb?file=ZZ.zz").status_code == (
        HTTPStatus.BAD_REQUEST
    )

    assert scan(client)["message"] == "5 of 5 files identified by title ID"
    found = versions(client)
    base = found["base.nsp"]
    assert base["game"] == "Super Game: (Deluxe)"
    assert base["dat"]["label"] == "titledb US.en"
    assert (base["publisher"], base["release"], base["languages"]) == (
        "Big Publisher",
        "2019-03-15",
        ["en", "fr"],
    )
    # An update has no entry of its own: its game's name and details.
    assert found["update.nsp"]["game_name"].startswith("Super Game: (Deluxe) [")
    assert found["update.nsp"]["publisher"] == "Big Publisher"
    assert found["pack.nsp"]["game_name"].startswith("Super Game: Pack [")
    # Listed only in the second file; listed nowhere: the file name, no details.
    assert found["jp.nsp"]["game"] == "Japan Game"
    assert found["jp.nsp"]["dat"]["label"] == "titledb JP.ja"
    unlisted = found["Unlisted Game.nsp"]
    assert unlisted["game"] == "Unlisted Game" and unlisted["dat"] is None
    assert unlisted["publisher"] is None
    assert card(client)["needs"] is None

    # JP first: its names win, and the set asks for a scan.
    order = ["titledb:JP.ja", "titledb:US.en", "hasheous"]
    assert client.put("/api/dats/switch/order", json={"order": order, "off": []}).status_code == (
        HTTPStatus.OK
    )
    assert card(client)["needs"] == "identify"
    scan(client)
    assert versions(client)["base.nsp"]["game"] == "Super Game JP"
    # Switched off: the next file names it.
    off = {"order": order, "off": ["titledb:JP.ja"]}
    client.put("/api/dats/switch/order", json=off)
    scan(client)
    assert versions(client)["base.nsp"]["game"] == "Super Game: (Deluxe)"

    # titledb files are no DATs to match a file to by hand, nor Statistics sources.
    assert client.get("/api/folders/switch/dat-search?q=Super").json() == []
    stats = client.get("/api/statistics").json()
    assert all(not row["coverage"] for row in stats["folders"] if row["label"] == "switch")

    # A restart's check of the DATs' names leaves titledb files alone.
    settings = client.app.state.settings
    conn = db.open_database(settings)
    conn.execute("UPDATE dat_version SET matches_platform = 0")
    DatRegistry(settings, LibraryStore(settings)).recheck_names(conn)
    conn.close()
    assert all(v["matches_platform"] for v in switch_row(client)["versions"])

    removed = client.delete("/api/dats/sources/titledb").json()
    assert removed == {"versions": 2, "platforms": ["switch"]}
    assert [e["id"] for e in switch_row(client)["order"]] == ["hasheous"]
