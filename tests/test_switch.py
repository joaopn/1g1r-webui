import struct
from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient

from g1r import titles
from g1r.web.app import create_app

BASE = "Super Game (USA) [0100AAAA00010000][v0]"
UPDATE = "Super Game [0100AAAA00010800][v65536]"
DLC = "Super Game - Pack [0100AAAA00011001][v0]"
OTHER_DLC = "Other Game - Pack [0100BBBB00011001][v0]"


def nsp_with_ticket(title_id: str, make_settings) -> bytes:
    """A PFS0 holding only a ticket's name: "<title ID><key generation>.tik"."""
    c = make_settings().title_ids
    key_generation = "0" * (c.rights_id_digits - c.digits)
    names = f"{title_id}{key_generation}{c.ticket_suffix}".encode() + b"\0"
    entry = struct.pack(c.pfs0_entry, 0, 0, 0, 0)
    return struct.pack(c.pfs0_header, c.pfs0_magic.encode(), 1, len(names), 0) + entry + names


def test_title_ids_tell_base_update_and_dlc(make_settings, tmp_path):
    c = make_settings().title_ids
    base, update, dlc = (titles.from_name(n + ".nsp", c) for n in (BASE, UPDATE, DLC))
    assert (base.role(c), update.role(c), dlc.role(c)) == (titles.BASE, titles.UPDATE, titles.DLC)
    assert {titles.hex_id(t.app_id(c), c) for t in (base, update, dlc)} == {"0100AAAA00010000"}
    assert base.name == "Super Game (USA)" and update.version == 65536
    # A ticket inside the NSP wins over a missing or wrong name.
    path = tmp_path / "renamed.nsp"
    path.write_bytes(nsp_with_ticket("0100AAAA00011002", make_settings))
    title = titles.read_title(path, path.name, c)
    assert titles.hex_id(title.title_id, c) == "0100AAAA00011002" and title.role(c) == titles.DLC


@pytest.fixture
def switch(make_settings, roms_root):
    folder = roms_root / "switch"
    folder.mkdir()
    (roms_root / "discarded").mkdir()
    for name in (BASE, UPDATE, DLC, OTHER_DLC):
        (folder / f"{name}.nsp").write_bytes(name.encode())
    (folder / "Super Game (USA) [0100AAAA00010000].xci").write_bytes(b"cart")
    (folder / "no id.nsp").write_bytes(b"?")
    with TestClient(create_app(make_settings(), report_runner=lambda *a: [])) as client:
        body = {"platform": "switch", "mount": "roms", "path": "switch", "label": "switch"}
        assert client.post("/api/folders", json=body).status_code == HTTPStatus.CREATED
        yield client, folder, roms_root


def test_game_plus_dlc_without_a_dat(switch):
    client, folder, roms_root = switch
    client.post("/api/folders/switch/scan")
    for _ in range(500):
        scan = client.get("/api/folders/switch/scan").json()
        if scan["status"] != "running":
            break
    assert scan["message"] == "5 of 6 files identified by title ID"
    games = {g["name"]: g for g in client.get("/api/folders/switch/games").json()}
    game = games["Super Game (USA)"]
    rows = {v["rel_path"]: v for v in game["versions"]}
    # Two dumps of the base (NSP and XCI) tie: undecided. The DLC is kept whatever is
    # chosen; the update is proposed for discarded/switch/updates/.
    assert game["status"] == "undecided"
    assert rows[f"{DLC}.nsp"]["keep"] and rows[f"{DLC}.nsp"]["operation"] is None
    assert rows[f"{UPDATE}.nsp"]["discard_reason"] == "updates"
    assert (rows[f"{UPDATE}.nsp"]["role"], rows[f"{DLC}.nsp"]["role"]) == ("update", "dlc")
    # DLC without its game: left alone.
    other = games["Other Game - Pack"]
    assert other["status"] == "left alone" and not any(v["operation"] for v in other["versions"])
    assert [f["rel_path"] for f in client.get("/api/folders/switch/unmatched").json()] == [
        "no id.nsp"
    ]

    client.put(
        "/api/folders/switch/keep",
        json={"group_key": game["key"], "rel_path": f"{BASE}.nsp"},
    )
    plan = client.post("/api/folders/switch/apply/preview", json={"group_key": game["key"]}).json()
    assert sorted(m["rel_path"] for m in plan["moves"]) == [
        "Super Game (USA) [0100AAAA00010000].xci",
        f"{UPDATE}.nsp",
    ]
    client.post(
        "/api/folders/switch/apply", json={"group_key": game["key"], "token": plan["token"]}
    )
    for _ in range(500):
        run = client.get("/api/folders/switch/run").json()
        if run and run["status"] != "running":
            break
    assert run["status"] == "done"
    assert (roms_root / "discarded/switch/updates" / f"{UPDATE}.nsp").exists()
    assert (folder / f"{DLC}.nsp").exists() and (folder / f"{BASE}.nsp").exists()


def test_a_game_says_applied_once_its_update_is_in_discarded(folder_of, roms_root):
    client, folder = folder_of("switch")
    for name in (
        BASE,
        UPDATE,
        "Second Game (USA) [0100CCCC00010000][v0]",
        "Second Game - Pack [0100CCCC00011001][v0]",
    ):
        (folder / f"{name}.nsp").write_bytes(name.encode())

    def games():
        client.post("/api/folders/switch/scan")
        for _ in range(500):
            if client.get("/api/folders/switch/scan").json()["status"] != "running":
                break
        return {g["name"]: g for g in client.get("/api/folders/switch/games").json()}

    found = games()
    assert found["Super Game (USA)"]["status"] == "decided"
    # A game and its DLC, no update: nothing to propose.
    second = found["Second Game (USA)"]
    assert (second["status"], second["reason"]) == ("single", "its DLC are kept")
    assert not any(v["operation"] for v in second["versions"])

    plan = client.post("/api/folders/switch/apply/preview", json={}).json()
    assert [m["rel_path"] for m in plan["moves"]] == [f"{UPDATE}.nsp"]
    client.post("/api/folders/switch/apply", json={"token": plan["token"]})
    for _ in range(500):
        run = client.get("/api/folders/switch/run").json()
        if run and run["status"] != "running":
            break
    assert run["status"] == "done"
    game = games()["Super Game (USA)"]
    assert (game["status"], game["reason"]) == ("applied", "its updates are in discarded/")
