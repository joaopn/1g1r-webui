"""Reading Switch NCAs with prod.keys: synthetic NSPs encrypted with made-up keys, laid out as
hactool reads real ones; the XTS core is pinned to a vector from another AES-XTS
implementation (the `cryptography` package, given Nintendo's big-endian sector tweak)."""

import hashlib
import struct
from http import HTTPStatus

import pytest
from Cryptodome.Cipher import AES

from g1r import nca
from tests.test_switch import BASE_ID, cnmt_xml, pfs0, scan, ticket

UPDATE_ID = "0100AAAA00010800"
SECOND_UPDATE = 131072
SECTION_CTR = bytes(range(8, 16))


@pytest.fixture
def keys():
    return {
        "header_key": bytes(range(32)),
        "key_area_key_application_00": b"\x11" * 16,
        "key_area_key_application_01": b"\x22" * 16,
        "titlekek_01": b"\x33" * 16,
    }


def prod_keys(keys: dict[str, bytes]) -> bytes:
    lines = ["; made up for the tests"] + [f"{k} = {v.hex()}" for k, v in keys.items()]
    return "\n".join(lines).encode()


def xts_encrypt(key: bytes, data: bytes, c) -> bytes:
    data_cipher, tweak_cipher = AES.new(key[:16], AES.MODE_ECB), AES.new(key[16:], AES.MODE_ECB)
    out = bytearray()
    for sector, at in enumerate(range(0, len(data), c.sector_bytes)):
        tweak = int.from_bytes(tweak_cipher.encrypt(sector.to_bytes(16, "big")), "little")
        for start in range(at, at + c.sector_bytes, 16):
            mask = tweak.to_bytes(16, "little")
            block = bytes(a ^ b for a, b in zip(data[start : start + 16], mask, strict=True))
            out += bytes(a ^ b for a, b in zip(data_cipher.encrypt(block), mask, strict=True))
            tweak <<= 1
            if tweak >> 128:
                tweak = (tweak & ((1 << 128) - 1)) ^ c.xts_reduction
    return bytes(out)


def make_nca(c, keys, *, content_type: int, payload: bytes, range_offset: int, rights=b""):
    """One NCA: generation 2 (keys of generation 01), one CTR section holding `payload`."""
    section_key = b"\x44" * 16
    header = bytearray(c.header_bytes)
    header[c.magic_offset : c.magic_offset + 4] = c.magic.encode()
    header[c.content_type_offset] = content_type
    header[c.key_generation2_offset] = 2
    start = c.header_bytes // c.sector_bytes
    padded = payload + b"\0" * (-len(payload) % c.sector_bytes)
    struct.pack_into(
        c.section_entry, header, c.section_table_offset, start, start + len(padded) // 512
    )
    fs = c.fs_header_offset
    struct.pack_into(c.fs_kinds, header, fs, 0, 0, c.crypt_ctr)
    struct.pack_into(c.range, header, fs + range_offset, 0, len(payload))
    header[fs + c.section_ctr_offset : fs + c.section_ctr_offset + 8] = SECTION_CTR
    if rights:
        header[c.rights_id_offset : c.rights_id_offset + 16] = rights
    else:
        at = c.key_area_offset + c.ctr_key_index * 16
        area_key = AES.new(keys["key_area_key_application_01"], AES.MODE_ECB)
        header[at : at + 16] = area_key.encrypt(section_key)
    iv = SECTION_CTR[::-1] + (c.header_bytes >> 4).to_bytes(8, "big")
    body = AES.new(section_key, AES.MODE_CTR, nonce=b"", initial_value=iv).encrypt(padded)
    return xts_encrypt(keys["header_key"], bytes(header), c) + body, section_key


def cnmt_nca(c, keys, title_id: str, version: int) -> bytes:
    cnmt = struct.pack(c.cnmt_header, int(title_id, 16), version) + b"\0" * 24
    inner = pfs0_bytes(c, {f"Patch_{title_id.lower()}.cnmt": cnmt})
    return make_nca(c, keys, content_type=c.meta_type, payload=inner, range_offset=0x40)[0]


def pfs0_bytes(c, members):
    class Settings:
        title_ids = c.title_ids

    return pfs0(lambda: Settings, members)


def control_nca(c, keys, display: str, rights: bytes):
    nacp = bytearray(0x4000)
    nacp[c.display_version_offset : c.display_version_offset + len(display)] = display.encode()
    name = c.nacp_name.encode()
    entry = struct.pack(c.romfs_file, 0, 0xFFFFFFFF, 0, len(nacp), 0, len(name))
    entry += name + b"\0" * (-len(name) % 4)
    head = struct.calcsize(c.romfs_header)
    romfs = struct.pack(c.romfs_header, head, len(entry), head + len(entry)) + entry + nacp
    return make_nca(
        c, keys, content_type=c.control_type, payload=bytes(romfs), range_offset=0x90, rights=rights
    )


def update_nsp(c, keys, version: int, display: str) -> bytes:
    """An update NSP without cnmt.xml: its version only in the encrypted metadata, its control
    data under titlekey crypto with a common ticket."""
    rights = bytes.fromhex(UPDATE_ID) + b"\0" * 7 + b"\x02"
    control, section_key = control_nca(c, keys, display, rights)
    title_key = AES.new(keys["titlekek_01"], AES.MODE_ECB).encrypt(section_key)
    tik = bytearray(0x2C0)
    tik[c.ticket_titlekey_offset : c.ticket_titlekey_offset + 16] = title_key
    tik[c.ticket_type_offset] = c.ticket_common
    return pfs0_bytes(
        c,
        {
            "aa.cnmt.nca": cnmt_nca(c, keys, UPDATE_ID, version),
            "bb.nca": control,
            f"{rights.hex()}.tik": bytes(tik),
        },
    )


class Config:
    def __init__(self, settings):
        self.__dict__.update(settings.nca.model_dump())
        self.title_ids = settings.title_ids


def test_xts_matches_another_implementation(make_settings):
    data = bytes(i * 7 % 256 for i in range(0x400))
    out = nca.xts_decrypt(bytes(range(32)), data, make_settings().nca)
    assert hashlib.sha256(out).hexdigest() == (
        "5e941bd92c784c23d8b3553a5796c8b8392d4942ecbc1120255fbde7ef0d02f8"
    )


def test_prod_keys_are_checked(make_settings, keys):
    c = make_settings().nca
    parsed = nca.parse_keys(prod_keys(keys).decode(), c)
    assert parsed.header == keys["header_key"] and sorted(parsed.key_area) == [0, 1]
    assert parsed.titlekek == {1: keys["titlekek_01"]}
    with pytest.raises(nca.KeysError, match="header_key"):
        nca.parse_keys("boot9 = 00", c)


def test_update_version_and_shown_version_need_the_keys(folder_of, make_settings, keys):
    settings = make_settings()
    c = Config(settings)
    client, folder = folder_of("switch")
    (folder / "game.nsp").write_bytes(
        pfs0_bytes(c, ticket(make_settings, BASE_ID) | cnmt_xml(BASE_ID, 0, "Application"))
    )
    (folder / "update old.nsp").write_bytes(
        pfs0_bytes(c, ticket(make_settings, UPDATE_ID) | cnmt_xml(UPDATE_ID, 65536, "Patch"))
    )
    (folder / "update new.nsp").write_bytes(update_nsp(c, keys, SECOND_UPDATE, "1.0.2"))

    scan(client)
    rows = {r["rel_path"]: r for r in client.get("/api/folders/switch/updates").json()["updates"]}
    # Without keys the new update has no version: nothing of the game is proposed.
    assert rows["update new.nsp"]["status"] == "version unknown"
    assert not any(r["operation"] for r in rows.values())

    bad = client.post("/api/keys/prod_keys", files={"file": ("prod.keys", b"nothing = 00")})
    assert bad.status_code == HTTPStatus.BAD_REQUEST
    added = client.post("/api/keys/prod_keys", files={"file": ("prod.keys", prod_keys(keys))})
    assert added.json()["prod_keys"] == len(["00", "01"])

    scan(client)
    rows = {r["rel_path"]: r for r in client.get("/api/folders/switch/updates").json()["updates"]}
    new, old = rows["update new.nsp"], rows["update old.nsp"]
    assert (new["version"], new["display_version"], new["status"]) == (
        SECOND_UPDATE,
        "1.0.2",
        "newest",
    )
    assert old["status"] == "older" and old["operation"]

    assert client.delete("/api/keys/prod_keys").json()["prod_keys"] is None
