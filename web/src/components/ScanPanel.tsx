import { RefreshCw } from "lucide-react";
import { type ReactNode, useEffect, useRef } from "react";
import { Button } from "@/components/ui/button";
import { formatWhen } from "@/lib/format";
import { invalidateFolder } from "@/lib/queries";
import { scanProgress, useStartScan } from "@/lib/scan";
import type { Scan } from "@/lib/types";

/** The folder's last scan, with the button that starts a new one; `children` goes above. */
export function ScanPanel({
  label,
  scan,
  children,
}: {
  label: string;
  scan: Scan | null;
  children: ReactNode;
}) {
  const start = useStartScan(label);
  const progress = scanProgress(scan);
  const running = scan?.status === "running";
  // When a scan ends, every table of the folder is stale.
  const wasRunning = useRef(running);
  useEffect(() => {
    if (wasRunning.current && !running) invalidateFolder(label);
    wasRunning.current = running;
  }, [running, label]);
  return (
    <section className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-card px-4 py-3">
      <div className="space-y-1 text-sm">
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
      </div>
      <Button onClick={() => start.mutate()} disabled={running || start.isPending}>
        <RefreshCw className={running ? "size-4 animate-spin" : "size-4"} aria-hidden="true" />
        {scan ? "Scan again" : "Scan folder"}
      </Button>
    </section>
  );
}
