"""Auto-check: a Check files run on every set with its auto-check on, once its last run is
older than the interval set in Settings -> Advanced.

The age comes from the set's latest run (check or scan) in the database, so a restart does
not reset it and a check or scan started by hand counts. A set that is hidden, busy (a scan,
an apply or a conversion) or not on disk is skipped and looked at again on the next poll.
"""

import logging
import sqlite3
import threading

from g1r import db, mounts, scanner
from g1r.jobs import Jobs
from g1r.library import FolderEntry, LibraryStore

log = logging.getLogger(__name__)


def _on_disk(settings, folder: FolderEntry) -> bool:
    try:
        return mounts.resolve(settings, folder.mount, folder.path).is_dir()
    except mounts.FolderPathError:
        return False


def due(conn: sqlite3.Connection, store: LibraryStore) -> list[str]:
    """Labels of the sets due an auto-check now."""
    library = store.load()
    age = f"-{store.auto_check_minutes(library)} minutes"
    labels = []
    for folder in library.folders:
        if not folder.auto_check or folder.hidden or not _on_disk(store.settings, folder):
            continue
        recent = conn.execute(
            "SELECT 1 FROM scan WHERE folder_label = ?"
            " AND started_at > strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ?)",
            (folder.label, age),
        ).fetchone()
        if recent is None:
            labels.append(folder.label)
    return labels


def run_due(conn: sqlite3.Connection, store: LibraryStore, jobs: Jobs) -> list[str]:
    """Start a check on every set due one; returns the labels started."""
    started = []
    for label in due(conn, store):
        try:
            jobs.scan(conn, label, kind=scanner.CHECK, auto=True)
        except scanner.ScanError:
            continue  # busy: the next poll tries again
        started.append(label)
    return started


class AutoCheck:
    """A daemon thread that looks for sets due a check every poll interval."""

    def __init__(self, store: LibraryStore, jobs: Jobs):
        self.store = store
        self.jobs = jobs
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self._loop, name="g1r-auto-check", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stopping.set()
        self.thread.join()

    def _loop(self) -> None:
        settings = self.store.settings
        poll = settings.jobs.auto_check.poll_seconds
        while not self.stopping.wait(poll):
            try:
                conn = db.connect(settings.paths.database_path, settings.database.busy_timeout_ms)
                try:
                    run_due(conn, self.store, self.jobs)
                finally:
                    conn.close()
            except Exception:  # a bad poll (library being edited, a locked database) waits
                log.exception("auto-check")
