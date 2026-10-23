import shutil
import subprocess
import zipfile
import zlib
from pathlib import Path

import pytest

from g1r import db, filecache, hashing, igir, scanner
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
    # Zipped, as the NES target wants it: a loose file would wait for its conversion.
    write_zip(folder / "sub" / "Loose (Europe).zip", "Loose (Europe).nes", b"unknown data")
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

    def fake_report(settings_, dat_file, input_dir, **_):
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
        "sub/Loose (Europe).zip": "archive",
    }
    # A file listed by its path is ignored; the same name elsewhere is not.
    by_path = {
        f.rel_path: f.kind
        for f in scanner.inventory(
            settings, roms_root / "nes", "nes", [], {"cover.png", "Known (USA).zip"}
        )
    }
    assert by_path["cover.png"] == by_path["Known (USA).zip"] == "ignored"
    assert by_path["metadata.txt"] == "other"


def test_ignored_by():
    assert scanner.ignored_by("sub/a [!].png", ["*.txt"], {"sub/a [!].png"}) == "file"
    assert scanner.ignored_by("sub/Notes.TXT", ["*.png", "*.txt"], ()) == "*.txt"
    assert scanner.ignored_by(".DS_Store", [], ()) == "hidden"
    assert scanner.ignored_by("game.nes", ["*.txt"], ()) is None


def test_header_rules():
    nes = HeaderRule(magic_hex="4e45531a", magic_offset=0, header_size=16)
    assert hashing.header_size(nes, NES_HEADER + BODY, len(NES_HEADER + BODY)) == 16
    assert hashing.header_size(nes, BODY, len(BODY)) is None
    snes = HeaderRule(size_modulus=1024, header_size=512)
    # Size rules look at the whole size, not at the bytes read so far.
    assert hashing.header_size(snes, bytes(16), 1024 + 512) == 512
    assert hashing.header_size(snes, bytes(1024 + 512), 2048) is None
    with pytest.raises(ValueError):
        HeaderRule(header_size=16)


def test_scan_identifies_by_checksum_and_headerless(env, roms_root):
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
    # Every file in the folder: ROMs, archives, frontend files and images alike.
    on_disk = sum(p.stat().st_size for p in (roms_root / "nes").rglob("*") if p.is_file())
    assert summary["bytes"] == on_disk
    assert [r["rel_path"] for r in scanner.unmatched_files(conn, "nes")] == [
        "sub/Loose (Europe).zip"
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


def test_scan_writes_its_progress(env):
    settings, store, registry, conn, _ = env
    seen = []

    def report(settings_, dat_file, input_dir, **_):
        row = conn.execute("SELECT stage, files_done, files_total FROM scan").fetchone()
        seen.append(tuple(row))
        return []

    folder_scanner = scanner.Scanner(settings, store, registry, report)
    scan_id = folder_scanner.start(conn, "nes")
    assert tuple(conn.execute("SELECT stage, files_done FROM scan").fetchone()) == (None, None)
    folder_scanner.run(conn, scan_id, "nes")
    # igir counts nothing; the steps after it have files.
    assert seen == [("Matching checksums with igir", None, None)]
    scan = scanner.latest_scan(conn, "nes")
    assert scan["status"] == "done" and scan["stage"] is None and scan["files_total"] is None


def test_progress_writes_at_most_every_interval(env):
    _, _, _, conn, folder_scanner = env
    scan_id = folder_scanner.start(conn, "nes")
    now = [0.0]
    progress = scanner.Progress(conn, scan_id, interval=10, clock=lambda: now[0])

    def row():
        return tuple(conn.execute("SELECT stage, files_done, files_total FROM scan").fetchone())

    items = progress.each("Reading archives", range(3))
    next(items)
    assert row() == ("Reading archives", 0, 3)
    next(items)  # one done, too soon to write
    assert row() == ("Reading archives", 0, 3)
    now[0] = 10
    next(items)
    assert row() == ("Reading archives", 2, 3)
    assert list(items) == []  # the last file is always written
    assert row() == ("Reading archives", 3, 3)
    progress.stage("Matching checksums with igir")
    assert row() == ("Matching checksums with igir", None, None)


def identities(conn):
    return dict(conn.execute("SELECT rel_path, method FROM identity").fetchall())


def test_a_quick_rescan_reads_no_unchanged_file(env, monkeypatch):
    _, _, _, conn, folder_scanner = env
    folder_scanner.run(conn, folder_scanner.start(conn, "nes"), "nes")
    first = identities(conn)
    hashes = conn.execute("SELECT * FROM content_hash").fetchall()

    def must_not_read(*args, **kwargs):
        raise AssertionError("an unchanged file was read again")

    monkeypatch.setattr(scanner, "content_hashes", must_not_read)
    monkeypatch.setattr(scanner.archives, "list_members", must_not_read)
    folder_scanner.run(conn, folder_scanner.start(conn, "nes"), "nes")
    assert scanner.latest_scan(conn, "nes")["status"] == "done"
    assert identities(conn) == first
    assert conn.execute("SELECT * FROM content_hash").fetchall() == hashes
    assert conn.execute("SELECT COUNT(*) FROM archive_member").fetchone()[0] == 3


def test_a_changed_file_is_read_again_and_a_gone_one_forgotten(env, roms_root):
    _, _, _, conn, folder_scanner = env
    folder_scanner.run(conn, folder_scanner.start(conn, "nes"), "nes")
    folder = roms_root / "nes"
    # The unmatched file now holds the known game's data: same name, new size and mtime.
    write_zip(folder / "Reheadered (Japan).zip", "Reheadered (Japan).nes", BODY[::-1])
    (folder / "sub" / "Loose (Europe).zip").unlink()
    folder_scanner.run(conn, folder_scanner.start(conn, "nes"), "nes")
    # Without its header the data is the DAT's "Reheadered (Japan)" as it is: igir's (fake)
    # report does not list it, so it is found by the header-stripped check no more.
    assert "Reheadered (Japan).zip" not in identities(conn)
    cached = {r[0] for r in conn.execute("SELECT rel_path FROM file_cache")}
    assert "sub/Loose (Europe).zip" not in cached
    sizes = {
        r[0]
        for r in conn.execute(
            "SELECT size FROM file_cache WHERE rel_path = 'Reheadered (Japan).zip'"
        )
    }
    assert sizes == {(folder / "Reheadered (Japan).zip").stat().st_size}


def test_a_full_scan_reads_everything_and_igir_hashes_afresh(env, monkeypatch):
    settings, store, registry, conn, _ = env
    calls = []
    cache = igir.cache_path(settings, "nes")

    def report(settings_, dat_file, input_dir, **options):
        calls.append((options, cache.exists()))
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text("hashed")
        return []

    folder_scanner = scanner.Scanner(settings, store, registry, report)
    folder_scanner.run(conn, folder_scanner.start(conn, "nes"), "nes")
    read = []
    listing = scanner.archives.list_members
    monkeypatch.setattr(
        scanner.archives,
        "list_members",
        lambda *args: read.append(args[1].name) or listing(*args),
    )
    folder_scanner.run(conn, folder_scanner.start(conn, "nes"), "nes")
    assert read == []
    folder_scanner.run(conn, folder_scanner.start(conn, "nes"), "nes", full=True)
    assert sorted(read) == ["Known (USA).zip", "Loose (Europe).zip", "Reheadered (Japan).zip"]
    # igir keeps the folder's cache between scans; a full scan starts it again.
    assert [present for _, present in calls] == [False, True, False]
    assert all(options["cache"] == cache for options, _ in calls)


def test_igir_may_take_longer_on_a_larger_folder(env, roms_root):
    """B4: a fixed limit stopped igir on a large disc library before it finished."""
    settings, store, registry, conn, _ = env
    limits = []

    def report(settings_, dat_file, input_dir, **options):
        limits.append(options["timeout"])
        return []

    folder_scanner = scanner.Scanner(settings, store, registry, report)
    folder_scanner.run(conn, folder_scanner.start(conn, "nes"), "nes")
    # Not a ROM (it would wait for its conversion): the limit counts every file igir walks.
    with open(roms_root / "nes" / "Big (Europe).img", "wb") as big:
        big.truncate(int(settings.igir.min_bytes_per_second * settings.igir.timeout_seconds))
    folder_scanner.run(conn, folder_scanner.start(conn, "nes"), "nes")
    small, large = limits
    assert small > settings.igir.timeout_seconds
    assert large - small >= settings.igir.timeout_seconds


def test_igir_limit_stays_within_what_subprocess_can_wait(env):
    """B6: a 5 TB Wii folder made the limit too large for poll(): "timeout is too large"."""
    settings = env[0]
    huge = int(settings.igir.min_bytes_per_second * settings.igir.max_timeout_seconds) * 2
    limit = igir.time_limit(settings, huge)
    assert limit == settings.igir.max_timeout_seconds
    subprocess.run(["true"], capture_output=True, timeout=limit)


def test_cache_steps_change_with_the_settings_they_depend_on():
    nes = HeaderRule(magic_hex="4e45531a", magic_offset=0, header_size=16)
    other = HeaderRule(magic_hex="4e45531a", magic_offset=0, header_size=512)
    assert filecache.step("headerless", [nes]) == filecache.step("headerless", [nes])
    assert filecache.step("headerless", [nes]) != filecache.step("headerless", [other])
    assert filecache.step("members") == "members"


def test_removing_a_set_forgets_what_its_scans_read(env):
    _, _, _, conn, folder_scanner = env
    folder_scanner.run(conn, folder_scanner.start(conn, "nes"), "nes")
    assert conn.execute("SELECT COUNT(*) FROM file_cache").fetchone()[0] > 0
    filecache.forget(conn, "nes")
    assert conn.execute("SELECT COUNT(*) FROM file_cache").fetchone()[0] == 0


def test_each_dat_in_the_order_identifies_what_the_ones_before_it_missed(env, roms_root):
    settings, store, registry, conn, _ = env
    loose = b"unknown data"
    nointro = dat_xml({"Loose (Europe)": loose, "Known (USA)": b"other data"}).replace(
        b"<header>", b"<header><homepage>No-Intro</homepage>"
    )
    registry.add_upload(conn, "nes", nointro, "nointro.dat")
    library = store.load()
    order = [v["source"] for v in registry.active_versions(conn, library, "nes")]
    assert order == ["nointro", "upload"]
    first, second = registry.active_versions(conn, library, "nes")
    asked = []

    def report(settings_, dat_file, input_dir, **_):
        asked.append(dat_file.name)
        if dat_file.name == Path(first["file"]).name:
            return [
                igir.ReportRow(
                    "Loose (Europe)", "FOUND", (str(input_dir / "sub/Loose (Europe).zip"),)
                )
            ]
        return [
            igir.ReportRow("Known (USA)", "FOUND", (str(input_dir / "Known (USA).zip"),)),
            igir.ReportRow("Loose (Europe)", "FOUND", (str(input_dir / "sub/Loose (Europe).zip"),)),
        ]

    folder_scanner = scanner.Scanner(settings, store, registry, report)
    folder_scanner.run(conn, folder_scanner.start(conn, "nes"), "nes")
    assert asked == [Path(first["file"]).name, Path(second["file"]).name]
    rows = {
        r["rel_path"]: (r["game_name"], r["method"], r["dat_sha1"])
        for r in conn.execute("SELECT * FROM identity")
    }
    assert rows == {
        "sub/Loose (Europe).zip": ("Loose (Europe)", "dat-checksum", first["sha1"]),
        "Known (USA).zip": ("Known (USA)", "dat-checksum", second["sha1"]),
        "Reheadered (Japan).zip": ("Reheadered (Japan)", "dat-headerless", second["sha1"]),
    }
    message = scanner.latest_scan(conn, "nes")["message"]
    assert message == "3 of 3 ROM files identified; 1 by No-Intro (DAT-o-MATIC), 2 by Uploaded file"


def test_igir_threads_set_its_readers_and_node_pool(make_settings, tmp_path, monkeypatch):
    settings = make_settings()
    seen = []

    def run(command, **options):
        seen.append((command, options["env"]))
        report = Path(command[command.index("--report-output") + 1])
        report.write_text("DAT Name,Game Name,Status,ROM Files\n")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(igir.subprocess, "run", run)
    cache = tmp_path / "c.cache"
    threads = settings.igir.max_threads
    for chosen in (None, threads):
        igir.run_report(
            settings, tmp_path / "x.dat", tmp_path, cache=cache, timeout=1, threads=chosen
        )
    (own, own_env), (set_, set_env) = seen
    assert "--reader-threads" not in own and own_env is None
    assert set_[set_.index("--reader-threads") + 1] == str(threads)
    assert set_env[igir.POOL_SIZE_ENV] == str(threads)
