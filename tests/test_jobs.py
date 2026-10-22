import threading

from g1r import db, journal, scanner
from g1r.jobs import Jobs
from g1r.library import FolderEntry
from tests.test_scanner import env  # noqa: F401


def test_scans_of_two_folders_run_side_by_side(env):  # noqa: F811
    """Each scan waits in igir until the other has reached it too: one at a time, both fail."""
    settings, store, registry, conn, _ = env
    store.update(
        lambda lib: lib.folders.append(
            FolderEntry(label="nes-sub", platform="nes", mount="roms", path="nes/sub")
        )
    )
    both = threading.Barrier(2, timeout=settings.database.busy_timeout_ms / 1000)

    def report(settings_, dat_file, input_dir, **_):
        both.wait()
        return []

    jobs = Jobs(settings, scanner.Scanner(settings, store, registry, report))
    ids = [jobs.scan(conn, label) for label in ("nes", "nes-sub")]
    jobs.shutdown()
    check = db.connect(settings.paths.database_path, settings.database.busy_timeout_ms)
    statuses = [
        check.execute("SELECT status, message FROM scan WHERE id = ?", (i,)).fetchone() for i in ids
    ]
    assert [tuple(s)[0] for s in statuses] == ["done", "done"], [tuple(s) for s in statuses]


def test_the_library_limit_holds_scans_back_and_a_new_limit_applies_at_once(env):  # noqa: F811
    settings, store, registry, conn, _ = env
    store.update(
        lambda lib: lib.folders.append(
            FolderEntry(label="nes-sub", platform="nes", mount="roms", path="nes/sub")
        )
    )
    store.update(lambda lib: setattr(lib, "parallel_scans", 1))
    patience = settings.database.busy_timeout_ms / 1000
    release, second = threading.Event(), threading.Event()
    inside = []

    def report(settings_, dat_file, input_dir, **_):
        inside.append(input_dir.name)
        if input_dir.name == "sub":
            second.set()
        release.wait(timeout=patience)
        return []

    jobs = Jobs(settings, scanner.Scanner(settings, store, registry, report))
    for label in ("nes", "nes-sub"):
        jobs.scan(conn, label)
    # One at a time: the second waits behind the first.
    assert not second.wait(timeout=settings.jobs.progress_interval_seconds)
    assert inside == ["nes"]
    store.update(lambda lib: setattr(lib, "parallel_scans", 2))
    jobs.limit_changed()
    assert second.wait(timeout=patience)
    release.set()
    jobs.shutdown()


def test_a_move_on_another_folder_does_not_wait_for_a_conversion(env, roms_root):  # noqa: F811
    settings, store, registry, conn, _ = env
    store.update(
        lambda lib: lib.folders.append(
            FolderEntry(label="other", platform="nes", mount="roms", path="other")
        )
    )
    (roms_root / "other").mkdir()
    loose = roms_root / "other" / "odd.txt"
    loose.write_text("x")
    big = roms_root / "nes" / "Known (USA).zip"
    release, converting = threading.Event(), threading.Event()

    def converter(step):
        converting.set()
        release.wait(timeout=30)
        raise journal.moves.MoveError("stopped by the test")

    jobs = Jobs(settings, scanner.Scanner(settings, store, registry, lambda *a, **k: []), converter)
    stat = big.stat()
    convert = journal.Move(
        "Known (USA).zip",
        "",
        "originals",
        big,
        big.with_suffix(".nes"),
        stat.st_size,
        stat.st_mtime_ns,
        action=journal.CONVERT,
        recipe="unwrap",
    )
    jobs.apply(conn, "nes", journal.APPLY, journal.CONVERT, lambda: [convert])
    assert converting.wait(timeout=10)
    stat = loose.stat()
    move = journal.Move(
        "odd.txt",
        "",
        "manual",
        loose,
        roms_root / "discarded" / "other" / "manual" / "odd.txt",
        stat.st_size,
        stat.st_mtime_ns,
    )
    (roms_root / "discarded" / "other" / "manual").mkdir(parents=True)
    run_id = jobs.apply(conn, "other", journal.APPLY, journal.SCOPE_SET_ASIDE, lambda: [move])
    done = False
    for _ in range(100):
        row = conn.execute("SELECT status FROM apply_run WHERE id = ?", (run_id,)).fetchone()
        if row["status"] != journal.RUNNING:
            done = True
            break
        threading.Event().wait(0.05)
    # A conversion on another folder waits its turn, and says for which folder.
    write = roms_root / "other" / "w.nes"
    write.write_bytes(b"w")
    stat = write.stat()
    second = journal.Move(
        "w.nes",
        "",
        "originals",
        write,
        write.with_suffix(".zip"),
        stat.st_size,
        stat.st_mtime_ns,
        action=journal.CONVERT,
        recipe="wrap",
    )
    waiting_id = jobs.apply(conn, "other", journal.APPLY, journal.CONVERT, lambda: [second])
    assert journal.progress(conn, waiting_id)["waiting_for"] == "nes"
    assert journal.running_conversion(conn, "other")["waiting_for"] == "nes"
    assert journal.running_conversion(conn, "nes")["waiting_for"] is None
    release.set()
    jobs.shutdown()
    assert done, "the move on 'other' waited behind the conversion on 'nes'"
