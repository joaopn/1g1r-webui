"""B8: unmatched RVZs are looked up by their disc, never by the file's hash."""

import hashlib
import struct
import zipfile

import pytest

from g1r import db, discs, hasheous, hashing, scanner, unmatched
from g1r.dat_registry import DatRegistry
from g1r.library import FolderEntry, LibraryStore

from .test_lookups import FakeHasheous

SYSTEM = "Nintendo - GameCube"
DISC = "Disc (Europe).rvz"
BROKEN = "Broken (Europe).rvz"
ZIPPED = "Zipped (Europe).zip"
DISC_SIZE = 1459978240
# The disc's hashes as dolphin-tool gives them: CRC32 and SHA1, no MD5.
DISC_HASH = hashing.ContentHash(
    hashing.FULL, DISC_SIZE, "2a8eb14c", "", "dd7710b006eab61ef8849ff6e97f96a96d31ef43"
)
# What `dolphin-tool verify` printed for a synthetic GameCube RVZ (image 1g1r-webui:p6).
VERIFY_OUTPUT = """CRC32: 2a8eb14c

MD5 not computed
SHA1: dd7710b006eab61ef8849ff6e97f96a96d31ef43
Problems Found: Yes

Severity: High
Summary: The filesystem is invalid or could not be read.
"""


def rvz_bytes(game_id: bytes) -> bytes:
    """An RVZ's two headers, enough for `rvz_identity`; no disc data follows."""
    return struct.pack(
        hashing.RVZ_HEADERS,
        hashing.RVZ_TAG,
        0,
        0,
        0,
        bytes(20),
        DISC_SIZE,
        0,
        bytes(20),
        0,
        0,
        0,
        0,
        game_id,
        0,
        0,
    )


def read_rvz(settings, path):
    return DISC_HASH if path.name == DISC else None


@pytest.fixture
def ngc(make_settings, roms_root):
    folder = roms_root / "ngc"
    folder.mkdir()
    (folder / DISC).write_bytes(rvz_bytes(b"GTST01"))
    (folder / BROKEN).write_bytes(rvz_bytes(b"GBRK01"))
    with zipfile.ZipFile(folder / ZIPPED, "w") as archive:
        archive.writestr("Zipped (Europe).rvz", rvz_bytes(b"GZIP01"))
    settings = make_settings()
    store = LibraryStore(settings)
    store.update(
        lambda lib: lib.folders.append(
            FolderEntry(label="ngc", platform="ngc", mount="roms", path="ngc")
        )
    )
    store.update(lambda lib: setattr(lib.lookups, "hasheous", True))
    conn = db.open_database(settings)
    registry = DatRegistry(settings, store, lambda url: b"")
    registry.add_upload(
        conn,
        "ngc",
        f"""<?xml version="1.0"?><datafile><header><name>{SYSTEM}</name>
        <description>x</description><version>1</version></header>
        <game name="Other (Japan)"><rom name="Other (Japan).iso" size="1" crc="00000000"/>
        </game></datafile>""".encode(),
        "ngc.dat",
    )
    return settings, store, registry, conn, folder


def test_an_rvz_is_looked_up_by_its_disc_never_by_its_own_hash(ngc):
    settings, store, registry, conn, folder = ngc
    post = FakeHasheous(
        {
            DISC_HASH.sha1: {
                "signatures": {
                    "Redump": [
                        {
                            "game": {"system": SYSTEM, "description": "Disc (Europe)"},
                            "rom": {"name": "Disc (Europe).iso"},
                        }
                    ]
                }
            }
        }
    )
    folder_scanner = scanner.Scanner(
        settings, store, registry, lambda *a, **_: [], lookup_post=post, read_rvz=read_rvz
    )
    folder_scanner.run(conn, folder_scanner.start(conn, "ngc"), "ngc")
    # MD5 is left out rather than sent empty: Hasheous answers to CRC32 and SHA1.
    assert post.asked == [{"crc": DISC_HASH.crc32, "sha1": DISC_HASH.sha1}]
    method = conn.execute("SELECT method FROM identity WHERE rel_path = ?", (DISC,)).fetchone()
    assert method[0] == scanner.METHOD_HASHEOUS
    reasons = {r["rel_path"]: r["hasheous"] for r in unmatched.rows(conn, "ngc", hasheous_on=True)}
    assert reasons == {
        BROKEN: {"status": hasheous.SKIPPED, "detail": "the disc could not be read"},
        ZIPPED: {
            "status": hasheous.SKIPPED,
            "detail": "an RVZ inside an archive: convert it first",
        },
    }


def test_an_rvz_has_no_size_cap_and_never_its_container_hash(make_settings, tmp_path):
    settings = make_settings({"lookups": {"max_hash_bytes": 16}})
    rvz = tmp_path / DISC
    rvz.write_bytes(rvz_bytes(b"GTST01"))
    assert hashing.content_hashes(settings, "ngc", rvz, read_rvz=read_rvz) == [DISC_HASH]
    own = hashlib.sha1(rvz.read_bytes()).hexdigest()
    unreadable = hashing.content_hashes(settings, "ngc", rvz, read_rvz=lambda s, p: None)
    assert unreadable == []
    assert own != DISC_HASH.sha1


@pytest.fixture
def fake_dolphin(tmp_path):
    output = tmp_path / "verify.txt"
    output.write_text(VERIFY_OUTPUT)
    tool = tmp_path / "dolphin-tool"
    tool.write_text(f'#!/bin/sh\n[ "$1" = verify ] || exit 1\ncat "{output}"\n')
    tool.chmod(0o755)
    return tool


def test_the_disc_hash_comes_from_one_verify_run(make_settings, tmp_path, fake_dolphin):
    settings = make_settings({"dolphin": {"binary": str(fake_dolphin)}})
    rvz = tmp_path / DISC
    rvz.write_bytes(rvz_bytes(b"GTST01"))
    assert hashing.rvz_disc_hash(settings, rvz) == DISC_HASH
    not_rvz = tmp_path / "Not (Europe).rvz"
    not_rvz.write_bytes(bytes(len(rvz.read_bytes())))
    assert hashing.rvz_disc_hash(settings, not_rvz) is None


def test_a_failed_verify_reads_no_disc(make_settings, tmp_path):
    tool = tmp_path / "dolphin-tool"
    tool.write_text("#!/bin/sh\necho 'Error: Unable to open input file'\nexit 1\n")
    tool.chmod(0o755)
    settings = make_settings({"dolphin": {"binary": str(tool)}})
    rvz = tmp_path / DISC
    rvz.write_bytes(rvz_bytes(b"GTST01"))
    assert hashing.rvz_disc_hash(settings, rvz) is None
    with pytest.raises(discs.DiscError):
        discs.rvz_digests(settings.dolphin, tmp_path, rvz)
