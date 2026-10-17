import hashlib
import zipfile
import zlib
from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient

from g1r.hashing import native_order, swap_words, word_bytes
from g1r.web.app import create_app

# A ROM in the native (big-endian, .z64) order starts with this magic.
NATIVE = bytes.fromhex("80371240")
WORDS = 64
V64 = 2
LITTLE = 4


def rom(seed: bytes) -> bytes:
    """A small native-order ROM; any whole number of 4-byte words works."""
    body = hashlib.sha256(seed).digest() * WORDS
    return NATIVE + body[len(NATIVE) :]


def dat(games: dict[str, bytes]) -> bytes:
    entries = "".join(
        f'<game name="{name}"><rom name="{name}.z64" size="{len(data)}" '
        f'crc="{zlib.crc32(data):08x}"/></game>'
        for name, data in games.items()
    )
    return (
        "<?xml version='1.0'?><datafile><header><name>Nintendo - Nintendo 64</name></header>"
        f"{entries}</datafile>"
    ).encode()


def test_byte_orders_are_known_by_their_magic(make_settings):
    config = make_settings().byte_orders["n64"]
    native = rom(b"a")
    assert word_bytes(config, native) is None
    assert word_bytes(config, swap_words(native, V64)) == V64
    assert word_bytes(config, swap_words(native, LITTLE)) == LITTLE
    assert swap_words(swap_words(native, LITTLE), LITTLE) == native
    assert native_order(config, swap_words(native, V64)) == native
    # The extension says nothing: an unswapped .v64 is in the native order already.
    assert native_order(config, native) is None


@pytest.fixture
def n64(make_settings, roms_root):
    folder = roms_root / "n64"
    folder.mkdir()
    (roms_root / "discarded").mkdir()
    with TestClient(create_app(make_settings(), report_runner=lambda *a: [])) as client:
        body = {"platform": "n64", "mount": "roms", "path": "n64", "label": "n64"}
        assert client.post("/api/folders", json=body).status_code == HTTPStatus.CREATED
        yield client, folder


def scan(client):
    client.post("/api/folders/n64/scan")
    for _ in range(500):
        result = client.get("/api/folders/n64/scan").json()
        if result["status"] != "running":
            return result
    raise AssertionError("scan did not finish")


def wait_run(client):
    for _ in range(500):
        run = client.get("/api/folders/n64/run").json()
        if run and run["status"] != "running":
            return run
    raise AssertionError("run did not finish")


def versions(client):
    return {
        v["rel_path"]: v for g in client.get("/api/folders/n64/games").json() for v in g["versions"]
    }


def rows(client):
    return {r["rel_path"]: r for r in client.get("/api/folders/n64/conversion").json()["rows"]}


def test_swapped_dumps_match_the_dat_and_are_copies_of_each_other(n64):
    client, folder = n64
    mario = rom(b"mario")
    (folder / "mario.v64").write_bytes(swap_words(mario, V64))
    (folder / "mario le.n64").write_bytes(swap_words(mario, LITTLE))
    client.post("/api/dats/n64/upload", files={"file": ("n64.dat", dat({"Mario (USA)": mario}))})
    scan(client)
    found = versions(client)
    assert {(v["game_name"], v["method"]) for v in found.values()} == {
        ("Mario (USA)", "dat-byteswapped")
    }
    # Both hold the same ROM in the native order: one is kept, the other is a duplicate.
    assert found["mario.v64"]["identical"] == ["mario le.n64"]
    reasons = sorted(str(v["discard_reason"]) for v in found.values())
    assert reasons == ["None", "duplicates"]


def test_swapped_roms_are_rewritten_in_the_native_order(n64, roms_root):
    client, folder = n64
    mario, kart, misnamed = rom(b"mario"), rom(b"kart"), rom(b"misnamed")
    (folder / "mario.v64").write_bytes(swap_words(mario, V64))
    with zipfile.ZipFile(folder / "Kart (USA).zip", "w") as z:
        z.writestr("Kart (USA).n64", swap_words(kart, LITTLE))
    (folder / "native.v64").write_bytes(rom(b"native"))
    (folder / "odd.z64").write_bytes(swap_words(misnamed, V64))
    scan(client)
    found = rows(client)
    m = found["mario.v64"]
    assert (m["status"], m["output"], m["output_member"]) == ("byteswap", "mario.zip", "mario.z64")
    # The zip's own name is taken: the ROM comes out bare first, the next run wraps it.
    k = found["Kart (USA).zip"]
    assert (k["status"], k["output"], k["word_bytes"]) == ("byteswap", "Kart (USA).z64", LITTLE)
    assert found["native.v64"]["status"] == "wrap"
    o = found["odd.z64"]
    assert (o["status"], o["output"], o["output_member"]) == ("byteswap", "odd.zip", "odd.z64")

    plan = client.post("/api/folders/n64/convert/preview", json={}).json()
    assert plan["problems"] == []
    client.post("/api/folders/n64/convert", json={"token": plan["token"]})
    run = wait_run(client)
    assert (run["status"], run["message"]) == ("done", "4 files converted"), run["failed"]
    with zipfile.ZipFile(folder / "mario.zip") as z:
        assert z.namelist() == ["mario.z64"] and z.read("mario.z64") == mario
    assert (folder / "Kart (USA).z64").read_bytes() == kart
    originals = roms_root / "discarded" / "n64" / "originals"
    assert (originals / "mario.v64").read_bytes() == swap_words(mario, V64)
    after = rows(client)
    assert {r["status"] for p, r in after.items() if p != "Kart (USA).z64"} == {"done"}
    # Zipping it again would take the name of the original in discarded/.
    assert "discarded/" in after["Kart (USA).z64"]["note"]

    # Undo: the swapped original comes back and is proposed again.
    listing = client.get("/api/folders/n64/discarded").json()
    (op,) = [
        f["operation_id"]
        for r in listing["reasons"]
        for f in r["files"]
        if f["rel_path"] == "mario.v64"
    ]
    assert client.post("/api/folders/n64/restore", json={"operation_ids": [op]}).status_code == (
        HTTPStatus.ACCEPTED
    )
    assert wait_run(client)["message"] == "1 file restored"
    assert not (folder / "mario.zip").exists()
    assert rows(client)["mario.v64"]["status"] == "byteswap"


def test_a_swapped_rom_named_like_its_output_is_flagged(n64):
    client, folder = n64
    (folder / "odd.z64").write_bytes(swap_words(rom(b"odd"), V64))
    scan(client)
    client.put("/api/settings/targets", json={"targets": {"n64": "plain"}})
    found = rows(client)["odd.z64"]
    assert found["status"] == "flagged" and "rename" in found["note"]


def test_online_lookups_get_the_native_order_hash_too(make_settings, tmp_path):
    from g1r.hashing import FULL, SWAPPED, content_hashes

    native = rom(b"lookup")
    path = tmp_path / "x.v64"
    path.write_bytes(swap_words(native, V64))
    hashes = {h.variant: h.sha1 for h in content_hashes(make_settings(), "n64", path)}
    assert hashes[SWAPPED] == hashlib.sha1(native).hexdigest()
    assert hashes[FULL] == hashlib.sha1(swap_words(native, V64)).hexdigest()


def test_a_dat_listing_each_byte_order_as_a_rom_still_identifies_one_file(n64):
    """libretro's N64 DAT lists a game's .z64 and .v64 as two ROMs; igir reports such a game
    missing unless both are present (the fake report runner finds nothing, as igir did)."""
    client, folder = n64
    mario = rom(b"mario")
    v64 = swap_words(mario, V64)
    game = (
        f'<game name="Mario (USA)"><rom name="Mario (USA).z64" size="{len(mario)}" '
        f'crc="{zlib.crc32(mario):08x}"/><rom name="Mario (USA).v64" size="{len(v64)}" '
        f'crc="{zlib.crc32(v64):08x}"/></game>'
    )
    body = (
        "<?xml version='1.0'?><datafile><header><name>Nintendo - Nintendo 64</name></header>"
        f"{game}</datafile>"
    ).encode()
    (folder / "a.z64").write_bytes(mario)
    (folder / "b.v64").write_bytes(v64)
    (folder / "c.n64").write_bytes(swap_words(mario, LITTLE))
    client.post("/api/dats/n64/upload", files={"file": ("n64.dat", body)})
    scan(client)
    found = {rel: v["method"] for rel, v in versions(client).items()}
    assert found == {"a.z64": "dat-checksum", "b.v64": "dat-checksum", "c.n64": "dat-byteswapped"}
