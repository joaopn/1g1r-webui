"""Background work: folder scans and apply runs, each in its own small thread pool.

Scans of different folders run side by side, as many as the library's limit allows (read
again whenever a scan waits, so a new limit applies at once); queued scans start in order.
Runs that change files run apart from them, so none waits behind a long scan. Conversion runs
go one at a time across folders (each one's free-space check holds while it runs); a
conversion run converts several files at a time, as many as the library's limit allows when it
starts. Every other run starts at once, one per folder. Each job opens its own connection.
Starting a job goes through one lock, so a scan and a run can never both start on a folder.
"""

import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor

from g1r import db, journal
from g1r.config import Settings
from g1r.converter import Converter
from g1r.scanner import IDENTIFY, Scanner


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
        self.conversions = ThreadPoolExecutor(
            max_workers=settings.jobs.conversion_runs, thread_name_prefix="g1r-convert"
        )
        self.applies = ThreadPoolExecutor(
            max_workers=settings.jobs.other_runs, thread_name_prefix="g1r-apply"
        )
        self.starting = threading.Lock()
        # The stop event of each apply run under way, by run id.
        self.stops: dict[int, threading.Event] = {}

    def _connect(self):
        return db.connect(self.settings.paths.database_path, self.settings.database.busy_timeout_ms)

    def scan(
        self,
        conn,
        label: str,
        rematch: bool = False,
        full: bool = False,
        kind: str = IDENTIFY,
        auto: bool = False,
    ) -> int:
        """A Scan, or with kind CHECK a Check files run; both wait in the same queue. `auto`:
        started by the app on its own (auto-check)."""
        # Queued and submitted in one order, so the scan first in line always has a thread.
        with self.starting:
            scan_id = self.scanner.start(conn, label, kind, auto)
            with self.gate:
                self.queued.append(scan_id)
            self.scans.submit(self._run_scan, scan_id, label, rematch, full, kind)
        return scan_id

    def scan_limit(self) -> int:
        store = self.scanner.store
        return store.parallel_scans(store.load())

    def limit_changed(self) -> None:
        """Let queued scans check the limit again."""
        with self.gate:
            self.gate.notify_all()

    def _run_scan(self, scan_id: int, label: str, rematch: bool, full: bool, kind: str) -> None:
        with self.gate:
            self.gate.wait_for(
                lambda: self.queued[0] == scan_id and self.running < self.scan_limit()
            )
            self.queued.popleft()
            self.running += 1
            self.gate.notify_all()
        conn = self._connect()
        try:
            self.scanner.run(conn, scan_id, label, rematch, full, kind)
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
            store = self.scanner.store
            workers = store.parallel_conversions(store.load())
            run_id = journal.start_run(conn, label, kind, scope, journal.files_in(plan))
            self.stops[run_id] = threading.Event()
        pool = self.conversions if journal.is_conversion(kind, scope) else self.applies
        pool.submit(self._run_apply, run_id, label, plan, workers, after)
        return run_id

    def _run_apply(self, run_id: int, label: str, plan, workers: int, after=None) -> None:
        conn = self._connect()
        stop = self.stops[run_id]
        try:
            journal.begin_run(conn, run_id)
            journal.run(
                self.settings.apply, conn, run_id, label, plan, self.converter, workers, stop
            )
        finally:
            conn.close()
            with self.starting:
                del self.stops[run_id]
            if after is not None:
                after()

    def stop_conversion(self, conn, label: str) -> bool:
        """Stop the folder's running conversion: no file starts, the ones under way are cut
        off. False when no conversion runs."""
        with self.starting:
            run_id = journal.ask_stop(conn, label)
            if run_id is None or run_id not in self.stops:
                return False
            self.stops[run_id].set()
        return True

    def shutdown(self) -> None:
        for pool in (self.scans, self.conversions, self.applies):
            pool.shutdown(wait=True, cancel_futures=True)
