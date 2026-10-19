"""Background work: folder scans and apply runs, in a small thread pool.

Each job opens its own connection. Starting a job goes through one lock, so a scan and an
apply can never both start on a folder.
"""

import threading
from concurrent.futures import ThreadPoolExecutor

from g1r import db, journal
from g1r.config import Settings
from g1r.converter import Converter
from g1r.scanner import Scanner


class Jobs:
    def __init__(self, settings: Settings, scanner: Scanner, converter: Converter | None = None):
        self.settings = settings
        self.scanner = scanner
        self.converter = converter or Converter(settings)
        self.pool = ThreadPoolExecutor(
            max_workers=settings.jobs.workers, thread_name_prefix="g1r-job"
        )
        self.starting = threading.Lock()

    def _connect(self):
        return db.connect(self.settings.paths.database_path, self.settings.database.busy_timeout_ms)

    def scan(self, conn, label: str, refresh_lookups: bool = False, full: bool = False) -> int:
        with self.starting:
            scan_id = self.scanner.start(conn, label)
        self.pool.submit(self._run_scan, scan_id, label, refresh_lookups, full)
        return scan_id

    def _run_scan(self, scan_id: int, label: str, refresh_lookups: bool, full: bool) -> None:
        conn = self._connect()
        try:
            self.scanner.run(conn, scan_id, label, refresh_lookups, full)
        finally:
            conn.close()

    def apply(self, conn, label: str, kind: str, scope: str, check, after=None) -> int:
        """Start a run. `check()` re-plans under the lock and returns the plan or raises;
        `after()`, if given, runs once the run has ended, however it ended."""
        with self.starting:
            reason = journal.busy(conn, label)
            if reason:
                raise journal.PlanError(reason)
            plan = check()
            run_id = journal.start_run(conn, label, kind, scope, len(plan))
        self.pool.submit(self._run_apply, run_id, label, plan, after)
        return run_id

    def _run_apply(self, run_id: int, label: str, plan, after=None) -> None:
        conn = self._connect()
        try:
            journal.run(self.settings.apply, conn, run_id, label, plan, self.converter)
        finally:
            conn.close()
            if after is not None:
                after()

    def shutdown(self) -> None:
        self.pool.shutdown(wait=True, cancel_futures=True)
