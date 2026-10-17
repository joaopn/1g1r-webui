import os
import struct
import zipfile
import zlib
from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient

from g1r import cards
from g1r.web.app import create_app

UNITS = 8
PARTITION_UNIT = 1


def card(
    make_settings, *, encrypted: bool, keep_units: int = UNITS, product: str = ""
) -> tuple[bytes, bytes]:
    """A small NCSD image (media unit = the config's base, exponent 0): the full image as the
    DAT lists it, and the file as dumped (cut after `keep_units` when trimmed)."""
    c = make_settings().card_images["ncsd"]
    unit = c.media_unit_bytes
    image = bytearray(bytes.fromhex(c.padding_hex) * (unit * UNITS))
    data_end = unit * (keep_units if keep_units < UNITS else UNITS)
    image[:data_end] = os.urandom(data_end)
    image[c.magic_offset : c.magic_offset + len(c.magic)] = c.magic.encode()
    struct.pack_into(cards.U32, image, c.image_size_offset, UNITS)
    struct.pack_into(cards.U32, image, c.partition_table_offset, PARTITION_UNIT)
    image[c.flags_offset + c.media_unit_flag] = 0
    ncch = unit * PARTITION_UNIT
    at = ncch + c.ncch_magic_offset
    image[at : at + len(c.ncch_magic)] = c.ncch_magic.encode()
    image[ncch + c.ncch_flags_offset + c.crypto_flag] = 0 if encrypted else c.no_crypto_mask
    code = ncch + c.product_code_offset
    image[code : code + c.product_code_bytes] = product.encode().ljust(c.product_code_bytes, b"\0")
    full = bytes(image)
    return full, full[:data_end]


def test_the_header_tells_encryption_and_trimming(make_settings, tmp_path):
    config = make_settings().card_images["ncsd"]
    full, dumped = card(make_settings, encrypted=False, keep_units=UNITS - 3)
    path = tmp_path / "a.3ds"
    path.write_bytes(dumped)
    info = cards.read_ncsd(config, path, None, len(dumped))
    assert info is not None and info.notes() == [cards.TRIMMED]
    assert info.image_size == len(full)
    chunk = make_settings().apply.copy_chunk_bytes
    assert cards.padded_crc(config, path, None, info.image_size, chunk) == format(
        zlib.crc32(full), "08x"
    )
    full, _ = card(make_settings, encrypted=True)
    with zipfile.ZipFile(tmp_path / "b.zip", "w") as z:
        z.writestr("b.3ds", full)
    info = cards.read_ncsd(config, tmp_path / "b.zip", "b.3ds", len(full))
    assert info is not None and info.notes() == [cards.ENCRYPTED]
    (tmp_path / "c.3ds").write_bytes(b"not a card")
    assert cards.read_ncsd(config, tmp_path / "c.3ds", None, len(b"not a card")) is None


@pytest.fixture
def n3ds(make_settings, roms_root):
    folder = roms_root / "3ds"
    folder.mkdir()
    (roms_root / "discarded").mkdir()
    with TestClient(create_app(make_settings(), report_runner=lambda *a: [])) as client:
        body = {"platform": "3ds", "mount": "roms", "path": "3ds", "label": "3ds"}
        assert client.post("/api/folders", json=body).status_code == HTTPStatus.CREATED
        yield client, folder


def test_trimmed_images_match_and_encrypted_ones_are_flagged(n3ds, make_settings):
    client, folder = n3ds
    trimmed_full, trimmed = card(make_settings, encrypted=False, keep_units=UNITS - 2)
    locked, _ = card(make_settings, encrypted=True)
    (folder / "Trim (USA).3ds").write_bytes(trimmed)
    (folder / "Locked (USA).3ds").write_bytes(locked)
    with zipfile.ZipFile(folder / "Zipped (USA).zip", "w") as z:
        z.writestr("Zipped (USA).3ds", card(make_settings, encrypted=False)[0])
    games = "".join(
        f'<game name="{n}"><rom name="{n}.3ds" size="{len(d)}" crc="{zlib.crc32(d):08x}"/></game>'
        for n, d in (("Trim (USA)", trimmed_full), ("Locked (USA)", locked))
    )
    dat = (
        "<?xml version='1.0'?><datafile><header><name>Nintendo - Nintendo 3DS</name></header>"
        f"{games}</datafile>"
    ).encode()
    client.post("/api/dats/3ds/upload", files={"file": ("3ds.dat", dat)})
    client.post("/api/folders/3ds/scan")
    for _ in range(500):
        if client.get("/api/folders/3ds/scan").json()["status"] != "running":
            break
    versions = {
        v["rel_path"]: v for g in client.get("/api/folders/3ds/games").json() for v in g["versions"]
    }
    assert versions["Trim (USA).3ds"]["method"] == "dat-untrimmed"
    assert versions["Trim (USA).3ds"]["notes"] == ["trimmed"]

    rows = {r["rel_path"]: r for r in client.get("/api/folders/3ds/conversion").json()["rows"]}
    assert rows["Locked (USA).3ds"]["status"] == "flagged"
    assert "decrypted" in rows["Locked (USA).3ds"]["note"]
    assert rows["Trim (USA).3ds"]["status"] == "done"
    assert "trimmed" in rows["Trim (USA).3ds"]["note"]
    zipped = rows["Zipped (USA).zip"]
    assert (zipped["status"], zipped["output"]) == ("unwrap", "Zipped (USA).3ds")


def test_an_encrypted_image_is_suggested_the_entries_with_its_product_code(n3ds, make_settings):
    client, folder = n3ds
    locked, _ = card(make_settings, encrypted=True, product="CTR-P-AWAE")
    (folder / "3DS0032 - Pilotwings Resort (Usa).3ds").write_bytes(locked)
    entries = [
        ("Pilotwings Resort (Japan)", "CTR-P-AWAJ"),
        ("Pilotwings Resort (USA) (En,Fr,Es)", "CTR-P-AWAE"),
        ("Pilotwings Resort (USA) (En,Fr,Es) (Rev 1)", "CTR-P-AWAE"),
    ]
    games = "".join(
        f'<game name="{n}"><serial>{s}</serial>'
        f'<rom name="{n}.3ds" size="{len(locked)}" crc="00000000"/></game>'
        for n, s in entries
    )
    dat = (
        "<?xml version='1.0'?><datafile><header><name>Nintendo - Nintendo 3DS</name></header>"
        f"{games}</datafile>"
    ).encode()
    client.post("/api/dats/3ds/upload", files={"file": ("3ds.dat", dat)})
    client.post("/api/folders/3ds/scan")
    for _ in range(500):
        if client.get("/api/folders/3ds/scan").json()["status"] != "running":
            break
    (row,) = client.get("/api/folders/3ds/unmatched").json()
    names = [s["game_name"] for s in row["suggestions"]]
    # Both releases with the code come first (a revision shares it); the Japanese one after.
    assert names[:2] == [entries[1][0], entries[2][0]]
    assert entries[0][0] in names[2:]
    # A product code is not a checksum: the image stays unmatched until you choose.
    assert client.get("/api/folders/3ds/games").json() == []
