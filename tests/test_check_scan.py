"""P10b: Check files (what conversion needs, nothing hashed) and Scan (identification of the
files with nothing left to convert) as two runs (maintainer, 2026-10-21)."""

from http import HTTPStatus

from g1r import scanner

from .test_api import dat_bytes, scanned, setup  # noqa: F401  (fixture)
from .test_scanner import env, write_zip  # noqa: F401  (fixture)


def identities(conn):
    return dict(conn.execute("SELECT rel_path, game_name FROM identity").fetchall())


def run(folder_scanner, conn, kind):
    folder_scanner.run(conn, folder_scanner.start(conn, "nes", kind), "nes", kind=kind)
    return scanner.latest_scan(conn, "nes")


def test_a_check_reads_what_conversion_needs_and_hashes_nothing(env, monkeypatch):  # noqa: F811
    settings, store, registry, conn, _ = env

    def never(*args, **kwargs):
        raise AssertionError("a check identified or hashed")

    monkeypatch.setattr(scanner, "content_hashes", never)
    folder_scanner = scanner.Scanner(settings, store, registry, never)
    check = run(folder_scanner, conn, scanner.CHECK)
    assert (check["kind"], check["status"]) == ("check", "done")
    assert check["message"] == "3 ROM files checked; 0 to convert"
    assert conn.execute("SELECT COUNT(*) FROM archive_member").fetchone()[0] == 3
    assert identities(conn) == {}


def test_a_check_keeps_what_a_scan_found_for_unchanged_files(env, roms_root):  # noqa: F811
    _, _, _, conn, folder_scanner = env
    run(folder_scanner, conn, scanner.IDENTIFY)
    found = identities(conn)
    assert set(found) == {"Known (USA).zip", "Reheadered (Japan).zip"}
    loose = "SELECT COUNT(*) FROM content_hash WHERE rel_path = 'sub/Loose (Europe).zip'"
    assert conn.execute(loose).fetchone()[0] > 0
    # A changed file loses what was found for it; the others keep theirs (the unmatched
    # file its hashes too).
    write_zip(roms_root / "nes" / "Reheadered (Japan).zip", "Reheadered (Japan).nes", b"new")
    run(folder_scanner, conn, scanner.CHECK)
    assert identities(conn) == {"Known (USA).zip": "Known (USA)"}
    assert conn.execute(loose).fetchone()[0] > 0


def test_a_scan_waits_for_files_not_in_the_target_format(env, roms_root):  # noqa: F811
    """While a file waits for its conversion, a scan stops after its check: igir is not run,
    nothing is identified, and the run is recorded as a check."""
    settings, store, registry, conn, _ = env
    (roms_root / "nes" / "Wait (USA).nes").write_bytes(b"loose")

    def report(*args, **kwargs):
        raise AssertionError("igir ran before every file was converted")

    folder_scanner = scanner.Scanner(settings, store, registry, report)
    scan = run(folder_scanner, conn, scanner.IDENTIFY)
    assert (scan["kind"], scan["status"]) == ("check", "done")
    assert scan["message"].startswith("1 files to convert or discard first")
    assert identities(conn) == {}


def test_check_files_from_the_api(setup, roms_root):  # noqa: F811
    client, _, _ = setup
    (roms_root / "NES Set" / "odd.nes").write_bytes(b"?")
    assert (
        client.post(
            "/api/folders",
            json={"platform": "nes", "mount": "roms", "path": "NES Set", "label": "nes"},
        ).status_code
        == HTTPStatus.CREATED
    )
    assert client.get("/api/folders").json()[0]["needs"] == "check"
    started = client.post("/api/folders/nes/check")
    assert started.status_code == HTTPStatus.ACCEPTED
    for _ in range(500):
        check = client.get("/api/folders/nes/scan").json()
        if check["status"] != "running":
            break
    assert (check["kind"], check["status"]) == ("check", "done")
    # odd.nes waits to be zipped; the Conversion page needs nothing more.
    assert check["message"] == "7 ROM files checked; 1 to convert"
    wrap = [r for r in client.get("/api/folders/nes/conversion").json()["rows"] if r["output"]]
    assert [r["rel_path"] for r in wrap] == ["odd.nes"]
    card = client.get("/api/folders").json()[0]
    assert (card["needs"], card["needs_scan"]) == ("identify", True)
    assert card["scan"]["kind"] == "check" and card["last_scan"] is None
    assert client.get("/api/folders/nes").json()["last_scan"] is None
    titles = [n["title"] for n in client.get("/api/notifications").json()]
    assert titles[0] == "Check files"
    # Listed, not yet looked at by a scan: not unmatched (and no Hasheous hint for them).
    summary = client.get("/api/folders/nes").json()["summary"]
    assert (summary["unmatched"], summary["unscanned"], summary["waiting"]) == (0, 6, 1)
    assert client.get("/api/folders/nes/unmatched").json() == []
    assert card["warnings"] == [] and card["progress"]["to_match"] == 6
    # Once odd.nes is gone, a scan looks at them: the one no DAT lists is unmatched now.
    (roms_root / "NES Set" / "odd.nes").unlink()
    client.post("/api/dats/nes/upload", files={"file": ("nes.dat", dat_bytes())})
    client.post("/api/folders/nes/scan")
    for _ in range(500):
        if client.get("/api/folders/nes/scan").json()["status"] != "running":
            break
    summary = client.get("/api/folders/nes").json()["summary"]
    assert (summary["unmatched"], summary["unscanned"]) == (1, 0)
