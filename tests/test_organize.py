from http import HTTPStatus

from g1r import organize

from .test_switch import scan, switch, wait_run  # noqa: F401 (the fixture)

GAME = "Super Game (USA)"


def rows_of(client) -> dict[str, dict]:
    return {r["rel_path"]: r for r in client.get("/api/folders/switch/organize").json()["rows"]}


def run(client, path: str, body: dict | None = None) -> dict:
    plan = client.post(f"/api/folders/switch/{path}/preview", json=body or {}).json()
    started = client.post(
        f"/api/folders/switch/{path}", json={**(body or {}), "token": plan["token"]}
    )
    assert started.status_code == HTTPStatus.ACCEPTED, started.text
    return wait_run(client)


def test_folder_names_lose_what_a_folder_cannot_hold(make_settings):
    settings = make_settings()
    assert organize.folder_name(settings, 'Mr. Shifty: "Deluxe"  ') == "Mr. Shifty Deluxe"
    assert organize.folder_name(settings, "Game...") == "Game"


def test_files_go_to_their_game_s_folders_and_back(switch):  # noqa: F811
    client, folder, _ = switch
    scan(client)
    (folder / "own").mkdir()
    rows = rows_of(client)
    base, newest = rows[f"{GAME}.nsp"], rows["Super Game update 2.nsp"]
    assert (base["status"], base["new_path"]) == ("move", f"{GAME}/{GAME}.nsp")
    assert newest["new_path"] == f"{GAME}/update/Super Game update 2.nsp"
    assert rows["Super Game - Pack.nsp"]["new_path"] == f"{GAME}/dlc/Super Game - Pack.nsp"
    # The older update waits for its move to discarded/; a DLC without its game and a file
    # without a title ID stay.
    assert rows["Super Game update 1.nsp"]["reason"] == "proposed for discarded/"
    assert rows["Other Game - Pack.nsp"]["reason"] == "its game's name is unknown"
    assert rows["no id.nsp"]["reason"] == "not identified by its title ID"

    assert run(client, "organize")["message"] == "3 files moved to game folders"
    assert (folder / GAME / f"{GAME}.nsp").is_file()
    assert (folder / GAME / "update" / "Super Game update 2.nsp").is_file()
    assert (folder / GAME / "dlc" / "Super Game - Pack.nsp").is_file()
    rows = rows_of(client)
    assert rows[f"{GAME}/{GAME}.nsp"]["status"] == "in place"
    assert rows[f"{GAME}/{GAME}.nsp"]["original_dir"] == ""
    # The Updates & DLC tab follows the files; nothing counts as renamed.
    updates = {r["rel_path"] for r in client.get("/api/folders/switch/updates").json()["updates"]}
    assert f"{GAME}/update/Super Game update 2.nsp" in updates
    assert client.get("/api/folders/switch/rename").json()["counts"]["renamed"] == 0
    # A rescan finds them where they are.
    scan(client)
    assert rows_of(client)[f"{GAME}/dlc/Super Game - Pack.nsp"]["status"] == "in place"

    # A rename keeps the folder; its revert gives the name back in that folder.
    client.put("/api/folders/switch/rename-template", json={"template": "switch"})
    renamed = {r["rel_path"]: r for r in client.get("/api/folders/switch/rename").json()["rows"]}
    new_name = renamed[f"{GAME}/{GAME}.nsp"]["new_path"]
    assert new_name.startswith(f"{GAME}/") and new_name != f"{GAME}/{GAME}.nsp"
    run(client, "rename", {"rel_paths": [f"{GAME}/{GAME}.nsp"]})
    assert (folder / new_name).is_file()

    notes = [n["title"] for n in client.get("/api/notifications").json()]
    assert "Game folders" in notes
    done = run(client, "organize/revert")
    assert done["message"] == "3 files given back their folders"
    assert (folder / "Super Game update 2.nsp").is_file()
    renamed_name = new_name.split("/")[-1]
    assert (folder / renamed_name).is_file()
    # The emptied game folders are gone; a folder of the user's stays.
    assert not (folder / GAME).exists() and (folder / "own").is_dir()
    run(client, "rename/revert")
    assert (folder / f"{GAME}.nsp").is_file()
    assert client.get("/api/folders/switch/organize").json()["counts"]["moved"] == 0


def test_a_set_without_title_ids_has_no_game_folders(folder_of):
    client, _ = folder_of("nes")
    assert client.get("/api/folders/nes/organize").status_code == HTTPStatus.NOT_FOUND
