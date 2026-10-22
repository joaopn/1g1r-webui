import zipfile
from pathlib import Path

import pytest

from g1r import archives, conversion, db, scanner
from g1r.dat_registry import DatRegistry
from g1r.library import FolderEntry, LibraryStore

SLT = """
7-Zip 23.01 (x64)

Listing archive: /roms/gb/Game (USA).7z

--
Path = /roms/gb/Game (USA).7z
Type = 7z
Physical Size = 123

----------
Path = Game (USA).gb
Size = 32768
Packed Size = 100
Attributes = A
CRC = 1A2B3C4D
Folder = -

Path = extras
Size = 0
Attributes = D
Folder = +

"""


def test_parse_slt_lists_files_not_folders():
    assert archives.parse_slt(SLT) == [archives.Member("Game (USA).gb", 32768, "1a2b3c4d")]


# What 7-Zip printed for a .7z holding a folder, an empty file and a track (image's 7z).
SLT_7Z_FOLDER = """
--
Path = /s/t.7z
Type = 7z

----------
Path = 4x4 Jam
Size = 0
Packed Size = 0
Attributes = D drwxrwxr-x
CRC =\x20
Encrypted = -

Path = 4x4 Jam/empty.txt
Size = 0
Packed Size = 0
Attributes = A -rw-rw-r--
CRC =\x20
Encrypted = -

Path = 4x4 Jam/track01.bin
Size = 5
Packed Size = 9
Attributes = A -rw-rw-r--
CRC = E6C1C582
Encrypted = -
"""


def test_parse_slt_knows_a_7z_folder_by_its_attributes():
    """B11: a .7z prints no `Folder` line; an empty file has no CRC."""
    assert archives.parse_slt(SLT_7Z_FOLDER) == [
        archives.Member("4x4 Jam/empty.txt", 0, archives.EMPTY_CRC32),
        archives.Member("4x4 Jam/track01.bin", 5, "e6c1c582"),
    ]
    assert archives.EMPTY_CRC32 == "00000000"


def test_parse_slt_without_members_is_an_error():
    with pytest.raises(archives.ArchiveError):
        archives.parse_slt("garbage")


def test_unreadable_zip_is_an_error(tmp_path, make_settings):
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not a zip")
    with pytest.raises(archives.ArchiveError, match="unreadable zip"):
        archives.list_members(make_settings(), bad)


def zipped(path: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)


@pytest.fixture
def gb(make_settings, roms_root):
    folder = roms_root / "gb"
    folder.mkdir(parents=True)
    zipped(folder / "Zipped (USA).zip", {"Zipped (USA).gb": b"a" * 64})
    zipped(folder / "Readme (USA).zip", {"Readme (USA).gb": b"b" * 64, "readme.txt": b"hi"})
    zipped(folder / "Two (USA).zip", {"Two (USA).gb": b"c", "Two (Japan).gb": b"d"})
    zipped(folder / "Empty.zip", {"notes.txt": b"x"})
    (folder / "Bare (Europe).gb").write_bytes(b"e" * 64)
    (folder / "Clash.gb").write_bytes(b"f")
    zipped(folder / "Clash.zip", {"Clash.gb": b"f"})
    (folder / "Seven (Japan).7z").write_bytes(b"7z")
    settings = make_settings()
    store = LibraryStore(settings)
    store.update(
        lambda lib: lib.folders.append(
            FolderEntry(label="gb", platform="gb", mount="roms", path="gb")
        )
    )
    conn = db.open_database(settings)
    seven = lambda _settings, _path: SLT  # noqa: E731
    folder_scanner = scanner.Scanner(
        settings, store, DatRegistry(settings, store, lambda url: b""), seven_zip=seven
    )
    folder_scanner.run(conn, folder_scanner.start(conn, "gb"), "gb")
    return settings, conn


def by_path(settings, conn, target: str, delete_originals=False):
    found = conversion.rows(
        settings,
        conn,
        "gb",
        "gb",
        settings.platforms.targets[target],
        delete_originals=delete_originals,
    )
    return {r.rel_path: r for r in found}


def test_zip_target(gb):
    settings, conn = gb
    rows = by_path(settings, conn, "zip")
    assert rows["Zipped (USA).zip"].status == conversion.DONE
    assert rows["Readme (USA).zip"].status == conversion.DONE
    # One format: a 7z becomes a zip holding all its members.
    seven = rows["Seven (Japan).7z"]
    assert (seven.status, seven.recipe, seven.output) == (
        conversion.REPACK,
        conversion.RECIPE_REPACK,
        "Seven (Japan).zip",
    )
    assert seven.originals_to.endswith("discarded/gb/originals/Seven (Japan).7z")
    bare = rows["Bare (Europe).gb"]
    assert (bare.status, bare.output) == (conversion.WRAP, "Bare (Europe).zip")
    assert bare.originals_to.endswith("discarded/gb/originals/Bare (Europe).gb")
    assert bare.reversible
    assert rows["Clash.gb"].status == conversion.FLAGGED
    assert "already exists" in rows["Clash.gb"].note
    # The disks of one game stay together in their zip.
    two = rows["Two (USA).zip"]
    assert (two.status, two.note) == (conversion.DONE, "2 ROM files kept together in one archive")
    assert rows["Empty.zip"].note == "no Game Boy ROM inside (gb)"


def test_plain_target(gb):
    settings, conn = gb
    rows = by_path(settings, conn, "plain")
    unwrap = rows["Zipped (USA).zip"]
    assert (unwrap.status, unwrap.output) == (conversion.UNWRAP, "Zipped (USA).gb")
    assert "1 other file" in rows["Readme (USA).zip"].note
    assert rows["Seven (Japan).7z"].status == conversion.UNWRAP
    assert rows["Bare (Europe).gb"].status == conversion.DONE
    # Clash.zip would unwrap onto the existing Clash.gb.
    assert rows["Clash.zip"].status == conversion.FLAGGED
    assert "only single-ROM archives are converted" in rows["Two (USA).zip"].note


def test_delete_originals_makes_the_step_irreversible(gb):
    settings, conn = gb
    bare = by_path(settings, conn, "zip", delete_originals=True)["Bare (Europe).gb"]
    assert bare.originals_to is None and not bare.reversible


def test_counts(gb):
    settings, conn = gb
    counts = conversion.counts(list(by_path(settings, conn, "zip").values()))
    assert counts["to_convert"] == counts["wrap"] + counts["repack"] == 2
    assert counts["flagged"] == 2 and counts["all"] == 8
