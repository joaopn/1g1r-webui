import { RefreshCw, ScanSearch } from "lucide-react";
import { type ReactNode, useEffect, useRef } from "react";
import { Box } from "@/components/Box";
import { Button } from "@/components/ui/button";
import { formatWhen } from "@/lib/format";
import { invalidateFolder } from "@/lib/queries";
import { scanProgress, useStartScan } from "@/lib/scan";
import type { Scan } from "@/lib/types";

/**
 * The folder's scan, in a titled box: `children` first, then the last scan's outcome.
 * A quick scan reads only new and changed files; a full scan reads every file again.
 */
export function ScanPanel({
  label,
  scan,
  title,
  actions,
  children,
}: {
  label: string;
  scan: Scan | null;
  title: string;
  /** More buttons, before the scan buttons. */
  actions?: ReactNode;
  children: ReactNode;
}) {
  const start = useStartScan(label);
  const progress = scanProgress(scan);
  const running = scan?.status === "running";
  const busy = running || start.isPending;
  // When a scan ends, every table of the folder is stale.
  const wasRunning = useRef(running);
  useEffect(() => {
    if (wasRunning.current && !running) invalidateFolder(label);
    wasRunning.current = running;
  }, [running, label]);
  return (
    <Box
      title={title}
      actions={
        <>
          {actions}
          {scan ? (
            <>
              <Button
                variant="outline"
                onClick={() => start.mutate({ full: true })}
                disabled={busy}
                title="Read every file again, ignoring what earlier scans read: for files changed in a way their size and date do not show"
              >
                <ScanSearch className="size-4" aria-hidden="true" />
                Full scan
              </Button>
              <Button
                onClick={() => start.mutate({})}
                disabled={busy}
                title="Read new and changed files; reuse what earlier scans read from the others"
              >
                <RefreshCw
                  className={running ? "size-4 animate-spin" : "size-4"}
                  aria-hidden="true"
                />
                Quick scan
              </Button>
            </>
          ) : (
            <Button onClick={() => start.mutate({})} disabled={busy}>
              <RefreshCw
                className={running ? "size-4 animate-spin" : "size-4"}
                aria-hidden="true"
              />
              Scan folder
            </Button>
          )}
        </>
      }
    >
      <div>{children}</div>
      <div className="text-muted-foreground">
        {!scan ? (
          "Not scanned yet."
        ) : progress ? (
          `Scanning since ${formatWhen(scan.started_at)}. ${progress.text}`
        ) : scan.status === "done" ? (
          `Last scan ${formatWhen(scan.finished_at)}: ${scan.message}.`
        ) : (
          <span className="text-status-bad">
            Last scan failed ({formatWhen(scan.finished_at)}): {scan.message}
          </span>
        )}
      </div>
    </Box>
  );
}
