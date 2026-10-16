from http import HTTPStatus
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from g1r import igir
from g1r.library import LibraryStore
from g1r.web.api import suggest_label
from g1r.web.app import create_app

from .test_scanner import write_zip

DATA = Path(__file__).parent / "data"
NAMES = ["Contra (USA)", "Contra (Japan)", "Gradius (USA)", "Gradius (USA) (Rev 1)", "Solo (Japan)"]


def dat_bytes(names=NAMES):
    games = "".join(
        f'<game name="{n}"><rom name="{n}.nes" size="1" crc="{i:08x}"/></game>'
        for i, n in enumerate(names)
    )
    return (
        f"<?xml version='1.0'?><datafile><header><name>Nintendo - Nintendo Entertainment "
        f"System</name></header>{games}</datafile>"
    ).encode()


@pytest.fixture
def setup(make_settings, roms_root):
    folder = roms_root / "NES Set"
    folder.mkdir()
    for n in NAMES:
        write_zip(folder / f"{n}.zip", f"{n}.nes", b"x")
    (folder / "odd.nes").write_bytes(b"?")
    (folder / "metadata.txt").write_text("x")
    (roms_root / "gb").mkdir()
    (roms_root / "discarded").mkdir()
    settings = make_settings({"grouping": {"retool_clonelists_dir": str(DATA / "none")}})
    libretro = (DATA / "nes-libretro.dat").read_bytes()

    def report(settings_, dat_file, input_dir):
        return [igir.ReportRow(n, "FOUND", (str(input_dir / f"{n}.zip"),)) for n in NAMES]

    app = create_app(settings, fetch=lambda url: libretro, report_runner=report)
    with TestClient(app) as client:
        yield client, LibraryStore(settings), settings


def add_nes(client, **extra):
    return client.post(
        "/api/folders",
        json={"platform": "nes", "mount": "roms", "path": "NES Set", "label": ""} | extra,
    )


def scanned(client):
    assert add_nes(client, label="nes").status_code == HTTPStatus.CREATED
    client.post("/api/dats/nes/upload", files={"file": ("nes.dat", dat_bytes())})
    assert client.post("/api/folders/nes/scan").status_code == HTTPStatus.ACCEPTED
    for _ in range(500):
        scan = client.get("/api/folders/nes/scan").json()
        if scan and scan["status"] != "running":
            return scan
    raise AssertionError("scan did not finish")


def test_suggest_label():
    assert suggest_label("roms/NES Set (No-Intro)") == "nes-set-no-intro"


def test_meta_lists_enabled_platforms_and_ui_config(setup):
    client, _, _ = setup
    meta = client.get("/api/meta").json()
    assert "nes" in meta["platforms"] and "psx" not in meta["platforms"]
    assert (
        meta["platforms"]["gb"]["short"] == "GB" and meta["platforms"]["gb"]["kind"] == "handheld"
    )
    assert meta["ui"]["sidebar"]["width_rem"] > 0
    assert set(meta["ui"]["game_columns_default"]) <= set(meta["ui"]["game_columns"])
    assert meta["ranking"]["default"]["criteria"] == ["prerelease", "region"]


def test_browse_and_mounts(setup):
    client, _, _ = setup
    assert client.get("/api/mounts").json()[0]["id"] == "roms"
    listing = client.get("/api/browse", params={"mount": "roms", "path": ""}).json()
    assert listing["children"] == ["gb", "NES Set"]
    assert client.get("/api/browse", params={"path": "../x"}).status_code == HTTPStatus.BAD_REQUEST


def test_add_folder_rules(setup):
    client, store, _ = setup
    created = add_nes(client)
    assert created.status_code == HTTPStatus.CREATED and created.json()["label"] == "nes-set"
    for body, message in [
        ({"platform": "psx"}, "supported platform"),
        ({"path": ""}, "not the mount itself"),
        ({"path": "../x"}, "may not contain"),
        ({"path": "gb", "label": "Bad Label"}, "lowercase"),
        ({"path": "missing"}, "does not exist"),
        ({"label": "other"}, "already added"),
        ({"path": "gb", "label": "nes-set"}, "already used"),
    ]:
        response = add_nes(client, **body)
        assert response.status_code == HTTPStatus.BAD_REQUEST, body
        assert message in response.json()["detail"], body
    assert [f.label for f in store.load().folders] == ["nes-set"]
    assert client.delete("/api/folders/nes-set").status_code == HTTPStatus.NO_CONTENT
    assert store.load().folders == []


def test_settings_targets_and_ignored(setup):
    client, store, _ = setup
    assert client.get("/api/settings").json()["targets"]["nes"] == "zip"
    assert (
        client.put("/api/settings/targets", json={"targets": {"nes": "plain"}}).json()["targets"][
            "nes"
        ]
        == "plain"
    )
    assert (
        client.put("/api/settings/targets", json={"targets": {"nes": "chd"}}).status_code
        == HTTPStatus.BAD_REQUEST
    )
    client.put("/api/settings/ignored", json={"patterns": ["foo.txt", " ", "*.bak "]})
    assert store.load().ignored_filenames == ["foo.txt", "*.bak"]


def test_dats_download_upload_activate_pin(setup):
    client, store, _ = setup
    first = client.post("/api/dats/nes/download").json()["version_id"]
    second = client.post(
        "/api/dats/nes/upload", files={"file": ("nes.dat", (DATA / "nes-nointro.dat").read_bytes())}
    ).json()["version_id"]
    row = next(r for r in client.get("/api/dats").json() if r["platform"] == "nes")
    assert row["active"]["id"] == first and len(row["versions"]) == 2
    client.put("/api/dats/nes/pin", json={"pinned": True})
    assert (
        client.put("/api/dats/nes/active", json={"version_id": second}).status_code
        == HTTPStatus.BAD_REQUEST
    )
    client.put("/api/dats/nes/pin", json={"pinned": False})
    client.put("/api/dats/nes/active", json={"version_id": second})
    assert store.load().dats["nes"].source == "nointro"
    bad = client.post("/api/dats/nes/upload", files={"file": ("x.dat", b"junk")})
    assert bad.status_code == HTTPStatus.BAD_REQUEST and "not a usable DAT" in bad.json()["detail"]


def test_scan_and_folder_detail(setup):
    client, _, _ = setup
    scan = scanned(client)
    assert scan["status"] == "done" and scan["message"] == "5 of 6 ROM files identified"
    detail = client.get("/api/folders/nes").json()
    assert detail["summary"]["unmatched"] == 1
    assert [f["rel_path"] for f in detail["unmatched"]] == ["odd.nes"]
    assert [f["rel_path"] for f in detail["others"]] == ["metadata.txt"]
    assert client.get("/api/folders/missing").status_code == HTTPStatus.NOT_FOUND


def test_games_keep_leave_and_ranking(setup):
    client, store, _ = setup
    scanned(client)
    games = {g["name"]: g for g in client.get("/api/folders/nes/games").json()}
    assert games["Contra"]["status"] == "decided" and games["Contra"]["kept"] == "Contra (USA).zip"
    assert games["Gradius"]["status"] == "undecided" and games["Gradius"]["kept"] is None
    assert games["Solo"]["status"] == "single"
    version = games["Contra"]["versions"][0]
    assert {"regions", "languages", "revision", "size", "probability", "operation"} <= set(version)
    picked = client.put(
        "/api/folders/nes/keep", json={"group_key": "name:Gradius", "rel_path": "Gradius (USA).zip"}
    ).json()
    assert picked["status"] == "your pick" and picked["kept"] == "Gradius (USA).zip"
    reset = client.put(
        "/api/folders/nes/keep", json={"group_key": "name:Gradius", "rel_path": None}
    ).json()
    assert reset["status"] == "undecided"
    left = client.put(
        "/api/folders/nes/leave", json={"group_key": "name:Contra", "left": True}
    ).json()
    assert left["status"] == "left alone" and all(v["operation"] is None for v in left["versions"])
    ranking = {
        "criteria": ["prerelease", "region", "revision"],
        "regions": ["World", "USA"],
        "languages": ["En"],
        "multi_region": "best",
    }
    assert (
        client.put("/api/folders/nes/ranking", json={"ranking": ranking}).json()["criteria"][-1]
        == "revision"
    )
    games = {g["name"]: g for g in client.get("/api/folders/nes/games").json()}
    assert games["Gradius"]["kept"] == "Gradius (USA) (Rev 1).zip"
    assert (
        client.put(
            "/api/folders/nes/ranking", json={"ranking": {**ranking, "criteria": ["bogus"]}}
        ).status_code
        == HTTPStatus.UNPROCESSABLE_ENTITY
    )
    client.put("/api/folders/nes/ranking", json={"ranking": None})
    assert store.load().folder("nes").ranking is None
    home = client.get("/api/folders").json()[0]
    assert home["counts"]["several"] == 2 and home["summary"]["identified"] == 5


def test_healthz(setup):
    client, _, _ = setup
    assert client.get("/healthz").json()["schema_version"] >= 1


def test_web_app_served_with_fallback(make_settings, tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><div id=root></div>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    (dist / "favicon.svg").write_text("<svg/>")
    settings = make_settings({"paths": {"web_dist": str(dist)}})
    with TestClient(create_app(settings)) as client:
        assert (
            "id=root" in client.get("/folders/nes/matching", headers={"accept": "text/html"}).text
        )
        assert client.get("/assets/app.js").text == "console.log(1)"
        assert client.get("/assets/missing.js").status_code == HTTPStatus.NOT_FOUND
        assert client.get("/favicon.svg").text == "<svg/>"
        assert client.get("/api/nope").status_code == HTTPStatus.NOT_FOUND
        assert client.get("/api/meta").status_code == HTTPStatus.OK


def test_conversion_proposals_and_delete_originals(setup):
    client, _, _ = setup
    scanned(client)
    body = client.get("/api/folders/nes/conversion").json()
    rows = {r["rel_path"]: r for r in body["rows"]}
    assert rows["Contra (USA).zip"]["status"] == "done"
    wrap = rows["odd.nes"]
    assert (wrap["status"], wrap["output"], wrap["reversible"]) == ("wrap", "odd.zip", True)
    assert body["counts"]["to_convert"] == 1
    assert client.get("/api/folders").json()[0]["conversion"]["to_convert"] == 1

    saved = client.put("/api/folders/nes/conversion", json={"delete_originals": True})
    assert saved.json()["delete_originals"] is True
    wrap = next(r for r in client.get("/api/folders/nes/conversion").json()["rows"] if r["output"])
    assert wrap["originals_to"] is None and wrap["reversible"] is False
