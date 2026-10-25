import os
from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient

from g1r import db, igir, journal, notifications, renaming
from g1r.library import LibraryStore
from g1r.web.app import create_app

from .test_api import DATA, dat_bytes
from .test_journal import CONFIG
from .test_scanner import write_zip
from .waits import finished

# File name -> the DAT game igir finds in it.
FILES = {
    "contra.zip": "Contra (USA)",
    "contra-jp.zip": "Contra (Japan)",
    "gradius.zip": "Gradius (USA)",
    "Gradius (USA) (Rev 1).zip": "Gradius (USA) (Rev 1)",
    # A second copy of a game: the first by path gets the name.
    "solo-a.zip": "Solo (Japan)",
    "solo-b.zip": "Solo (Japan)",
}


@pytest.fixture
def renames(make_settings, roms_root):
    folder = roms_root / "nes"
    folder.mkdir()
    for name in FILES:
        write_zip(folder / name, f"{name}.nes", name.encode())
    write_zip(folder / "stray.zip", "stray.nes", b"??")
    (roms_root / "discarded").mkdir()
    settings = make_settings({"grouping": {"retool_clonelists_dir": str(DATA / "none")}})

    def report(settings_, dat_file, input_dir, **_):
        by_game: dict[str, list[str]] = {}
        for name, game in FILES.items():
            by_game.setdefault(game, []).append(str(input_dir / name))
        return [igir.ReportRow(game, "FOUND", tuple(paths)) for game, paths in by_game.items()]

    with TestClient(create_app(settings, report_runner=report)) as client:
        body = {"platform": "nes", "mount": "roms", "path": "nes", "label": "nes"}
        assert client.post("/api/folders", json=body).status_code == HTTPStatus.CREATED
        client.post("/api/dats/nes/upload", files={"file": ("nes.dat", dat_bytes())})
        assert client.post("/api/folders/nes/scan").status_code == HTTPStatus.ACCEPTED
        assert finished(client, "nes")["status"] == "done"
        yield client, folder, settings


def rows_of(client) -> dict[str, dict]:
    return {r["rel_path"]: r for r in client.get("/api/folders/nes/rename").json()["rows"]}


def run(client, path: str, body: dict | None = None) -> dict:
    plan = client.post(f"/api/folders/nes/{path}/preview", json=body or {}).json()
    started = client.post(f"/api/folders/nes/{path}", json={**(body or {}), "token": plan["token"]})
    assert started.status_code == HTTPStatus.ACCEPTED, started.text
    return finished(client, "nes", "run")


def test_names_from_templates(make_settings):
    settings = make_settings()
    config = settings.rename
    assert renaming.without_tags(config, "Final Fantasy VII (USA) (Disc 1) [b]") == (
        "Final Fantasy VII (Disc 1)"
    )
    assert renaming.safe(config, 'What? A: "B" / C') == "What_ A_ _B_ _ C"
    assert renaming.new_stem(settings, "dat", "Tetris (World) (Rev 1)", "dat-checksum") == (
        "Tetris (World) (Rev 1)",
        "",
    )
    assert renaming.new_stem(settings, "clean", "Tetris (World) (Rev 1)", "manual")[0] == "Tetris"
    switch = "80 DAYS [0100B9900A1D0800][v65536][d1.0.1]"
    assert renaming.new_stem(settings, "switch", switch, "title-id")[0] == (
        "80 DAYS [0100B9900A1D0800][v65536]"
    )
    # The other templates work on title IDs too: the name without its IDs.
    assert renaming.new_stem(settings, "clean", switch, "title-id")[0] == "80 DAYS"
    assert renaming.new_stem(settings, "dat", switch, "title-id")[0] == "80 DAYS"
    unread = "80 DAYS [0100B9900A1D0800]"
    assert renaming.new_stem(settings, "switch", unread, "title-id") == (
        None,
        "version unknown (prod.keys read it)",
    )
    assert renaming.new_stem(settings, "keep", "Tetris (World)", "dat-checksum")[0] is None


def test_platforms_offer_their_templates(renames):
    client, _, settings = renames
    # Arcade set names are what emulators load; a template built from title IDs is offered
    # only where there are title IDs, the others everywhere.
    assert settings.rename_templates("neogeomvs") == ["keep"]
    assert settings.rename_default("neogeomvs") == "keep"
    assert settings.rename_templates("switch") == ["keep", "dat", "clean", "switch"]
    assert settings.rename_default("switch") == "switch"
    detail = client.get("/api/folders/nes").json()
    assert (detail["rename_template"], detail["rename_templates"]) == (
        "dat",
        ["keep", "dat", "clean"],
    )
    refused = client.put("/api/folders/nes/rename-template", json={"template": "switch"})
    assert refused.status_code == HTTPStatus.BAD_REQUEST
    refused = client.put("/api/folders/nes/rename-template", json={"template": "bogus"})
    assert refused.status_code == HTTPStatus.BAD_REQUEST
    meta = client.get("/api/meta").json()
    assert meta["rename_templates"]["dat"]["label"] == "DAT name"


def test_rename_to_dat_names_then_clean_titles_then_back(renames):
    client, folder, settings = renames
    # Keep names: nothing proposed, the tab has nothing to do.
    kept = client.put("/api/folders/nes/rename-template", json={"template": "keep"}).json()
    assert kept["rename_template"] == "keep"
    assert {r["status"] for r in rows_of(client).values()} == {"skipped"}
    assert client.get("/api/folders").json()[0]["rename"]["proposed"] == 0

    # Back to the platform's default, DAT name.
    saved = client.put("/api/folders/nes/rename-template", json={"template": None}).json()
    assert saved["rename_template"] == "dat"
    rows = rows_of(client)
    assert rows["contra.zip"]["new_path"] == "Contra (USA).zip"
    assert rows["Gradius (USA) (Rev 1).zip"]["status"] == "named"
    assert rows["solo-a.zip"]["new_path"] == "Solo (Japan).zip"
    assert rows["solo-b.zip"]["reason"] == "the name is taken by solo-a.zip"
    assert rows["stray.zip"]["reason"] == "not identified"
    assert client.get("/api/folders").json()[0]["rename"]["proposed"] == 4
    picked = {"group_key": "name:Gradius", "rel_path": "gradius.zip"}
    assert client.put("/api/folders/nes/keep", json=picked).status_code == HTTPStatus.OK

    preview = client.post("/api/folders/nes/rename/preview", json={}).json()
    assert [f["rel_path"] for f in preview["files"]] == [
        "contra-jp.zip",
        "contra.zip",
        "gradius.zip",
        "solo-a.zip",
    ]
    assert preview["files"][0]["destination"] == str(folder / "Contra (Japan).zip")
    done = run(client, "rename")
    assert (done["status"], done["message"]) == ("done", "4 files renamed")
    assert (folder / "Contra (USA).zip").is_file() and not (folder / "contra.zip").exists()

    # The rows followed the files: identities, the user's pick, no rescan needed.
    games = {g["name"]: g for g in client.get("/api/folders/nes/games").json()}
    assert games["Gradius"]["kept"] == "Gradius (USA).zip"
    assert games["Contra"]["kept"] == "Contra (USA).zip"
    rows = rows_of(client)
    assert rows["Contra (USA).zip"]["status"] == "named"
    assert rows["Contra (USA).zip"]["original"] == "contra.zip"
    assert rows["solo-b.zip"]["reason"] == "the name is taken by Solo (Japan).zip"

    # Another template: the original stays the first name; Contra's two regions collide.
    client.put("/api/folders/nes/rename-template", json={"template": "clean"})
    rows = rows_of(client)
    assert rows["Contra (Japan).zip"]["new_path"] == "Contra.zip"
    assert rows["Contra (USA).zip"]["reason"] == "the name is taken by Contra (Japan).zip"
    assert run(client, "rename", {"rel_paths": ["Contra (Japan).zip"]})["status"] == "done"
    assert rows_of(client)["Contra.zip"]["original"] == "contra-jp.zip"

    # Revert: every renamed file gets the name it had before its first rename.
    preview = client.post("/api/folders/nes/rename/revert/preview", json={}).json()
    assert len(preview["files"]) == 4
    back = run(client, "rename/revert")
    assert (back["kind"], back["message"]) == ("restore", "4 files given back their names")
    assert sorted(p.name for p in folder.iterdir()) == sorted([*FILES, "stray.zip"])
    assert all(r["original"] is None for r in rows_of(client).values())
    games = {g["name"]: g for g in client.get("/api/folders/nes/games").json()}
    assert games["Gradius"]["kept"] == "gradius.zip"

    feed = client.get("/api/notifications").json()
    assert [i["title"] for i in feed if i["kind"].startswith("rename")][:3] == [
        "Names given back",
        "Rename",
        "Rename",
    ]


def test_a_name_taken_on_disk_stops_the_rename(renames):
    client, folder, _ = renames
    client.put("/api/folders/nes/rename-template", json={"template": "dat"})
    (folder / "Contra (USA).zip").write_bytes(b"not scanned yet")
    preview = client.post("/api/folders/nes/rename/preview", json={}).json()
    assert any("already exists" in p["problem"] for p in preview["problems"])
    started = client.post("/api/folders/nes/rename", json={"token": preview["token"]})
    assert started.status_code == HTTPStatus.CONFLICT
    assert (folder / "contra.zip").is_file()


def test_names_by_hasheous_or_a_name_match_are_not_renamed(renames):
    client, _, settings = renames
    store = LibraryStore(settings)
    conn = db.open_database(settings)
    conn.execute(
        "UPDATE identity SET method = 'fuzzy' WHERE folder_label = 'nes' AND rel_path = ?",
        ("contra.zip",),
    )
    conn.close()
    assert store.load().folder("nes") is not None
    client.put("/api/folders/nes/rename-template", json={"template": "dat"})
    assert rows_of(client)["contra.zip"]["reason"] == "identified by name only: not renamed"


def test_every_table_with_a_file_path_follows_a_rename(tmp_path):
    conn = db.connect(tmp_path / "s.db", 1000)
    db.migrate(conn)
    with_paths = {
        name
        for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        if any(c[1] == "rel_path" for c in conn.execute(f"PRAGMA table_info({name})"))
    }
    assert with_paths == set(journal.RENAMED) | set(journal.RENAME_SKIPS)


def test_recovery_finishes_an_interrupted_rename(tmp_path):
    folder = tmp_path / "roms"
    folder.mkdir()
    conn = db.connect(tmp_path / "s.db", 1000)
    db.migrate(conn)
    (folder / "b.zip").write_bytes(b"x")
    stat = (folder / "b.zip").stat()
    conn.execute(
        "INSERT INTO folder_file (folder_label, rel_path, size, mtime_ns, kind) "
        "VALUES ('f', 'a.zip', ?, ?, 'archive')",
        (stat.st_size, stat.st_mtime_ns),
    )
    conn.execute(
        "INSERT INTO identity (folder_label, rel_path, game_name, method, dat_sha1) "
        "VALUES ('f', 'a.zip', 'B', 'dat-checksum', '')"
    )
    run_id = journal.start_run(conn, "f", journal.APPLY, journal.SCOPE_RENAME, 1)
    # Cut off after the file got its new name, before the step was settled.
    conn.execute(
        "INSERT INTO operation (run_id, folder_label, rel_path, reason, source, destination, "
        "size, mtime_ns, state, action) VALUES (?, 'f', 'a.zip', 'rename', ?, ?, ?, ?, ?, ?)",
        (
            run_id,
            str(folder / "a.zip"),
            str(folder / "b.zip"),
            stat.st_size,
            stat.st_mtime_ns,
            journal.STARTED,
            journal.RENAME,
        ),
    )
    assert journal.recover(CONFIG, conn) == 1
    assert conn.execute("SELECT rel_path FROM identity").fetchall()[0][0] == "b.zip"
    assert dict(conn.execute("SELECT rel_path, original FROM rename_origin").fetchall()) == {
        "b.zip": "a.zip"
    }
    assert os.path.exists(folder / "b.zip")
    assert notifications.TITLES[notifications.RENAME] == "Rename"
