"""Background work: folder scans and apply runs, each in its own small thread pool.

Scans of different folders run side by side, as many as the library's limit allows (read
again whenever a scan waits, so a new limit applies at once); queued scans start in order.
Applies run apart from them, so an apply never waits behind a long scan. Each job opens its
own connection. Starting a job goes through one lock, so a scan and an apply can never both
start on a folder.
"""

import threading
from collections import deque
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
        # Threads for the most scans the limit can allow; the gate holds the rest back.
        self.scans = ThreadPoolExecutor(
            max_workers=settings.jobs.max_scan_workers, thread_name_prefix="g1r-scan"
        )
        self.gate = threading.Condition()
        self.queued: deque[int] = deque()
        self.running = 0
        self.applies = ThreadPoolExecutor(
            max_workers=settings.jobs.apply_workers, thread_name_prefix="g1r-apply"
        )
        self.starting = threading.Lock()

    def _connect(self):
        return db.connect(self.settings.paths.database_path, self.settings.database.busy_timeout_ms)

    def scan(self, conn, label: str, refresh_lookups: bool = False, full: bool = False) -> int:
        # Queued and submitted in one order, so the scan first in line always has a thread.
        with self.starting:
            scan_id = self.scanner.start(conn, label)
            with self.gate:
                self.queued.append(scan_id)
            self.scans.submit(self._run_scan, scan_id, label, refresh_lookups, full)
        return scan_id

    def scan_limit(self) -> int:
        store = self.scanner.store
        return store.parallel_scans(store.load())

    def limit_changed(self) -> None:
        """Let queued scans check the limit again."""
        with self.gate:
            self.gate.notify_all()

    def _run_scan(self, scan_id: int, label: str, refresh_lookups: bool, full: bool) -> None:
        with self.gate:
            self.gate.wait_for(
                lambda: self.queued[0] == scan_id and self.running < self.scan_limit()
            )
            self.queued.popleft()
            self.running += 1
            self.gate.notify_all()
        conn = self._connect()
        try:
            self.scanner.run(conn, scan_id, label, refresh_lookups, full)
        finally:
            conn.close()
            with self.gate:
                self.running -= 1
                self.gate.notify_all()

    def apply(self, conn, label: str, kind: str, scope: str, check, after=None) -> int:
        """Start a run. `check()` re-plans under the lock and returns the plan or raises;
        `after()`, if given, runs once the run has ended, however it ended."""
        with self.starting:
            reason = journal.busy(conn, label)
            if reason:
                raise journal.PlanError(reason)
            plan = check()
            run_id = journal.start_run(conn, label, kind, scope, len(plan))
        self.applies.submit(self._run_apply, run_id, label, plan, after)
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
        for pool in (self.scans, self.applies):
            pool.shutdown(wait=True, cancel_futures=True)
