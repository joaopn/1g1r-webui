import hashlib
from pathlib import Path

import pytest

from g1r import decrypt
from tests.test_3ds import UNITS, card


def upload(client, games: list[tuple[str, str, bytes]], *, serial="game", nointro=False):
    """Upload a 3DS DAT of (name, serial, decrypted image). `serial`: where the DAT writes it,
    a `<serial>` of the game, an attribute of the rom (as No-Intro does), or nowhere (None).
    `nointro`: the file says it is No-Intro's, so it takes that source (else "upload")."""
    entries = "".join(
        f'<game name="{n}">{f"<serial>{s}</serial>" if serial == "game" else ""}'
        f'<rom name="{n}.3ds" size="{len(d)}" sha1="{hashlib.sha1(d).hexdigest()}"'
        f"{f" serial='{s}'" if serial == 'rom' else ''}/></game>"
        for n, s, d in games
    )
    homepage = "<homepage>No-Intro</homepage>" if nointro else ""
    dat = (
        "<?xml version='1.0'?><datafile><header><name>Nintendo - Nintendo 3DS</name>"
        f"{homepage}</header>{entries}</datafile>"
    ).encode()
    client.post("/api/dats/3ds/upload", files={"file": ("3ds.dat", dat)})


def scan(client, games: list[tuple[str, str, bytes]] | None = None):
    """Upload a 3DS DAT of (name, serial, decrypted image), if given, and scan the folder."""
    if games is not None:
        upload(client, games)
    client.post("/api/folders/3ds/scan")
    for _ in range(500):
        if client.get("/api/folders/3ds/scan").json()["status"] != "running":
            break
    return {r["rel_path"]: r for r in client.get("/api/folders/3ds/conversion").json()["rows"]}


def convert(client):
    plan = client.post("/api/folders/3ds/convert/preview", json={}).json()
    client.post("/api/folders/3ds/convert", json={"token": plan["token"]})
    for _ in range(5000):
        run = client.get("/api/folders/3ds/run").json()
        if run and run["status"] != "running":
            return run
    raise AssertionError("the run did not finish")


@pytest.fixture
def fake_decrypt(monkeypatch):
    """Stands in for pyctr (which needs real console keys): writes the given image."""
    images: dict[str, bytes] = {}

    def write(settings, source: Path, output: Path) -> None:
        with output.open("xb") as out:
            out.write(images[source.name])

    monkeypatch.setattr(decrypt, "decrypt_cci", write)
    return images


def test_without_keys_an_encrypted_image_says_where_they_go(n3ds, make_settings, keys_root):
    client, folder = n3ds
    locked, _ = card(make_settings, encrypted=True, product="CTR-P-AWAE")
    (folder / "P (USA).3ds").write_bytes(locked)
    row = scan(client, [("P (USA)", "CTR-P-AWAE", locked)])["P (USA).3ds"]
    assert row["status"] == "flagged"
    assert "add your console's boot9 under Console keys on this page" in row["note"]


def test_a_decryption_is_proposed_only_when_the_dat_can_prove_it(
    n3ds,
    make_settings,
    keys_root,
):
    client, folder = n3ds
    (keys_root / "boot9_prot.bin").write_bytes(b"key")
    locked, _ = card(make_settings, encrypted=True, product="CTR-P-AWAE")
    clear, _ = card(make_settings, encrypted=False, product="CTR-P-AWAE")
    other, _ = card(make_settings, encrypted=True, product="CTR-P-ZZZZ")
    (folder / "P (USA).3ds").write_bytes(locked)
    (folder / "Z (USA).3ds").write_bytes(other)
    rows = scan(client, [("P (USA)", "CTR-P-AWAE", clear), ("Q (USA)", "CTR-P-QQQE", clear)])
    p = rows["P (USA).3ds"]
    assert (p["status"], p["output"], p["recipe"]) == (
        "decrypt",
        "P (USA) (Decrypted).3ds",
        "decrypt",
    )
    assert p["expect_sha1"] == [hashlib.sha1(clear).hexdigest()]
    assert p["originals_to"].endswith("discarded/3ds/originals/P (USA).3ds")
    assert "P (USA)" in p["verify"]
    z = rows["Z (USA).3ds"]
    assert (
        z["status"] == "flagged" and "no decrypted image with product code CTR-P-ZZZZ" in z["note"]
    )


def test_a_serial_on_the_rom_is_the_games(n3ds, make_settings, keys_root):
    # No-Intro writes the serial as an attribute of <rom>, not as the game's <serial> (B15).
    client, folder = n3ds
    (keys_root / "boot9_prot.bin").write_bytes(b"key")
    locked, _ = card(make_settings, encrypted=True, product="CTR-P-AWAE")
    clear, _ = card(make_settings, encrypted=False, product="CTR-P-AWAE")
    (folder / "P (USA).3ds").write_bytes(locked)
    upload(client, [("P (USA)", "CTR-P-AWAE", clear)], serial="rom", nointro=True)
    row = scan(client)["P (USA).3ds"]
    assert row["status"] == "decrypt"
    assert row["expect_sha1"] == [hashlib.sha1(clear).hexdigest()]


def test_every_active_dat_is_searched_for_the_product_code(n3ds, make_settings, keys_root):
    # The first DAT in the order lists no serials: the next one's entry proves it (B15).
    client, folder = n3ds
    (keys_root / "boot9_prot.bin").write_bytes(b"key")
    locked, _ = card(make_settings, encrypted=True, product="CTR-P-AWAE")
    clear, _ = card(make_settings, encrypted=False, product="CTR-P-AWAE")
    rev, _ = card(make_settings, encrypted=False, product="CTR-P-AWAE")
    other, _ = card(make_settings, encrypted=True, product="CTR-P-ZZZZ")
    (folder / "P (USA).3ds").write_bytes(locked)
    (folder / "Z (USA).3ds").write_bytes(other)
    upload(client, [("P (USA)", "CTR-P-AWAE", clear)], serial=None, nointro=True)
    upload(client, [("P (USA) (Rev 1)", "CTR-P-AWAE", rev)])
    rows = scan(client)
    p = rows["P (USA).3ds"]
    assert p["status"] == "decrypt"
    assert p["expect_sha1"] == [hashlib.sha1(rev).hexdigest()]
    assert "P (USA) (Rev 1)" in p["verify"]
    z = rows["Z (USA).3ds"]
    assert z["status"] == "flagged"
    assert "no decrypted image with product code CTR-P-ZZZZ" in z["note"]
    # The note says which DATs were searched.
    assert "No-Intro" in z["note"] and "Uploaded file" in z["note"]


def test_the_decrypted_image_must_be_the_dats(
    n3ds,
    make_settings,
    keys_root,
    roms_root,
    fake_decrypt,
):
    client, folder = n3ds
    (keys_root / "boot9_prot.bin").write_bytes(b"key")
    locked, _ = card(make_settings, encrypted=True, product="CTR-P-AWAE")
    clear, _ = card(make_settings, encrypted=False, product="CTR-P-AWAE")
    (folder / "P (USA).3ds").write_bytes(locked)
    scan(client, [("P (USA)", "CTR-P-AWAE", clear)])

    # A wrong result changes nothing.
    fake_decrypt["P (USA).3ds"] = clear[:-1] + b"\0"
    run = convert(client)
    assert run["status"] == "failed" and "not the DAT's image" in run["failed"][0]["error"]
    assert (folder / "P (USA).3ds").read_bytes() == locked
    assert sorted(p.name for p in folder.iterdir()) == ["P (USA).3ds"]

    fake_decrypt["P (USA).3ds"] = clear
    run = convert(client)
    assert (run["status"], run["message"]) == ("done", "1 file converted"), run["failed"]
    assert (folder / "P (USA) (Decrypted).3ds").read_bytes() == clear
    assert (roms_root / "discarded/3ds/originals/P (USA).3ds").read_bytes() == locked
    # The output is no longer noted encrypted, and restore brings the original back.
    rows = {r["rel_path"]: r for r in client.get("/api/folders/3ds/conversion").json()["rows"]}
    assert "encrypted" not in rows["P (USA) (Decrypted).3ds"]["note"]
    client.post("/api/folders/3ds/restore", json={})
    for _ in range(5000):
        if client.get("/api/folders/3ds/run").json()["status"] != "running":
            break
    assert sorted(p.name for p in folder.iterdir()) == ["P (USA).3ds"]


def test_a_trimmed_image_is_compared_padded_to_the_card(
    n3ds,
    make_settings,
    keys_root,
    fake_decrypt,
):
    client, folder = n3ds
    (keys_root / "boot9_prot.bin").write_bytes(b"key")
    _, locked = card(make_settings, encrypted=True, product="CTR-P-AWAE", keep_units=UNITS - 2)
    full, trimmed = card(make_settings, encrypted=False, product="CTR-P-AWAE", keep_units=UNITS - 2)
    (folder / "T (USA).3ds").write_bytes(locked)
    rows = scan(client, [("T (USA)", "CTR-P-AWAE", full)])
    assert rows["T (USA).3ds"]["status"] == "decrypt"
    fake_decrypt["T (USA).3ds"] = trimmed
    assert convert(client)["status"] == "done"
    assert (folder / "T (USA) (Decrypted).3ds").read_bytes() == trimmed


def test_missing_keys_are_reported(make_settings, tmp_path):
    with pytest.raises(decrypt.DecryptError, match="no boot9 has been added"):
        decrypt.decrypt_cci(make_settings(), tmp_path / "a.3ds", tmp_path / "b.3ds")


def boot9_like(protected: bytes) -> bytes:
    """A full-size dump whose protected half is `protected`."""
    return b"\0" * len(protected) + protected


def test_keys_are_added_checked_and_removed_from_the_web_ui(n3ds, keys_root, monkeypatch):
    client, _ = n3ds
    assert client.get("/api/keys").json() == {"boot9": False, "seeddb": None}
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
    assert ok.json() == {"boot9": True, "seeddb": None}
    stored = keys_root / "boot9_prot.bin"
    assert stored.read_bytes() == protected and stored.stat().st_mode & 0o777 == 0o600
    seeddb = (2).to_bytes(4, "little") + b"\0" * 12 + b"\3" * 64
    assert client.post("/api/keys/seeddb", files={"file": ("seeddb.bin", seeddb)}).json() == {
        "boot9": True,
        "seeddb": 2,
    }
    junk = client.post("/api/keys/seeddb", files={"file": ("seeddb.bin", seeddb[:-1])})
    assert junk.status_code == 400 and "not a seeddb" in junk.json()["detail"]
    assert client.delete("/api/keys/seeddb").json() == {"boot9": True, "seeddb": None}
    assert client.delete("/api/keys/boot9").json() == {"boot9": False, "seeddb": None}
    assert client.delete("/api/keys/other").status_code == 404
