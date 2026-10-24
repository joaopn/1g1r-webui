import functools
import hashlib
import io
import re
import zipfile
from contextlib import contextmanager
from pathlib import Path

import pytest
from pyctr.crypto import engine as pyctr_engine

from g1r import archives, cards, decrypt, scanner
from tests.ncch_image import UNIT, card, regions
from tests.waits import finished

TITLE = "0004000000031c00"


def scan(client):
    """Scan the 3DS folder (no DAT: a decryption proves itself) and return its conversion
    rows by path."""
    client.post("/api/folders/3ds/scan")
    finished(client, "3ds")
    return {r["rel_path"]: r for r in client.get("/api/folders/3ds/conversion").json()["rows"]}


def convert(client):
    plan = client.post("/api/folders/3ds/convert/preview", json={}).json()
    client.post("/api/folders/3ds/convert", json={"token": plan["token"]})
    return finished(client, "3ds", "run")


def seeddb(*titles: str) -> bytes:
    """A seeddb holding a seed for each title (program ID as `CardInfo` writes it)."""
    entries = b"".join(bytes.fromhex(t)[::-1] + b"\5" * 16 + b"\0" * 8 for t in titles)
    return len(titles).to_bytes(4, "little") + b"\0" * 12 + entries


@pytest.fixture
def fake_decrypt(monkeypatch):
    """Stands in for pyctr (which needs real console keys): writes the given image."""
    images: dict[str, bytes] = {}

    def write(settings, config, source: Path, output: Path) -> None:
        with output.open("xb") as out:
            out.write(images[source.name])

    monkeypatch.setattr(decrypt, "decrypt_cci", write)
    return images


def test_a_decrypted_image_proves_itself_with_its_own_hashes(make_settings, tmp_path):
    config = make_settings().card_images["ncsd"]
    image = card(make_settings, encrypted=False)
    path = tmp_path / "a.3ds"
    path.write_bytes(image)
    assert cards.prove_decrypted(config, path, lambda: None) > 0
    # One byte wrong anywhere the hashes cover: refused, naming where.
    for region, at in regions(config).items():
        broken = bytearray(image)
        broken[at] ^= 1
        path.write_bytes(broken)
        with pytest.raises(cards.ProofError, match=re.escape(f"partition 0's {region}")):
            cards.prove_decrypted(config, path, lambda: None)
    # Cut inside the data, or not a card at all.
    path.write_bytes(image[: len(image) // 2])
    with pytest.raises(cards.ProofError):
        cards.prove_decrypted(config, path, lambda: None)
    path.write_bytes(b"\0" * len(image))
    with pytest.raises(cards.ProofError, match="not a 3DS card image"):
        cards.prove_decrypted(config, path, lambda: None)


def test_damage_in_the_data_is_told_from_a_wrong_decryption(make_settings, tmp_path):
    config = make_settings().card_images["ncsd"]
    image = card(make_settings, encrypted=False)
    path = tmp_path / "a.3ds"
    for region, at in regions(config).items():
        broken = bytearray(image)
        broken[at] ^= 1
        path.write_bytes(broken)
        with pytest.raises(cards.ProofError) as failed:
            cards.prove_decrypted(config, path, lambda: None)
        # Only a RomFS block, checked after the RomFS header proved its key, is bad data.
        assert failed.value.damaged == region.startswith("RomFS (level")
        assert failed.value.offset <= at


def test_a_blank_partition_is_left_out_of_the_proof(make_settings, tmp_path):
    config = make_settings().card_images["ncsd"]
    path = tmp_path / "a.3ds"
    plain = card(make_settings, encrypted=False)
    path.write_bytes(plain)
    checked = cards.prove_decrypted(config, path, lambda: None)
    for byte in (0, 255):
        path.write_bytes(card(make_settings, encrypted=False, blank=7, blank_byte=byte))
        assert cards.prove_decrypted(config, path, lambda: None) == checked
    # Anything else in a partition slot must be a partition that proves itself.
    junk = bytearray(card(make_settings, encrypted=False, blank=7))
    junk[len(plain) - 2 * UNIT + 1] = 1  # inside the blank partition, after the game's
    path.write_bytes(junk)
    with pytest.raises(cards.ProofError, match="partition 7 is not an NCCH partition"):
        cards.prove_decrypted(config, path, lambda: None)


def test_a_blank_partition_is_copied_as_it_is(make_settings, keys_root, tmp_path, monkeypatch):
    settings = make_settings()
    config = settings.card_images["ncsd"]
    (keys_root / settings.decryption.boot9_file).write_bytes(b"key")

    # Stored decrypted already, so pyctr copies the game partition with no key work: its
    # engine needs no real boot9, only a key X in the slot it sets up.
    def engine(boot9):
        crypto = pyctr_engine.CryptoEngine(setup_b9_keys=False)
        crypto.set_keyslot("x", pyctr_engine.Keyslot.NCCH, bytes(16))
        return crypto

    monkeypatch.setattr(decrypt, "CryptoEngine", engine)
    # The test RomFS is random bytes under a right hash tree, no file system to list.
    monkeypatch.setattr(
        decrypt, "NCCHReader", functools.partial(decrypt.NCCHReader, load_sections=False)
    )
    image = card(make_settings, encrypted=False, blank=7)
    (tmp_path / "a.3ds").write_bytes(image)
    decrypt.decrypt_cci(settings, config, tmp_path / "a.3ds", tmp_path / "b.3ds")
    assert (tmp_path / "b.3ds").read_bytes() == image
    assert cards.prove_decrypted(config, tmp_path / "b.3ds", lambda: None) > 0


def test_the_header_tells_a_seed_and_the_program_id(make_settings, tmp_path):
    config = make_settings().card_images["ncsd"]
    path = tmp_path / "a.3ds"
    path.write_bytes(card(make_settings, encrypted=True, seed=True, program_id=TITLE))
    info = cards.read_ncsd(config, path, None, path.stat().st_size)
    assert (info.encrypted, info.seed, info.program_id) == (True, True, TITLE)


def test_without_keys_an_encrypted_image_says_where_they_go(n3ds, make_settings, keys_root):
    client, folder = n3ds
    (folder / "P (USA).3ds").write_bytes(card(make_settings, encrypted=True))
    row = scan(client)["P (USA).3ds"]
    assert row["status"] == "flagged"
    assert "add your console's boot9 under Console keys on this page" in row["note"]


def test_a_decryption_needs_no_dat(n3ds, make_settings, keys_root):
    client, folder = n3ds
    (keys_root / "boot9_prot.bin").write_bytes(b"key")
    (folder / "P (USA).3ds").write_bytes(card(make_settings, encrypted=True))
    p = scan(client)["P (USA).3ds"]
    assert (p["status"], p["output"], p["recipe"]) == (
        "decrypt",
        "P (USA) (Decrypted).3ds",
        "decrypt",
    )
    assert p["originals_to"].endswith("discarded/3ds/originals/P (USA).3ds")
    assert "hashes its partitions carry" in p["verify"]


def test_a_seed_title_needs_its_seed_before_it_is_proposed(n3ds, make_settings, keys_root):
    client, folder = n3ds
    (keys_root / "boot9_prot.bin").write_bytes(b"key")
    (folder / "S (USA).3ds").write_bytes(
        card(make_settings, encrypted=True, seed=True, program_id=TITLE)
    )
    row = scan(client)["S (USA).3ds"]
    assert row["status"] == "flagged" and "add your console's seeddb" in row["note"]
    (keys_root / "seeddb.bin").write_bytes(seeddb("0004000000099900"))
    row = scan(client)["S (USA).3ds"]
    assert row["status"] == "flagged"
    assert f"its seed (title {TITLE}) is not in the seeddb added" in row["note"]
    (keys_root / "seeddb.bin").write_bytes(seeddb("0004000000099900", TITLE))
    assert scan(client)["S (USA).3ds"]["status"] == "decrypt"


def test_only_a_right_decryption_is_kept(n3ds, make_settings, keys_root, roms_root, fake_decrypt):
    client, folder = n3ds
    (keys_root / "boot9_prot.bin").write_bytes(b"key")
    locked = card(make_settings, encrypted=True)
    clear = card(make_settings, encrypted=False)
    (folder / "P (USA).3ds").write_bytes(locked)
    scan(client)

    # A wrong result (one byte off in the game data) changes nothing.
    broken = bytearray(clear)
    broken[regions(make_settings().card_images["ncsd"])["RomFS (level 3"]] ^= 1
    fake_decrypt["P (USA).3ds"] = bytes(broken)
    run = convert(client)
    assert run["status"] == "failed" and "is damaged about 1 MB in" in run["failed"][0]["error"]
    assert (folder / "P (USA).3ds").read_bytes() == locked
    assert sorted(p.name for p in folder.iterdir()) == ["P (USA).3ds"]

    fake_decrypt["P (USA).3ds"] = clear
    run = convert(client)
    assert (run["status"], run["message"]) == ("done", "1 file converted"), run["failed"]
    assert (folder / "P (USA) (Decrypted).3ds").read_bytes() == clear
    assert (roms_root / "discarded/3ds/originals/P (USA).3ds").read_bytes() == locked
    # The output is no longer encrypted, and restore brings the original back.
    rows = {r["rel_path"]: r for r in client.get("/api/folders/3ds/conversion").json()["rows"]}
    out = rows["P (USA) (Decrypted).3ds"]
    assert out["status"] == "done" and "encrypted" not in out["note"]
    client.post("/api/folders/3ds/restore", json={})
    finished(client, "3ds", "run")
    assert sorted(p.name for p in folder.iterdir()) == ["P (USA).3ds"]


def test_an_image_filled_up_after_a_cut_says_where_the_data_ends(
    n3ds, make_settings, keys_root, roms_root, fake_decrypt
):
    client, folder = n3ds
    (keys_root / "boot9_prot.bin").write_bytes(b"key")
    config = make_settings().card_images["ncsd"]
    # Only the start of the game data arrived; the rest of the file is zeros up to its size.
    cut = regions(config)["RomFS (level 3"] + 10
    locked = card(make_settings, encrypted=True)
    locked = locked[:cut] + bytes(len(locked) - cut)
    (folder / "P (USA).3ds").write_bytes(locked)
    scan(client)
    clear = card(make_settings, encrypted=False)
    fake_decrypt["P (USA).3ds"] = clear[:cut] + bytes(len(clear) - cut)
    run = convert(client)
    error = run["failed"][0]["error"]
    assert "is cut short: from about 1 MB to its end it holds only 00 bytes" in error, error
    assert (folder / "P (USA).3ds").read_bytes() == locked

    # The failed file can then be moved to discarded/ like a flagged one.
    body = {"rel_paths": ["P (USA).3ds"]}
    plan = client.post("/api/folders/3ds/set-aside/preview", json=body).json()
    assert plan["problems"] == [] and len(plan["files"]) == 1
    client.post("/api/folders/3ds/set-aside", json={**body, "token": plan["token"]})
    finished(client, "3ds", "run")
    assert (roms_root / "discarded/3ds/manual/P (USA).3ds").read_bytes() == locked
    assert not (folder / "P (USA).3ds").exists()


def test_the_fill_that_ends_a_file_is_found():
    for data, want in (
        (b"abc" + b"\0" * 9, (3, 0)),
        (b"abc\xff", (3, 255)),
        (b"\0" * 5, (0, 0)),
        (b"ab" + b"\0" * 3 + b"\xff" * 4, (5, 255)),
        (b"a" * 4 + b"b" * 4, (4, ord("b"))),
    ):
        for chunk in (1, 2, 3, 4, 64):
            assert cards.trailing_fill(io.BytesIO(data), chunk, lambda: None) == want, (data, chunk)


def test_a_trimmed_image_stays_trimmed(n3ds, make_settings, keys_root, fake_decrypt):
    # Trimming cuts the card's padding, which no hash covers.
    client, folder = n3ds
    (keys_root / "boot9_prot.bin").write_bytes(b"key")
    pad = 3
    locked = card(make_settings, encrypted=True, padding_units=pad)
    clear = card(make_settings, encrypted=False, padding_units=pad)
    unit = make_settings().card_images["ncsd"].media_unit_bytes
    (folder / "T (USA).3ds").write_bytes(locked[: -pad * unit])
    assert scan(client)["T (USA).3ds"]["status"] == "decrypt"
    fake_decrypt["T (USA).3ds"] = clear[: -pad * unit]
    assert convert(client)["status"] == "done"
    assert (folder / "T (USA) (Decrypted).3ds").read_bytes() == clear[: -pad * unit]


def test_an_encrypted_image_in_a_zip_is_unpacked_and_decrypted_at_once(
    n3ds, make_settings, keys_root, roms_root, fake_decrypt
):
    client, folder = n3ds
    locked = card(make_settings, encrypted=True)
    clear = card(make_settings, encrypted=False)
    with zipfile.ZipFile(folder / "P (USA).zip", "w") as z:
        z.writestr("P (USA).3ds", locked)
    # Without keys it is only unpacked, as any zip.
    assert scan(client)["P (USA).zip"]["status"] == "unwrap"
    (keys_root / "boot9_prot.bin").write_bytes(b"key")
    row = scan(client)["P (USA).zip"]
    assert (row["status"], row["output"]) == ("decrypt", "P (USA) (Decrypted).3ds")
    assert "unpacked to a work folder" in row["note"]
    fake_decrypt["P (USA).3ds"] = clear
    run = convert(client)
    assert (run["status"], run["message"]) == ("done", "1 file converted"), run["failed"]
    assert sorted(p.name for p in folder.iterdir()) == ["P (USA) (Decrypted).3ds"]
    assert (folder / "P (USA) (Decrypted).3ds").read_bytes() == clear
    assert (roms_root / "discarded/3ds/originals/P (USA).zip").is_file()
    # Nothing unpacked is left behind: only the output, and the zip among the originals.
    assert sorted(str(p.relative_to(roms_root)) for p in roms_root.rglob("*") if p.is_file()) == [
        "3ds/P (USA) (Decrypted).3ds",
        "discarded/3ds/originals/P (USA).zip",
    ]


def test_a_7z_card_header_is_read_through_7zip(make_settings, tmp_path, monkeypatch):
    settings = make_settings()
    image = card(make_settings, encrypted=True, seed=True, program_id=TITLE)
    archive = tmp_path / "P (USA).7z"
    archive.write_bytes(b"7z stand-in")
    opened = []

    @contextmanager
    def open_member(_settings, path, member):
        opened.append((path.name, member))
        yield io.BytesIO(image)

    files = [scanner.InventoryFile("P (USA).7z", archive.stat().st_size, 0, "archive")]
    members = [("P (USA).7z", archives.Member("P (USA).3ds", len(image), None))]
    found = scanner.read_cards(settings, "3ds", tmp_path, files, members, open_member=open_member)
    info, member = found["P (USA).7z"]
    assert opened == [("P (USA).7z", "P (USA).3ds")] and member == "P (USA).3ds"
    assert (info.encrypted, info.seed, info.program_id) == (True, True, TITLE)


def test_missing_keys_are_reported(make_settings, tmp_path):
    with pytest.raises(decrypt.DecryptError, match="no boot9 has been added"):
        settings = make_settings()
        decrypt.decrypt_cci(
            settings, settings.card_images["ncsd"], tmp_path / "a.3ds", tmp_path / "b.3ds"
        )


def boot9_like(protected: bytes) -> bytes:
    """A full-size dump whose protected half is `protected`."""
    return b"\0" * len(protected) + protected


def test_keys_are_added_checked_and_removed_from_the_web_ui(n3ds, keys_root, monkeypatch):
    client, _ = n3ds
    assert client.get("/api/keys").json() == {"boot9": False, "seeddb": None, "prod_keys": None}
    # Not a retail boot9: refused, nothing stored.
    bad = client.post("/api/keys/boot9", files={"file": ("boot9.bin", b"\1" * 65536)})
    assert bad.status_code == 400 and "not a retail 3DS boot9" in bad.json()["detail"]
    short = client.post("/api/keys/boot9", files={"file": ("boot9.bin", b"\1" * 100)})
    assert short.status_code == 400 and "32768 or 65536 bytes" in short.json()["detail"]
    assert not list(keys_root.iterdir())
    # The checksum check is pyctr's retail hash; a stand-in hash lets a test file pass.
    protected = b"\2" * 32768
    monkeypatch.setattr(decrypt, "BOOT9_PROT_HASH", hashlib.sha256(protected).hexdigest())
    ok = client.post("/api/keys/boot9", files={"file": ("boot9.bin", boot9_like(protected))})
    assert ok.json() == {"boot9": True, "seeddb": None, "prod_keys": None}
    stored = keys_root / "boot9_prot.bin"
    assert stored.read_bytes() == protected and stored.stat().st_mode & 0o777 == 0o600
    seeddb = (2).to_bytes(4, "little") + b"\0" * 12 + b"\3" * 64
    assert client.post("/api/keys/seeddb", files={"file": ("seeddb.bin", seeddb)}).json() == {
        "boot9": True,
        "seeddb": 2,
        "prod_keys": None,
    }
    junk = client.post("/api/keys/seeddb", files={"file": ("seeddb.bin", seeddb[:-1])})
    assert junk.status_code == 400 and "not a seeddb" in junk.json()["detail"]
    assert client.delete("/api/keys/seeddb").json() == {
        "boot9": True,
        "seeddb": None,
        "prod_keys": None,
    }
    assert client.delete("/api/keys/boot9").json() == {
        "boot9": False,
        "seeddb": None,
        "prod_keys": None,
    }
    assert client.delete("/api/keys/other").status_code == 404
