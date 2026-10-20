import threading

from g1r import db, scanner
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
