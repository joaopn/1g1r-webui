import hashlib
import zipfile
import zlib
from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient

from g1r import igir
from g1r.dats import parse_dat_bytes
from g1r.hashing import swap_words, word_bytes
from g1r.web.app import create_app

from .waits import finished

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


def report_by_crc(settings, dat_file, input_dir, **_):
    """igir as far as these tests need it: a zip whose one ROM has a DAT ROM's CRC32 and size
    is found as that game (no byte-swapped matches, as igir)."""
    games = {
        (rom.crc, rom.size): game.name
        for game in parse_dat_bytes(dat_file.read_bytes()).games
        for rom in game.roms
    }
    rows = []
    for path in sorted(input_dir.glob("*.zip")):
        with zipfile.ZipFile(path) as z:
            (info,) = z.infolist()
            game = games.get((format(info.CRC, "08x"), info.file_size))
        if game:
            rows.append(igir.ReportRow(game, "FOUND", (str(path),)))
    return rows


@pytest.fixture
def n64(make_settings, roms_root):
    folder = roms_root / "n64"
    folder.mkdir()
    (roms_root / "discarded").mkdir()
    # Reads of 3 bytes: every swap and copy crosses a word boundary between reads.
    small_reads = make_settings({"hashing": {"chunk_bytes": 3}, "apply": {"copy_chunk_bytes": 3}})
    with TestClient(create_app(small_reads, report_runner=report_by_crc)) as client:
        body = {"platform": "n64", "mount": "roms", "path": "n64", "label": "n64"}
        assert client.post("/api/folders", json=body).status_code == HTTPStatus.CREATED
        yield client, folder


def scan(client):
    client.post("/api/folders/n64/scan")
    return finished(client, "n64")


def wait_run(client):
    return finished(client, "n64", "run")


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
    # Both wait to be rewritten in the native order: identified once converted (P10).
    assert versions(client) == {}
    assert {r["status"] for r in rows(client).values()} == {"byteswap"}
    plan = client.post("/api/folders/n64/convert/preview", json={}).json()
    client.post("/api/folders/n64/convert", json={"token": plan["token"]})
    assert wait_run(client)["status"] == "done"
    scan(client)
    found = versions(client)
    assert {(v["game_name"], v["method"]) for v in found.values()} == {
        ("Mario (USA)", "dat-checksum")
    }
    # Both hold the same ROM: one is kept, the other is a duplicate.
    assert found["mario.zip"]["identical"] == ["mario le.zip"]
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


def test_the_zip_takes_back_its_originals_name(n64, roms_root):
    """A zip holding a swapped ROM becomes a bare .z64, then a zip under the original's own
    name, which discarded/ holds: the name is free, and restoring that original refuses."""
    client, folder = n64
    kart = rom(b"kart")
    with zipfile.ZipFile(folder / "Kart (USA).zip", "w") as z:
        z.writestr("Kart (USA).n64", swap_words(kart, LITTLE))
    for _ in range(2):
        scan(client)
        plan = client.post("/api/folders/n64/convert/preview", json={}).json()
        assert plan["problems"] == []
        client.post("/api/folders/n64/convert", json={"token": plan["token"]})
        assert wait_run(client)["status"] == "done"
    with zipfile.ZipFile(folder / "Kart (USA).zip") as z:
        assert z.namelist() == ["Kart (USA).z64"] and z.read("Kart (USA).z64") == kart
    listing = client.get("/api/folders/n64/discarded").json()
    (op,) = [
        f["operation_id"]
        for r in listing["reasons"]
        for f in r["files"]
        if f["rel_path"] == "Kart (USA).zip"
    ]
    refused = client.post("/api/folders/n64/restore", json={"operation_ids": [op]})
    assert refused.status_code == HTTPStatus.CONFLICT
    assert "already exists" in refused.text
