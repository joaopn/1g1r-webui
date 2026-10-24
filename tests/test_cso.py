import os
import shutil
import struct
import zlib

import pytest

from g1r import cso
from tests.test_dvds import DVD_SECTOR, SECTORS, proposals

from .waits import finished

HEADER = "<4sIQIBB2x"
PLAIN = 1 << 31
SHIFT = 2


def make_cso(data: bytes, block: int = DVD_SECTOR, version: int = 1) -> bytes:
    """A CSO of `data`: every other block deflated, the rest stored (the plain bit)."""
    header_size = struct.calcsize(HEADER)
    blocks = [data[i : i + block] for i in range(0, len(data), block)]
    index_bytes = struct.calcsize("<I") * (len(blocks) + 1)
    body, index = b"", []
    offset = header_size + index_bytes
    for n, chunk in enumerate(blocks):
        pad = (-offset) % (1 << SHIFT)
        body += b"\0" * pad
        offset += pad
        stored = n % 2 == 1
        if stored:
            payload = chunk
        else:
            packer = zlib.compressobj(9, zlib.DEFLATED, -15)
            payload = packer.compress(chunk) + packer.flush()
        index.append((offset >> SHIFT) | (PLAIN if stored else 0))
        body += payload
        offset += len(payload)
    pad = (-offset) % (1 << SHIFT)
    body += b"\0" * pad
    offset += pad
    index.append(offset >> SHIFT)
    header = struct.pack(HEADER, b"CISO", header_size, len(data), block, version, SHIFT)
    return header + struct.pack(f"<{len(index)}I", *index) + body


def test_a_cso_decodes_to_the_image_it_was_made_from(make_settings, tmp_path):
    settings = make_settings()
    image = os.urandom(DVD_SECTOR * 3) + b"\0" * (DVD_SECTOR * 4) + b"tail"
    source = tmp_path / "A.cso"
    source.write_bytes(make_cso(image))
    assert cso.decode(settings.cso, source, tmp_path / "A.iso") == len(image)
    assert (tmp_path / "A.iso").read_bytes() == image
    # The output is a new file: never written over.
    with pytest.raises(FileExistsError):
        cso.decode(settings.cso, source, tmp_path / "A.iso")


@pytest.mark.parametrize(
    ("damage", "message"),
    [
        (lambda b: b"ZISO" + b[4:], "is not a CSO"),
        (lambda b: b[:20] + b"\x02" + b[21:], "CSO version 2, which is not read"),
        (lambda b: b[: len(b) // 2], "block"),
    ],
)
def test_other_or_damaged_files_are_refused(make_settings, tmp_path, damage, message):
    settings = make_settings()
    source = tmp_path / "A.cso"
    source.write_bytes(damage(make_cso(os.urandom(DVD_SECTOR * 4))))
    with pytest.raises(cso.CsoError, match=message):
        cso.decode(settings.cso, source, tmp_path / "A.iso")


@pytest.mark.skipif(shutil.which("chdman") is None, reason="chdman is not installed")
def test_a_ps2_cso_becomes_a_verified_dvd_chd(folder_of, roms_root):
    client, folder = folder_of("ps2")
    image = os.urandom(DVD_SECTOR * SECTORS)
    original = make_cso(image)
    (folder / "A (USA).cso").write_bytes(original)
    rows = proposals(client, "ps2")
    assert rows["A (USA).cso"]["disc_mode"] == "createdvd"
    plan = client.post("/api/folders/ps2/convert/preview", json={}).json()
    client.post("/api/folders/ps2/convert", json={"token": plan["token"]})
    run = finished(client, "ps2", "run")
    assert (run["status"], run["message"]) == ("done", "1 file converted"), run["failed"]
    assert (folder / "A (USA).chd").is_file() and not (folder / "A (USA).cso").exists()
    assert (roms_root / "discarded/ps2/originals/A (USA).cso").read_bytes() == original
    # Nothing is left behind in the work folder.
    assert not [p for p in folder.iterdir() if p.name not in ("A (USA).chd",)]
