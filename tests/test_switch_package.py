"""NSZ to NSP: synthetic packages in nsz's layout; every NCA must come back byte for byte,
proven by its content ID."""

import hashlib
import struct
from http import HTTPStatus

import pytest
import zstandard
from Cryptodome.Cipher import AES

from g1r import switch_package
from tests.test_switch import pfs0, ticket, wait_run

ORIGINALS = "discarded/switch/originals"
KEY, COUNTER = b"\x55" * 16, bytes(range(16))


def nca(seed: int, body_bytes: int, c) -> tuple[bytes, bytes]:
    """An "NCA": its first ncz_header_bytes, then one CTR section; also its decrypted body."""
    head = bytes((seed + i) % 251 for i in range(c.ncz_header_bytes))
    # Compressible, with some variation.
    plain = b"".join(bytes([seed, i % 256]) * 64 for i in range(body_bytes // 128))
    iv = COUNTER[:8] + (c.ncz_header_bytes // 16).to_bytes(8, "big")
    return head + AES.new(KEY, AES.MODE_CTR, nonce=b"", initial_value=iv).encrypt(plain), plain


def name_of(data: bytes, suffix=".nca") -> str:
    return hashlib.sha256(data).hexdigest()[:32] + suffix


def ncz(data: bytes, plain: bytes, c, block_exponent: int | None = None) -> bytes:
    head = data[: c.ncz_header_bytes]
    out = head + c.section_magic.encode() + struct.pack(c.count, 1)
    out += struct.pack(c.section, c.ncz_header_bytes, len(plain), 3, KEY, COUNTER)
    if block_exponent is None:
        return out + zstandard.ZstdCompressor().compress(plain)
    block = 1 << block_exponent
    blocks = []
    for at in range(0, len(plain), block):
        piece = plain[at : at + block]
        packed = zstandard.ZstdCompressor().compress(piece)
        # Stored as it is when compressing does not make it smaller than a block.
        blocks.append(packed if len(packed) < len(piece) else piece)
    out += c.block_magic.encode() + struct.pack(
        c.block_header, 2, 1, 0, block_exponent, len(blocks), len(plain)
    )
    out += b"".join(struct.pack(c.block_size, len(b)) for b in blocks)
    return out + b"".join(blocks)


@pytest.fixture
def parts(make_settings):
    c = make_settings().switch_package
    program, program_plain = nca(1, 0x20000, c)
    meta, _ = nca(2, 0x400, c)
    return c, program, program_plain, meta


def converted(client, rel: str) -> dict:
    client.post("/api/folders/switch/check")
    for _ in range(500):
        if client.get("/api/folders/switch/scan").json()["status"] != "running":
            break
    rows = {r["rel_path"]: r for r in client.get("/api/folders/switch/conversion").json()["rows"]}
    return rows[rel]


def run(client, rel: str) -> dict:
    body = {"rel_paths": [rel]}
    plan = client.post("/api/folders/switch/convert/preview", json=body).json()
    started = client.post("/api/folders/switch/convert", json={**body, "token": plan["token"]})
    assert started.status_code == HTTPStatus.ACCEPTED, started.text
    return wait_run(client)


def nsp_members(path, settings) -> dict[str, bytes]:
    data = path.read_bytes()
    with path.open("rb") as handle:
        from g1r import titles

        start, members = titles.pfs0_members(handle, settings.title_ids)
    return {n: data[start + o : start + o + s] for n, o, s in members}


@pytest.mark.parametrize("block_exponent", [None, 14])
def test_an_nsz_becomes_the_nsp_it_was_made_from(
    folder_of, make_settings, roms_root, parts, block_exponent
):
    c, program, plain, meta = parts
    client, folder = folder_of("switch")
    tik = ticket(make_settings, "0100AAAA00010000")
    program_name, meta_name = name_of(program), name_of(meta, ".cnmt.nca")
    members = {
        program_name.replace(".nca", ".ncz"): ncz(program, plain, c, block_exponent),
        meta_name: meta,
        **tik,
    }
    (folder / "Game.nsz").write_bytes(pfs0(make_settings, members))

    row = converted(client, "Game.nsz")
    assert (row["status"], row["output"]) == ("make nsp", "Game.nsp")
    assert "decompressed" in row["note"]
    assert run(client, "Game.nsz")["status"] == "done"
    out = nsp_members(folder / "Game.nsp", make_settings())
    assert list(out) == [program_name, meta_name, *tik]
    assert out[program_name] == program and out[meta_name] == meta
    assert (roms_root / ORIGINALS / "Game.nsz").exists() and not (folder / "Game.nsz").exists()


def test_what_cannot_become_one_nsp_is_flagged(folder_of, make_settings, parts):
    c, program, plain, meta = parts
    client, folder = folder_of("switch")
    other, _ = nca(3, 0x400, c)
    two = {name_of(program, ".ncz"): ncz(program, plain, c), "a.cnmt.nca": meta}
    two["b.cnmt.nca"] = other
    (folder / "Two.nsz").write_bytes(pfs0(make_settings, two))
    (folder / "Broken.nsz").write_bytes(b"\0" * 0x400)
    two_row, broken = converted(client, "Two.nsz"), converted(client, "Broken.nsz")
    assert two_row["status"] == "flagged" and "holds 2 titles" in two_row["note"]
    assert broken["status"] == "flagged" and "no PFS0" in broken["note"]


def test_game_card_images_are_not_a_switch_format(folder_of):
    client, folder = folder_of("switch")
    (folder / "Game.xci").write_bytes(b"\0" * 0x400)
    (folder / "Game.xcz").write_bytes(b"\0" * 0x400)
    client.post("/api/folders/switch/check")
    for _ in range(500):
        if client.get("/api/folders/switch/scan").json()["status"] != "running":
            break
    rows = client.get("/api/folders/switch/conversion").json()["rows"]
    assert not any(r["rel_path"].startswith("Game.") for r in rows)
    detail = client.get("/api/folders/switch").json()
    assert {f["rel_path"]: f["reason"] for f in detail["unsupported"]} == {
        "Game.xci": ".xci is not a supported format",
        "Game.xcz": ".xcz is not a supported format",
    }


def test_an_ncz_that_does_not_give_its_nca_back_fails(folder_of, make_settings, parts):
    c, program, plain, meta = parts
    client, folder = folder_of("switch")
    damaged = bytearray(plain)
    damaged[100] ^= 1
    members = {name_of(program, ".ncz"): ncz(program, bytes(damaged), c), name_of(meta): meta}
    (folder / "Game.nsz").write_bytes(pfs0(make_settings, members))
    assert converted(client, "Game.nsz")["status"] == "make nsp"
    finished = run(client, "Game.nsz")
    assert finished["status"] == "failed"
    assert "content ID" in finished["failed"][0]["error"]
    assert (folder / "Game.nsz").exists() and not (folder / "Game.nsp").exists()


def test_the_content_id_check_reads_the_written_file(make_settings, tmp_path, parts):
    c, program, plain, meta = parts
    settings = make_settings()
    source = tmp_path / "Game.nsz"
    source.write_bytes(pfs0(make_settings, {name_of(program, ".ncz"): ncz(program, plain, c)}))
    output = tmp_path / "Game.nsp"
    switch_package.build(source, output, settings, lambda: None)
    members = switch_package.plan(source, settings)
    data = bytearray(output.read_bytes())
    data[-1] ^= 1
    output.write_bytes(bytes(data))
    with pytest.raises(switch_package.PackageError, match="content ID"):
        switch_package.prove(output, members, {}, settings, lambda: None)
