"""Background work: folder scans run in a small thread pool, each with its own connection."""

from concurrent.futures import ThreadPoolExecutor

from g1r import db
from g1r.config import Settings
from g1r.scanner import Scanner


class Jobs:
    def __init__(self, settings: Settings, scanner: Scanner):
        self.settings = settings
        self.scanner = scanner
        self.pool = ThreadPoolExecutor(
            max_workers=settings.jobs.workers, thread_name_prefix="g1r-job"
        )

    def scan(self, conn, label: str) -> int:
        scan_id = self.scanner.start(conn, label)
        self.pool.submit(self._run_scan, scan_id, label)
        return scan_id

    def _run_scan(self, scan_id: int, label: str) -> None:
        conn = db.connect(self.settings.paths.database_path, self.settings.database.busy_timeout_ms)
        try:
            self.scanner.run(conn, scan_id, label)
        finally:
            conn.close()

    def shutdown(self) -> None:
        self.pool.shutdown(wait=True, cancel_futures=True)
