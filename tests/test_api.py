from http import HTTPStatus
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from g1r import dashboard, db, hasheous, igir, matching, scanner
from g1r.library import LibraryStore
from g1r.web.api import suggest_label
from g1r.web.app import create_app

from .test_scanner import write_zip
from .waits import finished

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
        write_zip(folder / f"{n}.zip", f"{n}.nes", n.encode())
    # Zipped, as the target wants it, and in no DAT: unmatched.
    write_zip(folder / "stray.zip", "stray.nes", b"??")
    (folder / "metadata.txt").write_text("x")
    (roms_root / "gb").mkdir()
    (roms_root / "discarded").mkdir()
    settings = make_settings({"grouping": {"retool_clonelists_dir": str(DATA / "none")}})
    libretro = (DATA / "nes-libretro.dat").read_bytes()

    def report(settings_, dat_file, input_dir, **_):
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
    return finished(client, "nes")


def test_suggest_label():
    assert suggest_label("roms/NES Set (No-Intro)") == "nes-set-no-intro"


def test_meta_lists_enabled_platforms_and_ui_config(setup):
    client, _, _ = setup
    meta = client.get("/api/meta").json()
    assert "nes" in meta["platforms"] and "psvita" not in meta["platforms"]
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
        ({"platform": "psvita"}, "supported platform"),
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


def test_settings_targets(setup):
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


def test_ignore_list_per_folder_checks_the_files_again(setup, roms_root):
    """Each set has its own ignore list (patterns and exact files); saving it checks the
    files so an unsupported file leaves the warning at once."""
    client, store, settings = setup
    folder = roms_root / "NES Set"
    (folder / "cover.png").write_bytes(b"png")
    (folder / "scan.jpg").write_bytes(b"jpg")
    add_nes(client, label="nes")
    add_nes(client, label="other", path="gb")
    detail = client.get("/api/folders/nes").json()
    assert detail["ignored_patterns"] == settings.ignored_filenames
    assert detail["ignored_patterns_default"] is True

    def checked():
        finished(client, "nes")
        return client.get("/api/folders/nes").json()

    client.post("/api/folders/nes/check")
    assert {f["rel_path"] for f in checked()["unsupported"]} == {"cover.png", "scan.jpg"}

    saved = client.put(
        "/api/folders/nes/ignored",
        json={"patterns": ["*.txt", " *.jpg", "", "*.jpg"], "files": ["cover.png"]},
    ).json()
    assert saved["checking"] is True
    assert saved["ignored_patterns"] == ["*.txt", "*.jpg"]
    assert saved["ignored_files"] == ["cover.png"]
    detail = checked()
    assert detail["unsupported"] == []
    by = {f["rel_path"]: f["ignored_by"] for f in detail["others"]}
    assert by == {"cover.png": "file", "scan.jpg": "*.jpg", "metadata.txt": "*.txt"}
    # The other set keeps the default list.
    assert store.load().folder("other").ignored_patterns is None

    # Back to the default patterns.
    client.put("/api/folders/nes/ignored", json={"patterns": None, "files": []})
    assert store.load().folder("nes").ignored_patterns is None
    assert {f["rel_path"] for f in checked()["unsupported"]} == {"cover.png", "scan.jpg"}


def test_dats_download_upload_activate_pin(setup):
    client, store, _ = setup
    libretro = client.post("/api/dats/nes/download").json()["version_id"]
    nointro_dat = (DATA / "nes-nointro.dat").read_bytes()
    nointro = client.post("/api/dats/nes/upload", files={"file": ("nes.dat", nointro_dat)}).json()[
        "version_id"
    ]
    row = next(r for r in client.get("/api/dats").json() if r["platform"] == "nes")
    # The first DAT of each source joins the platform's order, complete DATs first.
    assert len(row["versions"]) == 2 and row["active"]["id"] == nointro
    assert [(e["id"], e["dat"] and e["dat"]["id"]) for e in row["order"]] == [
        ("nointro", nointro),
        ("libretro", libretro),
        ("hasheous", None),
    ]
    # A newer No-Intro DAT waits to be chosen; a pinned source refuses it.
    newer = client.post(
        "/api/dats/nes/upload",
        files={"file": ("nes.dat", nointro_dat.replace(b"</datafile>", b"<!-- v2 --></datafile>"))},
    ).json()["version_id"]
    assert store.load().dats["nes"].active["nointro"].sha1 != ""
    client.put("/api/dats/nes/pin", json={"pinned": True, "source": "nointro"})
    assert (
        client.put("/api/dats/nes/active", json={"version_id": newer}).status_code
        == HTTPStatus.BAD_REQUEST
    )
    client.put("/api/dats/nes/pin", json={"pinned": False, "source": "nointro"})
    assert client.put("/api/dats/nes/active", json={"version_id": newer}).status_code == 200
    assert store.load().dats["nes"].active["libretro"].source == "libretro"
    assert row["pages"] == []
    psx = next(r for r in client.get("/api/dats").json() if r["platform"] == "psx")
    assert [p["source"] for p in psx["pages"]] == ["nonredump"]
    assert psx["pages"][0]["url"].endswith("&s=168")
    bad = client.post("/api/dats/nes/upload", files={"file": ("x.dat", b"junk")})
    assert bad.status_code == HTTPStatus.BAD_REQUEST and "not a usable DAT" in bad.json()["detail"]


def test_dat_order_is_saved_per_platform(setup):
    client, store, _ = setup
    assert add_nes(client, label="nes").status_code == HTTPStatus.CREATED
    client.post("/api/dats/nes/download")
    client.post(
        "/api/dats/nes/upload", files={"file": ("nes.dat", (DATA / "nes-nointro.dat").read_bytes())}
    )
    order = client.put(
        "/api/dats/nes/order",
        json={"order": ["hasheous", "libretro", "nointro"], "off": ["nointro"]},
    ).json()
    assert [(e["id"], e["on"]) for e in order] == [
        ("hasheous", True),
        ("libretro", True),
        ("nointro", False),
    ]
    assert store.load().dats["nes"].order == ["hasheous", "libretro", "nointro"]
    detail = client.get("/api/folders/nes").json()
    assert detail["dat"]["source"] == "libretro"
    assert [e["id"] for e in detail["dat_order"]][:2] == ["hasheous", "libretro"]
    bad = client.put("/api/dats/nes/order", json={"order": ["nope"]})
    assert bad.status_code == HTTPStatus.BAD_REQUEST


def test_scan_and_folder_detail(setup):
    client, _, _ = setup
    scan = scanned(client)
    assert scan["status"] == "done" and scan["message"] == "5 of 6 ROM files identified"
    detail = client.get("/api/folders/nes").json()
    assert (detail["summary"]["unmatched"], detail["summary"]["waiting"]) == (1, 0)
    assert [f["rel_path"] for f in detail["unmatched"]] == ["stray.zip"]
    assert detail["convert_first"] == []
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
    # To process: the undecided game's two versions and stray.zip (unmatched).
    assert home["progress"] == {"processed": 3, "to_process": 3, "to_match": 3, "to_convert": 0}


def test_matching_waits_until_every_file_is_converted_or_discarded(setup, roms_root):
    """One target format, converted first: while a file is not in it, a scan stops after its
    check (recorded as a check) and 1G1R cannot be applied; converting it, or moving what
    cannot be converted to discarded/, lets matching go on."""
    client, _, _ = setup
    folder = roms_root / "NES Set"
    (folder / "odd.nes").write_bytes(b"?")
    write_zip(folder / "Empty.zip", "readme.txt", b"no ROM")
    scan = scanned(client)
    assert (scan["status"], scan["kind"]) == ("done", "check")
    assert scan["message"].startswith("2 files to convert or discard first")
    assert client.get("/api/folders/nes/games").json() == []
    refused = client.post("/api/folders/nes/apply/preview", json={})
    assert refused.status_code == HTTPStatus.CONFLICT and "convert or discard first" in refused.text
    detail = client.get("/api/folders/nes").json()
    assert [f["rel_path"] for f in detail["convert_first"]] == ["Empty.zip", "odd.nes"]
    assert client.get("/api/folders").json()[0]["needs"] == "identify"
    conversion_body = client.get("/api/folders/nes/conversion").json()
    assert conversion_body["cannot_convert"] == ["Empty.zip"]

    # Convert what can be converted, discard what cannot: then the scan identifies.
    plan = client.post("/api/folders/nes/convert/preview", json={}).json()
    client.post("/api/folders/nes/convert", json={"token": plan["token"]})
    assert finished(client, "nes", "run")["status"] == "done"
    aside = client.post("/api/folders/nes/set-aside/preview", json={"rel_paths": ["Empty.zip"]})
    client.post(
        "/api/folders/nes/set-aside",
        json={"rel_paths": ["Empty.zip"], "token": aside.json()["token"]},
    )
    assert finished(client, "nes", "run")["status"] == "done"
    assert client.post("/api/folders/nes/scan").status_code == HTTPStatus.ACCEPTED
    scan = finished(client, "nes")
    assert (scan["kind"], scan["message"]) == ("identify", "5 of 7 ROM files identified")


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


def test_index_is_revalidated_so_a_new_build_is_picked_up(make_settings, tmp_path):
    # A cached index.html keeps loading the previous build's hashed assets.
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><div id=root></div>")
    settings = make_settings({"paths": {"web_dist": str(dist)}})
    with TestClient(create_app(settings)) as client:
        for path in ("/", "/folders/nes/conversion", "/index.html"):
            page = client.get(path, headers={"accept": "text/html"})
            assert page.headers.get("cache-control") == "no-cache", path


def test_conversion_proposals_and_delete_originals(setup, roms_root):
    client, _, _ = setup
    (roms_root / "NES Set" / "odd.nes").write_bytes(b"?")
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


def test_unmatched_assign_and_lookup_settings(setup):
    client, _, _ = setup
    scanned(client)
    (row,) = client.get("/api/folders/nes/unmatched").json()
    assert row["rel_path"] == "stray.zip" and row["hasheous"]["status"] == "off"
    assert row["hash"]["crc32"]
    assert client.get("/api/folders/nes/dat-search", params={"q": "contra"}).json() == [
        "Contra (Japan)",
        "Contra (USA)",
    ]
    bad = client.put("/api/folders/nes/assign", json={"rel_path": "stray.zip", "game_name": "Nope"})
    assert bad.status_code == HTTPStatus.BAD_REQUEST
    ok = client.put(
        "/api/folders/nes/assign", json={"rel_path": "stray.zip", "game_name": "Solo (Japan)"}
    )
    assert ok.status_code == HTTPStatus.OK
    assert client.get("/api/folders/nes/unmatched").json() == []
    versions = [v for g in client.get("/api/folders/nes/games").json() for v in g["versions"]]
    assigned = next(v for v in versions if v["rel_path"] == "stray.zip")
    assert (assigned["method"], assigned["probability"]) == ("manual", 1)
    client.put("/api/folders/nes/assign", json={"rel_path": "stray.zip", "game_name": None})
    assert len(client.get("/api/folders/nes/unmatched").json()) == 1

    # Several at once: all checked first, so one bad entry stores nothing.
    many = "/api/folders/nes/assign-many"
    bad = client.put(
        many,
        json={
            "assignments": [
                {"rel_path": "stray.zip", "game_name": "Solo (Japan)"},
                {"rel_path": "missing.zip", "game_name": "Solo (Japan)"},
            ]
        },
    )
    assert bad.status_code == HTTPStatus.NOT_FOUND
    assert len(client.get("/api/folders/nes/unmatched").json()) == 1
    ok = client.put(
        many, json={"assignments": [{"rel_path": "stray.zip", "game_name": "Solo (Japan)"}]}
    )
    assert ok.json() == {"assigned": 1}
    assert client.get("/api/folders/nes/unmatched").json() == []
    client.put(many, json={"assignments": [{"rel_path": "stray.zip", "game_name": None}]})
    assert len(client.get("/api/folders/nes/unmatched").json()) == 1

    assert client.get("/api/settings").json()["lookups"] == {"hasheous": False}
    switched = client.put("/api/settings/lookups", json={"hasheous": True}).json()
    assert switched == {"hasheous": True}


def test_home_cards_are_kept_until_the_folder_changes(setup, monkeypatch):
    client, _, settings = setup
    scanned(client)
    built = []
    game_rows = matching.game_rows

    def counted(*args, **kwargs):
        built.append(args[2])
        return game_rows(*args, **kwargs)

    monkeypatch.setattr(matching, "game_rows", counted)
    card = client.get("/api/folders").json()[0]
    assert card["summary"]["unmatched"] == 1 and not card["running"]
    assert client.get("/api/folders").json() == [card]
    assert built == ["nes"]

    # A manual match is a write to the folder's data: the card is rebuilt.
    client.put(
        "/api/folders/nes/assign", json={"rel_path": "stray.zip", "game_name": "Solo (Japan)"}
    )
    assert client.get("/api/folders").json()[0]["summary"]["unmatched"] == 0
    assert built == ["nes", "nes"]
    client.get("/api/folders")
    assert built == ["nes", "nes"]

    # So is a change to the library (a ranking, a target, an ignored name).
    client.put(
        "/api/folders/nes/ranking",
        json={
            "ranking": {
                "criteria": ["region"],
                "regions": ["Japan"],
                "languages": ["En"],
                "multi_region": "best",
            }
        },
    )
    client.get("/api/folders")
    assert built == ["nes", "nes", "nes"]

    # An apply or a restore running: Home polls until it ends.
    conn = db.connect(settings.paths.database_path, busy_timeout_ms=0)
    conn.execute(
        "INSERT INTO apply_run (folder_label, kind, status) VALUES ('nes', 'apply', 'running')"
    )
    assert client.get("/api/folders").json()[0]["running"]


def test_discarded_listing_and_home_warnings(setup, roms_root):
    client, _, _ = setup
    scanned(client)
    empty = client.get("/api/folders/nes/discarded").json()
    assert (empty["files"], empty["reasons"]) == (0, [])
    base = roms_root / "discarded" / "nes"
    (base / "1g1r").mkdir(parents=True)
    (base / "1g1r" / "Contra (Japan).zip").write_bytes(b"12")
    (base / "1g1r" / "Gone (USA).zip").write_bytes(b"3")
    (base / "originals").mkdir()
    (base / "originals" / "odd.nes").write_bytes(b"4567")
    (base / "loose.bin").write_bytes(b"8")
    body = client.get("/api/folders/nes/discarded").json()
    assert (body["files"], body["bytes"]) == (4, 8)
    assert [r["id"] for r in body["reasons"]] == ["1g1r", "originals", ""]
    one = {f["rel_path"]: f for f in body["reasons"][0]["files"]}
    assert one["Contra (Japan).zip"]["occupied"] is True
    assert one["Gone (USA).zip"]["occupied"] is False
    assert one["Gone (USA).zip"]["restore_to"].endswith("NES Set/Gone (USA).zip")
    assert body["reasons"][2]["known"] is False

    folder = client.get("/api/folders").json()[0]
    assert folder["discarded"] == {"files": 4, "bytes": 8}
    assert folder["needs_scan"] is False
    assert folder["warnings"] == [HASHEOUS_HINT]
    (roms_root / "NES Set" / "game.sfc").write_bytes(b"x")
    client.post("/api/folders/nes/scan")
    finished(client, "nes")
    warning, hint = client.get("/api/folders").json()[0]["warnings"]
    assert warning["text"].startswith("Not NES ROMs or archives: 1 file.")
    assert hint == HASHEOUS_HINT
    new = client.post(
        "/api/dats/nes/upload", files={"file": ("nes.dat", dat_bytes([*NAMES, "New"]))}
    )
    client.put("/api/dats/nes/active", json={"version_id": new.json()["version_id"]})
    card = client.get("/api/folders").json()[0]
    assert "The active DAT changed since the last scan. Rescan to use it." in [
        w["text"] for w in card["warnings"]
    ]
    assert card["needs_scan"] is True


def test_a_set_needs_a_check_then_a_scan_until_one_succeeds_with_the_active_dat():
    dat = {"sha1": "new"}

    def run(kind, status, dat_sha1=None, started_at="2026-10-22T10:00:00Z"):
        return {"kind": kind, "status": status, "dat_sha1": dat_sha1, "started_at": started_at}

    check, scan = scanner.CHECK, scanner.IDENTIFY
    assert dashboard.needs(None, None, dat, None) == check
    assert dashboard.needs(run(check, "failed"), None, dat, None) == check
    assert dashboard.needs(run(check, "running"), None, dat, None) is None
    # Checked, never scanned; or the last scan failed (a first one included).
    assert dashboard.needs(run(check, "done"), None, dat, None) == scan
    failed = run(scan, "failed")
    assert dashboard.needs(failed, failed, dat, None) == scan
    done = run(scan, "done", "new")
    assert dashboard.needs(done, done, dat, None) is None
    assert dashboard.needs(run(check, "done"), done, dat, None) is None
    old = run(scan, "done", "old")
    assert dashboard.needs(old, old, dat, None) == scan
    # Scanned without a DAT (title IDs), or no DAT active: nothing to rescan for.
    assert dashboard.needs(run(scan, "done"), run(scan, "done"), dat, None) is None
    assert dashboard.needs(old, old, None, None) is None
    # A conversion ended after the scan: its outputs are identified by the next one.
    assert dashboard.needs(done, done, dat, "2026-10-22T09:00:00Z") is None
    assert dashboard.needs(done, done, dat, "2026-10-22T11:00:00Z") == scan


def test_folder_card_offers_the_default_dat_until_one_is_active(setup):
    client, _, _ = setup
    add_nes(client, label="nes")
    card = client.get("/api/folders").json()[0]
    assert card["needs_dat"] is True
    assert card["dat_download"] == {"source": "libretro", "label": "libretro-database mirror"}
    assert client.post("/api/dats/nes/download?source=libretro").status_code == HTTPStatus.OK
    card = client.get("/api/folders").json()[0]
    assert (card["needs_dat"], card["dat_download"]) == (False, None)


HASHEOUS_HINT = {
    "level": "info",
    "text": "Unmatched: 1 file. Hasheous may identify some.",
    "link": {"to": "/settings/lookups", "text": "Switch on Hasheous"},
}


def test_unmatched_files_point_to_hasheous_until_it_is_switched_on(setup):
    client, _, _ = setup
    scanned(client)
    assert HASHEOUS_HINT in client.get("/api/folders").json()[0]["warnings"]
    assert client.put("/api/settings/lookups", json={"hasheous": True}).status_code == 200
    assert HASHEOUS_HINT not in client.get("/api/folders").json()[0]["warnings"]


def test_each_version_names_the_dat_that_identified_it(setup):
    client, _, _ = setup
    scanned(client)
    games = client.get("/api/folders/nes/games").json()
    dats = {v["dat"]["label"] for g in games for v in g["versions"]}
    version = games[0]["versions"][0]
    assert len(dats) == 1 and dats <= {"uploaded DAT", "No-Intro"}
    assert version["dat"]["header_name"] == "Nintendo - Nintendo Entertainment System"
    assert version["dat"]["source_label"] in ("Uploaded file", "No-Intro (DAT-o-MATIC)")


def test_the_global_dat_order(setup):
    client, store, _ = setup
    first = client.get("/api/dat-order").json()
    assert not first["own"] and [e["id"] for e in first["entries"]][:2] == ["nointro", "upload"]
    order = [e["id"] for e in first["entries"]][::-1]
    saved = client.put("/api/dat-order", json={"order": order, "off": ["tosec"]}).json()
    assert saved["own"] and [e["id"] for e in saved["entries"]] == order
    assert [e["id"] for e in saved["entries"] if not e["on"]] == ["tosec"]
    assert store.load().dat_order == order
    assert client.put("/api/dat-order", json={"order": None}).json()["own"] is False


def test_parallel_scans_are_set_in_the_ui_within_the_configured_max(setup):
    client, store, settings = setup
    jobs = settings.jobs
    assert client.get("/api/settings").json()["parallel_scans"] == {
        "value": jobs.scan_workers,
        "default": jobs.scan_workers,
        "max": jobs.max_scan_workers,
    }
    chosen = jobs.max_scan_workers
    saved = client.put("/api/settings/parallel-scans", json={"value": chosen}).json()
    assert saved["parallel_scans"]["value"] == chosen == store.load().parallel_scans
    too_many = client.put("/api/settings/parallel-scans", json={"value": chosen + 1})
    assert too_many.status_code == HTTPStatus.BAD_REQUEST
    reset = client.put("/api/settings/parallel-scans", json={"value": None}).json()
    assert reset["parallel_scans"]["value"] == jobs.scan_workers


def test_parallel_conversions_are_set_in_the_ui_within_the_configured_max(setup):
    client, store, settings = setup
    jobs = settings.jobs
    assert client.get("/api/settings").json()["parallel_conversions"] == {
        "value": jobs.conversion_workers,
        "default": jobs.conversion_workers,
        "max": jobs.max_conversion_workers,
    }
    chosen = jobs.max_conversion_workers
    saved = client.put("/api/settings/parallel-conversions", json={"value": chosen}).json()
    assert saved["parallel_conversions"]["value"] == chosen == store.load().parallel_conversions
    too_many = client.put("/api/settings/parallel-conversions", json={"value": chosen + 1})
    assert too_many.status_code == HTTPStatus.BAD_REQUEST
    reset = client.put("/api/settings/parallel-conversions", json={"value": None}).json()
    assert reset["parallel_conversions"]["value"] == jobs.conversion_workers


def test_rows_per_page_are_set_in_the_ui_and_reach_every_table(setup):
    client, store, settings = setup
    ui = settings.ui
    assert client.get("/api/settings").json()["page_size"] == {
        "value": ui.page_size,
        "default": ui.page_size,
        "max": ui.max_page_size,
    }
    chosen = ui.max_page_size
    saved = client.put("/api/settings/page-size", json={"value": chosen}).json()
    assert saved["page_size"]["value"] == chosen == store.load().page_size
    assert client.get("/api/meta").json()["ui"]["page_size"] == chosen
    too_many = client.put("/api/settings/page-size", json={"value": chosen + 1})
    assert too_many.status_code == HTTPStatus.BAD_REQUEST
    client.put("/api/settings/page-size", json={"value": None})
    assert client.get("/api/meta").json()["ui"]["page_size"] == ui.page_size


def test_igir_threads_are_igir_s_own_until_set(setup):
    client, store, settings = setup
    assert client.get("/api/settings").json()["igir_threads"]["value"] is None
    most = settings.igir.max_threads
    assert (
        client.put("/api/settings/igir-threads", json={"value": most}).json()["igir_threads"][
            "value"
        ]
        == most
    )
    too_many = client.put("/api/settings/igir-threads", json={"value": most + 1})
    assert too_many.status_code == HTTPStatus.BAD_REQUEST
    client.put("/api/settings/igir-threads", json={"value": None})
    assert store.load().igir_threads is None


def test_removing_a_source_removes_its_dats_on_every_platform(setup):
    client, store, settings = setup
    client.post("/api/dats/nes/download")
    client.post("/api/dats/gb/download")
    nointro_dat = (DATA / "nes-nointro.dat").read_bytes()
    client.post("/api/dats/nes/upload", files={"file": ("nes.dat", nointro_dat)})
    client.put("/api/dats/nes/pin", json={"pinned": True, "source": "libretro"})
    files = [
        settings.paths.data_dir / v["file"]
        for r in client.get("/api/dats").json()
        for v in r["versions"]
    ]

    gone = client.delete("/api/dats/sources/libretro")
    assert gone.json() == {"versions": 2, "platforms": ["gb", "nes"]}
    rows = {r["platform"]: r for r in client.get("/api/dats").json()}
    assert [v["source"] for v in rows["nes"]["versions"]] == ["nointro"]
    assert rows["gb"]["versions"] == [] and rows["gb"]["active"] is None
    assert [e["id"] for e in rows["nes"]["order"]] == ["nointro", "hasheous"]
    assert set(store.load().dats["nes"].active) == {"nointro"}
    assert [f.exists() for f in files].count(True) == 1

    assert client.delete("/api/dats/sources/nonsense").status_code == HTTPStatus.BAD_REQUEST


def test_removing_a_source_waits_for_running_scans(setup):
    client, _, settings = setup
    client.post("/api/dats/nes/download")
    conn = db.open_database(settings)
    conn.execute(
        "INSERT INTO scan (folder_label, status, started_at) VALUES ('x', 'running', 'now')"
    )
    conn.close()
    assert client.delete("/api/dats/sources/libretro").status_code == HTTPStatus.CONFLICT
    assert (
        len(next(r for r in client.get("/api/dats").json() if r["platform"] == "nes")["versions"])
        == 1
    )


def test_hasheous_other_platform_warns_only_while_the_file_is_unmatched_in_the_folder(setup):
    client, _, settings = setup
    scanned(client)
    conn = db.connect(settings.paths.database_path, busy_timeout_ms=0)
    conn.execute(
        "INSERT INTO lookup_result VALUES ('nes', 'stray.zip', ?, ?, 'known for Game Boy')",
        (hasheous.SERVICE, hasheous.OTHER_PLATFORM),
    )
    warning = {
        "level": "warn",
        "text": "Hasheous knows 1 file for another platform.",
        "link": {"to": "/folders/nes/matching?view=unmatched", "text": "Show them"},
    }
    assert warning in client.get("/api/folders").json()[0]["warnings"]

    # Matched by hand: the stored answer no longer points at anything to do.
    client.put(
        "/api/folders/nes/assign", json={"rel_path": "stray.zip", "game_name": "Solo (Japan)"}
    )
    assert warning not in client.get("/api/folders").json()[0]["warnings"]
    client.put("/api/folders/nes/assign", json={"rel_path": "stray.zip", "game_name": None})
    assert warning in client.get("/api/folders").json()[0]["warnings"]

    # Moved to discarded/: neither.
    conn.execute(
        "UPDATE folder_file SET place = 'discarded' WHERE folder_label = 'nes' "
        "AND rel_path = 'stray.zip'"
    )
    assert warning not in client.get("/api/folders").json()[0]["warnings"]
