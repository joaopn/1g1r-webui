"""B5: unmatched CHDs are looked up by their largest data track, never by the file's hash."""

import hashlib

import pytest

from g1r import db, hasheous, hashing, scanner, unmatched
from g1r.dat_registry import DatRegistry
from g1r.library import FolderEntry, LibraryStore

from .test_lookups import FakeHasheous

SYSTEM = "Sony - PlayStation"
DISC = "Disc (Europe).chd"
BROKEN = "Broken (Europe).chd"
BIG = "Big (Europe).iso"


def track(index: int, kind: str, size: int, seed: str) -> dict:
    digest = hashlib.sha1(seed.encode()).hexdigest()
    return {
        "index": index,
        "type": kind,
        "size": size,
        "crc32": digest[:8],
        "md5": digest[:32],
        "sha1": digest,
    }


# A data track and a longer audio track: the lookup uses the data track.
TRACKS = [track(0, "MODE2_RAW", 3, "data"), track(1, "AUDIO", 5, "audio")]


def read_chd(settings, path):
    return {"type": "CD_ROM", "tracks": TRACKS} if path.name == DISC else None


@pytest.fixture
def psx(make_settings, roms_root):
    folder = roms_root / "psx"
    folder.mkdir()
    for name in (DISC, BROKEN):
        (folder / name).write_bytes(b"MComprHD" + name.encode())
    settings = make_settings()
    (folder / BIG).write_bytes(b"iso data")
    store = LibraryStore(settings)
    store.update(
        lambda lib: lib.folders.append(
            FolderEntry(label="psx", platform="psx", mount="roms", path="psx")
        )
    )
    store.update(lambda lib: setattr(lib.lookups, "hasheous", True))
    conn = db.open_database(settings)
    registry = DatRegistry(settings, store, lambda url: b"")
    registry.add_upload(
        conn,
        "psx",
        f"""<?xml version="1.0"?><datafile><header><name>{SYSTEM}</name>
        <description>x</description><version>1</version></header>
        <game name="Other (Japan)"><rom name="Other (Japan).bin" size="1" crc="00000000"/>
        </game></datafile>""".encode(),
        "psx.dat",
    )
    return settings, store, registry, conn, folder


def test_a_chd_is_looked_up_by_its_data_track_never_by_its_own_hash(psx):
    settings, store, registry, conn, folder = psx
    data = TRACKS[0]["sha1"]
    post = FakeHasheous(
        {
            data: {
                "signatures": {
                    "Redump": [
                        {
                            "game": {"system": SYSTEM, "description": "Disc (Europe)"},
                            "rom": {"name": "Disc (Europe) (Track 1).bin"},
                        }
                    ]
                }
            }
        }
    )
    folder_scanner = scanner.Scanner(
        settings, store, registry, lambda *a, **_: [], lookup_post=post, read_chd=read_chd
    )
    folder_scanner.run(conn, folder_scanner.start(conn, "psx"), "psx")
    own = {hashlib.sha1((folder / n).read_bytes()).hexdigest() for n in (DISC, BROKEN)}
    assert [a["sha1"] for a in post.asked] == [data]
    assert not own & {a["sha1"] for a in post.asked}
    method = conn.execute("SELECT method FROM identity WHERE rel_path = ?", (DISC,)).fetchone()
    assert method[0] == scanner.METHOD_HASHEOUS
    # The ISO waits for its CHD: identified (and looked up) once converted.
    waiting = folder_scanner.waiting(conn, store.load(), store.load().folder("psx"), folder)
    assert waiting == {BIG}
    rows = unmatched.rows(conn, "psx", hasheous_on=True, waiting=waiting)
    reasons = {r["rel_path"]: r["hasheous"] for r in rows}
    assert reasons == {
        BROKEN: {"status": hasheous.SKIPPED, "detail": "the disc's tracks could not be read"},
    }


def test_the_largest_data_track_stands_for_the_disc(make_settings, tmp_path):
    settings = make_settings()
    gd = [
        track(0, "MODE1_RAW", 2, "low"),
        track(1, "AUDIO", 9, "audio"),
        track(2, "MODE1_RAW", 7, "high"),
    ]
    (found,) = hashing.content_hashes(
        settings, "psx", tmp_path / "x.chd", lambda s, p: {"type": "GD_ROM", "tracks": gd}
    )
    assert (found.variant, found.sha1) == (hashing.FULL, gd[2]["sha1"])
    only_audio = {"type": "CD_ROM", "tracks": [track(0, "AUDIO", 1, "a")]}
    assert (
        hashing.content_hashes(settings, "psx", tmp_path / "x.chd", lambda s, p: only_audio) == []
    )
