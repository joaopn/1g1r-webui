from pathlib import Path

from g1r import hashing

from .test_api import scanned, setup  # noqa: F401  (fixture)
from .test_journal import versions, wait_run
from .test_scanner import write_zip

DUPLICATES = Path("discarded") / "nes" / "duplicates"


def games(client):
    return {g["name"]: g for g in client.get("/api/folders/nes/games").json()}


def test_an_unmatched_identical_copy_joins_its_game_and_goes_to_duplicates(
    setup,  # noqa: F811
    roms_root,
):
    client, _, _ = setup
    folder = roms_root / "NES Set"
    # Same ROM data as Contra (USA), under a name no DAT lists: only step 2 identifies it.
    write_zip(folder / "contra copy.zip", "whatever.nes", b"Contra (USA)")
    scanned(client)
    copy = versions(client)["contra copy.zip"]
    assert (copy["method"], copy["game_name"]) == ("duplicate", "Contra (USA)")
    assert copy["identical"] == ["Contra (USA).zip"]
    assert "contra copy.zip" not in [
        f["rel_path"] for f in client.get("/api/folders/nes/unmatched").json()
    ]

    contra = games(client)["Contra"]
    assert contra["status"] == "decided" and contra["kept"] == "Contra (USA).zip"
    reasons = {v["rel_path"]: v["discard_reason"] for v in contra["versions"]}
    assert reasons == {
        "Contra (USA).zip": None,
        "Contra (Japan).zip": "1g1r",
        "contra copy.zip": "duplicates",
    }
    plan = client.post("/api/folders/nes/apply/preview", json={"group_key": contra["key"]}).json()
    client.post("/api/folders/nes/apply", json={"group_key": contra["key"], "token": plan["token"]})
    assert wait_run(client)["status"] == "done"
    assert (roms_root / DUPLICATES / "contra copy.zip").exists()
    assert (roms_root / "discarded" / "nes" / "1g1r" / "Contra (Japan).zip").exists()
    assert games(client)["Contra"]["status"] == "applied"


def test_an_undecided_game_still_sheds_its_identical_copies(setup, roms_root):  # noqa: F811
    client, _, _ = setup
    write_zip(roms_root / "NES Set" / "gradius again.zip", "g.nes", b"Gradius (USA)")
    scanned(client)
    gradius = games(client)["Gradius"]
    assert gradius["status"] == "undecided" and gradius["kept"] is None
    proposed = {v["rel_path"]: v["discard_reason"] for v in gradius["versions"]}
    assert proposed == {
        "Gradius (USA).zip": None,
        "Gradius (USA) (Rev 1).zip": None,
        "gradius again.zip": "duplicates",
    }

    # Picking the copy keeps it and sheds the one that stood in for it.
    client.put(
        "/api/folders/nes/keep",
        json={"group_key": gradius["key"], "rel_path": "gradius again.zip"},
    )
    picked = {v["rel_path"]: v["discard_reason"] for v in games(client)["Gradius"]["versions"]}
    assert picked == {
        "Gradius (USA).zip": "duplicates",
        "Gradius (USA) (Rev 1).zip": "1g1r",
        "gradius again.zip": None,
    }


def test_different_data_of_the_same_size_is_not_a_duplicate(setup, roms_root):  # noqa: F811
    client, _, _ = setup
    # Same size as Solo (Japan)'s data, different bytes.
    write_zip(roms_root / "NES Set" / "solo-ish.zip", "s.nes", b"Solo (Jap@n)")
    scanned(client)
    assert "solo-ish.zip" not in versions(client)
    unmatched = [f["rel_path"] for f in client.get("/api/folders/nes/unmatched").json()]
    assert "solo-ish.zip" in unmatched


def test_same_size_files_whose_start_differs_are_never_read_whole(
    setup,  # noqa: F811
    roms_root,
    monkeypatch,
):
    """Copies are found by size, then by the SHA1 of their first bytes, then by their full
    SHA1: an identified file the same size as an unmatched one, but starting differently,
    is never hashed whole."""
    client, _, _ = setup
    write_zip(roms_root / "NES Set" / "solo-ish.zip", "s.nes", b"Xolo (Japan)")
    whole = []
    payloads = hashing.payloads

    def recorded(settings, path, *args, limit=None, **kwargs):
        if limit is None:
            whole.append(path.name)
        return payloads(settings, path, *args, limit=limit, **kwargs)

    monkeypatch.setattr(hashing, "payloads", recorded)
    scanned(client)
    assert "Solo (Japan).zip" not in whole
    assert "solo-ish.zip" in {
        f["rel_path"] for f in client.get("/api/folders/nes/unmatched").json()
    }
