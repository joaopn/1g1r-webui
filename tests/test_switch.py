import sqlite3
import struct
from http import HTTPStatus

import pytest

from g1r import titles

BASE_ID = "0100AAAA00010000"
UPDATE_ID = "0100AAAA00010800"
DLC_ID = "0100AAAA00011001"
OTHER_DLC_ID = "0100BBBB00011001"
LONE_ID = "0100CCCC00010000"
# Versions as the console counts them: each update release adds 65536.
FIRST_UPDATE = 65536
SECOND_UPDATE = 131072


def pfs0(make_settings, members: dict[str, bytes]) -> bytes:
    """A PFS0 container holding these files."""
    c = make_settings().title_ids
    names = b"".join(n.encode() + b"\0" for n in members)
    entries, name_at, offset = b"", 0, 0
    for name, data in members.items():
        entries += struct.pack(c.pfs0_entry, offset, len(data), name_at, 0)
        name_at += len(name) + 1
        offset += len(data)
    header = struct.pack(c.pfs0_header, c.pfs0_magic.encode(), len(members), len(names), 0)
    return header + entries + names + b"".join(members.values())


def ticket(make_settings, title_id: str) -> dict[str, bytes]:
    """A ticket's file: "<title ID><key generation>.tik"."""
    c = make_settings().title_ids
    key_generation = "0" * (c.rights_id_digits - c.digits)
    return {f"{title_id.lower()}{key_generation}{c.ticket_suffix}": b"ticket"}


def cnmt_xml(title_id: str, version: int, kind: str) -> dict[str, bytes]:
    xml = (
        f'<?xml version="1.0" encoding="utf-8"?><ContentMeta><Type>{kind}</Type>'
        f"<Id>0x{title_id.lower()}</Id><Version>{version}</Version></ContentMeta>"
    )
    return {"1c6deb728d6e6b4b364aceb24773d0dd.cnmt.xml": xml.encode()}


def nsp(make_settings, title_id: str, version: int | None = None, kind: str = "Patch") -> bytes:
    """An NSP with a ticket, and the content metadata when `version` is given."""
    members = ticket(make_settings, title_id)
    if version is not None:
        members |= cnmt_xml(title_id, version, kind)
    return pfs0(make_settings, members)


def test_titles_are_read_from_inside_the_file(make_settings, tmp_path):
    c = make_settings().title_ids
    path = tmp_path / "Super Game (USA) [0100FFFF00010000][v999].nsp"
    path.write_bytes(nsp(make_settings, UPDATE_ID, SECOND_UPDATE))
    title = titles.read_title(path, path.name, c)
    # The content metadata says what it is; the name's tags are not read.
    assert titles.hex_id(title.title_id, c) == UPDATE_ID and title.role(c) == titles.UPDATE
    assert title.version == SECOND_UPDATE and title.name == "Super Game (USA)"
    # A ticket alone gives the title ID, not the version.
    path = tmp_path / "random name.nsp"
    path.write_bytes(nsp(make_settings, DLC_ID))
    title = titles.read_title(path, path.name, c)
    assert titles.hex_id(title.title_id, c) == DLC_ID and title.role(c) == titles.DLC
    assert title.version is None and title.name == "random name"
    # A name with an ID but nothing inside, or a format without a PFS0: nothing read.
    path = tmp_path / f"Super Game [{BASE_ID}][v0].nsp"
    path.write_bytes(b"not a pfs0")
    assert titles.read_title(path, path.name, c) is None
    path = tmp_path / f"Super Game [{BASE_ID}].xci"
    path.write_bytes(nsp(make_settings, BASE_ID, 0, "Application"))
    assert titles.read_title(path, path.name, c) is None  # converted to NSP first


def scan(client) -> dict:
    client.post("/api/folders/switch/scan")
    for _ in range(500):
        found = client.get("/api/folders/switch/scan").json()
        if found["status"] != "running":
            return found
    raise AssertionError("the scan did not finish")


def wait_run(client) -> dict:
    for _ in range(500):
        run = client.get("/api/folders/switch/run").json()
        if run and run["status"] != "running":
            return run
    raise AssertionError("the run did not finish")


@pytest.fixture
def switch(folder_of, make_settings, roms_root):
    client, folder = folder_of("switch")
    files = {
        "Super Game (USA).nsp": nsp(make_settings, BASE_ID, 0, "Application"),
        "Super Game update 1.nsp": nsp(make_settings, UPDATE_ID, FIRST_UPDATE),
        "Super Game update 2.nsp": nsp(make_settings, UPDATE_ID, SECOND_UPDATE),
        "Super Game - Pack.nsp": nsp(make_settings, DLC_ID, 0, "AddOnContent"),
        "Other Game - Pack.nsp": nsp(make_settings, OTHER_DLC_ID),
        "no id.nsp": b"?",
    }
    for name, data in files.items():
        (folder / name).write_bytes(data)
    return client, folder, roms_root


def test_1g1r_keeps_the_game_its_updates_and_dlc(switch, make_settings):
    client, folder, roms_root = switch
    (folder / "Lone Game.nsp").write_bytes(nsp(make_settings, LONE_ID, 0, "Application"))
    assert scan(client)["message"] == "6 of 7 files identified by title ID"
    games = {g["name"]: g for g in client.get("/api/folders/switch/games").json()}
    game = games["Super Game (USA)"]
    assert (game["status"], game["reason"]) == ("single", "its updates and DLC are kept")
    # Matching lists the base file only; its updates and DLC are counted, and listed on the
    # Updates & DLC tab.
    assert [v["rel_path"] for v in game["versions"]] == ["Super Game (USA).nsp"]
    assert game["extras"] == {"updates": 2, "dlc": 1}
    assert game["versions"][0]["keep"] and game["versions"][0]["operation"] is None
    rows = client.get("/api/folders/switch/updates").json()["updates"]
    roles = {r["rel_path"]: (r["role"], r["status"]) for r in rows}
    assert roles["Super Game update 1.nsp"][0] == "update"
    assert roles["Super Game - Pack.nsp"] == ("dlc", "dlc")
    # DLC without its game: not a game of the Matching table; listed with the DLC, kept.
    assert "Other Game - Pack" not in games
    # The Updates & DLC tab lists every game, those without updates or DLC too.
    entries = {g["game"]: g for g in client.get("/api/folders/switch/updates").json()["games"]}
    assert sorted(entries) == ["Lone Game", "Other Game - Pack", "Super Game (USA)"]
    sg = entries["Super Game (USA)"]
    assert (sg["updates"], sg["dlc"], sg["to_discard"], sg["version"]) == (2, 1, 1, SECOND_UPDATE)
    assert (entries["Lone Game"]["updates"], entries["Lone Game"]["dlc"]) == (0, 0)
    assert entries["Other Game - Pack"]["dlc"] == 1
    assert roles["Other Game - Pack.nsp"] == ("dlc", "dlc")
    refused = client.put(
        "/api/folders/switch/updates/keep",
        json={"rel_paths": ["Super Game - Pack.nsp"], "keep": True},
    )
    assert refused.status_code == HTTPStatus.NOT_FOUND
    # A name alone identifies nothing.
    assert sorted(f["rel_path"] for f in client.get("/api/folders/switch/unmatched").json()) == [
        "no id.nsp"
    ]
    # Updates and DLC are no versions: one base file is not "several versions".
    card = next(f for f in client.get("/api/folders").json() if f["label"] == "switch")
    assert card["counts"]["several"] == 0
    assert card["updates"] == {"total": 2, "proposed": 1, "unknown": 0, "unreadable": 0, "dlc": 2}
    plan = client.post("/api/folders/switch/apply/preview", json={}).json()
    assert plan["moves"] == []


def test_two_base_files_are_still_several_versions(folder_of, make_settings):
    client, folder = folder_of("switch")
    for name in ("Super Game [dump a].nsp", "Super Game [dump b].nsp"):
        (folder / name).write_bytes(nsp(make_settings, BASE_ID, 0, "Application") + name.encode())
    (folder / "update.nsp").write_bytes(nsp(make_settings, UPDATE_ID, FIRST_UPDATE))
    scan(client)
    (game,) = client.get("/api/folders/switch/games").json()
    assert game["status"] == "undecided"
    card = next(f for f in client.get("/api/folders").json() if f["label"] == "switch")
    assert card["counts"]["several"] == 1


def test_copies_of_a_base_file_are_yours_to_pick(folder_of, make_settings):
    """Two base files of one title ID, byte-identical or not, leave the game undecided
    (maintainer, 2026-10-24: "Even when byte-identical they are mine to pick"). Without
    titledb the game is named after its first base file (by path)."""
    client, folder = folder_of("switch")
    base = nsp(make_settings, BASE_ID, 0, "Application")
    for name in ("Super Game [0100AAAA00010000][v0].nsp", "SG v0.nsp"):
        (folder / name).write_bytes(base)
    (folder / "update.nsp").write_bytes(nsp(make_settings, UPDATE_ID, FIRST_UPDATE))
    scan(client)
    (game,) = client.get("/api/folders/switch/games").json()
    assert (game["name"], game["status"]) == ("SG v0", "undecided")
    assert not any(v["operation"] for v in game["versions"])
    assert all(v["identical"] == [] for v in game["versions"])
    # Even with their data known to be identical (a DAT pass hashes possible copies).
    conn = sqlite3.connect(client.app.state.settings.paths.database_path)
    conn.executemany(
        "INSERT INTO payload_hash VALUES ('switch', ?, 1, 'same')",
        [(v["rel_path"],) for v in game["versions"] if v["role"] == "base"],
    )
    conn.commit()
    conn.close()
    (game,) = client.get("/api/folders/switch/games").json()
    assert game["status"] == "undecided" and not any(v["operation"] for v in game["versions"])


def test_older_updates_are_proposed_kept_or_moved(switch):
    client, folder, roms_root = switch
    scan(client)
    rows = {r["rel_path"]: r for r in client.get("/api/folders/switch/updates").json()["updates"]}
    newest, older = rows["Super Game update 2.nsp"], rows["Super Game update 1.nsp"]
    assert (newest["status"], newest["operation"]) == ("newest", None)
    assert (newest["version"], newest["title_id"]) == (SECOND_UPDATE, UPDATE_ID)
    assert (newest["release"], older["release"]) == (2, 1)
    assert older["status"] == "older"
    assert older["operation"].endswith("discarded/switch/updates/Super Game update 1.nsp")

    # Kept by the user: nothing to move.
    body = {"rel_paths": ["Super Game update 1.nsp"], "keep": True}
    kept = client.put("/api/folders/switch/updates/keep", json=body).json()
    assert {r["rel_path"]: r["status"] for r in kept["updates"]}["Super Game update 1.nsp"] == (
        "kept"
    )
    assert client.post("/api/folders/switch/updates/discard/preview", json={}).json()["files"] == []
    body["keep"] = False
    client.put("/api/folders/switch/updates/keep", json=body)
    # A file that is not an update is refused.
    refused = client.put(
        "/api/folders/switch/updates/keep", json={"rel_paths": ["no id.nsp"], "keep": True}
    )
    assert refused.status_code == HTTPStatus.NOT_FOUND

    plan = client.post("/api/folders/switch/updates/discard/preview", json={}).json()
    assert [f["rel_path"] for f in plan["files"]] == ["Super Game update 1.nsp"]
    assert plan["irreversible"] == 0
    client.post("/api/folders/switch/updates/discard", json={"token": plan["token"]})
    assert wait_run(client)["status"] == "done"
    assert (roms_root / "discarded/switch/updates/Super Game update 1.nsp").exists()
    assert (folder / "Super Game update 2.nsp").exists()
    rows = {r["rel_path"]: r for r in client.get("/api/folders/switch/updates").json()["updates"]}
    moved = rows["Super Game update 1.nsp"]
    assert moved["status"] == "discarded" and moved["discarded"]
    # 1G1R still keeps the game whole: the discarded update is not a discarded version.
    games = {g["name"]: g for g in client.get("/api/folders/switch/games").json()}
    assert games["Super Game (USA)"]["status"] == "single"
    notes = client.get("/api/notifications").json()
    assert any(n["title"] == "Older updates" for n in notes)

    restored = client.post(
        "/api/folders/switch/restore", json={"operation_ids": [moved["discarded"]]}
    )
    assert restored.status_code == HTTPStatus.ACCEPTED
    assert wait_run(client)["status"] == "done"
    assert (folder / "Super Game update 1.nsp").exists()


def test_an_update_without_a_readable_version_keeps_the_whole_game(folder_of, make_settings):
    client, folder = folder_of("switch")
    (folder / "game.nsp").write_bytes(nsp(make_settings, BASE_ID, 0, "Application"))
    (folder / "update 1.nsp").write_bytes(nsp(make_settings, UPDATE_ID, FIRST_UPDATE))
    # No content metadata: the ticket gives the ID, not the version.
    (folder / "update 2.nsp").write_bytes(nsp(make_settings, UPDATE_ID))
    scan(client)
    found = client.get("/api/folders/switch/updates").json()
    assert {r["status"] for r in found["updates"]} == {"version unknown"}
    assert not any(r["operation"] for r in found["updates"])
    assert found["counts"] == {
        "total": 2,
        "proposed": 0,
        "unknown": 2,
        "unreadable": 1,
        "dlc": 0,
        "newer": 0,
    }
    # Home says so, pointing at the tab where prod.keys are added.
    card = next(f for f in client.get("/api/folders").json() if f["label"] == "switch")
    (hint,) = [w for w in card["warnings"] if "readable version" in w["text"]]
    assert hint["level"] == "info" and hint["text"].startswith("1 update without")
    assert hint["link"] == {"to": "/folders/switch/updates", "text": "Add prod.keys"}


def test_a_lone_update_is_the_newest_without_a_version(folder_of, make_settings):
    client, folder = folder_of("switch")
    (folder / "game.nsp").write_bytes(nsp(make_settings, BASE_ID, 0, "Application"))
    (folder / "update.nsp").write_bytes(nsp(make_settings, UPDATE_ID))
    scan(client)
    (update,) = client.get("/api/folders/switch/updates").json()["updates"]
    assert (update["status"], update["version"], update["operation"]) == ("newest", None, None)


def test_a_platform_without_title_ids_has_no_updates(folder_of):
    client, _ = folder_of("gb")
    assert client.get("/api/folders/gb/updates").status_code == HTTPStatus.NOT_FOUND
