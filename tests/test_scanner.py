import shutil
import zipfile
import zlib
from pathlib import Path

import pytest

from g1r import db, hashing, igir, scanner
from g1r.config import HeaderRule
from g1r.dat_registry import DatRegistry
from g1r.library import FolderEntry, LibraryStore

NES_HEADER = bytes.fromhex("4e45531a") + bytes(12)
BODY = b"\x01\x02\x03\x04" * 64


def crc(data: bytes) -> str:
    return format(zlib.crc32(data), "08x")


def dat_xml(games: dict[str, bytes]) -> bytes:
    entries = "".join(
        f'<game name="{name}"><rom name="{name}.nes" size="{len(data)}" crc="{crc(data)}"/></game>'
        for name, data in games.items()
    )
    return (
        "<?xml version='1.0'?><datafile><header><name>Nintendo - Nintendo Entertainment System"
        f"</name><version>1</version></header>{entries}</datafile>"
    ).encode()


def write_zip(path: Path, member: str, data: bytes) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(member, data)


@pytest.fixture
def env(make_settings, roms_root):
    folder = roms_root / "nes"
    (folder / "sub").mkdir(parents=True)
    write_zip(folder / "Known (USA).zip", "Known (USA).nes", NES_HEADER + BODY)
    write_zip(
        folder / "Reheadered (Japan).zip",
        "Reheadered (Japan).nes",
        bytes.fromhex("4e45531a") + b"\xff" * 12 + BODY[::-1],
    )
    (folder / "sub" / "Loose (Europe).nes").write_bytes(b"unknown data")
    (folder / "metadata.txt").write_text("frontend file")
    (folder / "cover.png").write_bytes(b"png")
    settings = make_settings()
    store = LibraryStore(settings)
    store.update(
        lambda lib: lib.folders.append(
            FolderEntry(label="nes", platform="nes", mount="roms", path="nes")
        )
    )
    conn = db.open_database(settings)
    registry = DatRegistry(settings, store, lambda url: b"")
    registry.add_upload(
        conn,
        "nes",
        dat_xml({"Known (USA)": NES_HEADER + BODY, "Reheadered (Japan)": BODY[::-1]}),
        "nes.dat",
    )

    def fake_report(settings_, dat_file, input_dir):
        assert dat_file.is_file()
        return [
            igir.ReportRow("Known (USA)", "FOUND", (str(input_dir / "Known (USA).zip"),)),
            igir.ReportRow("Known (USA)", "FOUND", (str(input_dir / "Known (USA).zip"),)),
            igir.ReportRow("Missing (USA)", "MISSING", ()),
            igir.ReportRow("", "UNUSED", (str(input_dir / "metadata.txt"),)),
        ]

    return settings, store, registry, conn, scanner.Scanner(settings, store, registry, fake_report)


def test_inventory_kinds(env, roms_root):
    settings, *_ = env
    files = {
        f.rel_path: f.kind
        for f in scanner.inventory(settings, roms_root / "nes", "nes", settings.ignored_filenames)
    }
    assert files == {
        "Known (USA).zip": "archive",
        "Reheadered (Japan).zip": "archive",
        "cover.png": "other",
        "metadata.txt": "ignored",
        "sub/Loose (Europe).nes": "rom",
    }


def test_header_rules():
    nes = HeaderRule(magic_hex="4e45531a", magic_offset=0, header_size=16)
    assert hashing.header_size(nes, NES_HEADER + BODY) == 16
    assert hashing.header_size(nes, BODY) is None
    snes = HeaderRule(size_modulus=1024, header_size=512)
    assert hashing.header_size(snes, bytes(1024 + 512)) == 512
    assert hashing.header_size(snes, bytes(2048)) is None
    with pytest.raises(ValueError):
        HeaderRule(header_size=16)


def test_scan_identifies_by_checksum_and_headerless(env):
    _, _, _, conn, folder_scanner = env
    scan_id = folder_scanner.start(conn, "nes")
    folder_scanner.run(conn, scan_id, "nes")
    scan = scanner.latest_scan(conn, "nes")
    assert scan["status"] == "done" and scan["message"] == "2 of 3 ROM files identified"
    rows = {
        r["rel_path"]: (r["game_name"], r["method"]) for r in conn.execute("SELECT * FROM identity")
    }
    assert rows == {
        "Known (USA).zip": ("Known (USA)", "dat-checksum"),
        "Reheadered (Japan).zip": ("Reheadered (Japan)", "dat-headerless"),
    }
    summary = scanner.folder_summary(conn, "nes")
    assert (summary["roms"], summary["identified"], summary["unmatched"]) == (3, 2, 1)
    assert [r["rel_path"] for r in scanner.unmatched_files(conn, "nes")] == [
        "sub/Loose (Europe).nes"
    ]
    assert {r["rel_path"] for r in scanner.other_files(conn, "nes")} == {
        "metadata.txt",
        "cover.png",
    }


def test_rescan_replaces_results(env, roms_root):
    _, _, _, conn, folder_scanner = env
    for _ in range(2):
        folder_scanner.run(conn, folder_scanner.start(conn, "nes"), "nes")
    assert conn.execute("SELECT COUNT(*) FROM folder_file").fetchone()[0] == 5


def test_scan_without_dat_takes_the_inventory_only(env, make_settings):
    settings, store, registry, conn, folder_scanner = env
    store.update(lambda lib: lib.dats.clear())
    folder_scanner.run(conn, folder_scanner.start(conn, "nes"), "nes")
    scan = scanner.latest_scan(conn, "nes")
    assert scan["status"] == "done" and "no active DAT" in scan["message"]
    assert conn.execute("SELECT COUNT(*) FROM folder_file").fetchone()[0] == 5
    assert conn.execute("SELECT COUNT(*) FROM identity").fetchone()[0] == 0


def test_scan_records_archive_members(env):
    _, _, _, conn, folder_scanner = env
    folder_scanner.run(conn, folder_scanner.start(conn, "nes"), "nes")
    member = conn.execute(
        "SELECT member, size, crc32 FROM archive_member WHERE rel_path = 'Known (USA).zip'"
    ).fetchone()
    assert tuple(member) == ("Known (USA).nes", len(NES_HEADER + BODY), crc(NES_HEADER + BODY))


def test_one_scan_at_a_time_and_interrupted_scans(env):
    _, _, _, conn, folder_scanner = env
    folder_scanner.start(conn, "nes")
    with pytest.raises(scanner.ScanError, match="already running"):
        folder_scanner.start(conn, "nes")
    scanner.fail_interrupted(conn)
    assert scanner.latest_scan(conn, "nes")["message"] == "interrupted by a restart"


def test_parse_igir_report(tmp_path):
    report = tmp_path / "r.csv"
    report.write_text(
        "DAT Name,Game Name,Status,ROM Files,Patched\n"
        "D,Game A,FOUND,/roms/a.zip,false\n"
        "D,Game B,FOUND,/roms/b (Track 1).bin|/roms/b.cue,false\n"
        "D,Game C,MISSING,,false\n"
        "D,,UNUSED,/roms/x.txt,false\n",
        encoding="utf-8",
    )
    found = igir.identified_files(igir.parse_report(report))
    assert found == {
        "/roms/a.zip": {"Game A"},
        "/roms/b (Track 1).bin": {"Game B"},
        "/roms/b.cue": {"Game B"},
    }


@pytest.mark.skipif(shutil.which("igir") is None, reason="igir is only in the Docker image")
def test_real_igir_report(env, roms_root):
    settings, store, registry, conn, _ = env
    real = scanner.Scanner(settings, store, registry)
    real.run(conn, real.start(conn, "nes"), "nes")
    rows = dict(conn.execute("SELECT rel_path, method FROM identity").fetchall())
    assert rows["Known (USA).zip"] == "dat-checksum"
