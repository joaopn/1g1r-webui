import { FileSearch, RefreshCw, ScanSearch } from "lucide-react";
import { type ReactNode, useEffect, useRef } from "react";
import { Box } from "@/components/Box";
import { ProgressFill } from "@/components/ProgressFill";
import { Button } from "@/components/ui/button";
import { formatWhen } from "@/lib/format";
import { invalidateFolder } from "@/lib/queries";
import { runWords, scanProgress, useStartCheck, useStartScan } from "@/lib/scan";
import type { Scan } from "@/lib/types";

/**
 * A folder's run, in a titled box: `children` first, then how the last one went.
 *
 * `check` (Conversion page): Check files lists the folder and reads what conversion needs,
 * hashing nothing. `identify` (Matching page): a Scan does that, then identifies the files with
 * nothing left to convert; a quick scan reads only new and changed files, a full one every file.
 * `scan` is the latest run of either kind (one runs at a time); `lastScan` the latest Scan.
 */
export function ScanPanel({
  label,
  kind,
  scan,
  lastScan,
  title,
  actions,
  blocked,
  children,
}: {
  label: string;
  kind: "check" | "identify";
  scan: Scan | null;
  lastScan?: Scan | null;
  title: string;
  /** More buttons, before the run buttons. */
  actions?: ReactNode;
  /** Why a Scan cannot run now (files not converted yet): its buttons are off and say so. */
  blocked?: string;
  children: ReactNode;
}) {
  const start = useStartScan(label);
  const check = useStartCheck(label);
  const progress = scanProgress(scan);
  const running = scan?.status === "running";
  const busy = running || start.isPending || check.isPending;
  // A Scan waits for the conversion; Check files never does.
  const off = busy || (kind === "identify" && Boolean(blocked));
  // When a run ends, every table of the folder is stale.
  const wasRunning = useRef(running);
  useEffect(() => {
    if (wasRunning.current && !running) invalidateFolder(label);
    wasRunning.current = running;
  }, [running, label]);
  const spin = running ? "size-4 animate-spin" : "size-4";
  // What the status line reports: a Scan on the Matching page; on the Conversion page, the
  // last run of either kind (both read the folder).
  const shown = kind === "check" ? scan : (lastScan ?? null);
  return (
    <Box
      title={title}
      background={
        running && progress ? (
          <ProgressFill
            fraction={progress.fraction}
            testId="scan-progress"
            className="bg-primary/10"
          />
        ) : null
      }
      actions={
        <>
          {actions}
          {kind === "check" ? (
            <Button
              onClick={() => check.mutate()}
              disabled={busy}
              title="List the folder and read what conversion needs (archive listings, headers); nothing is hashed"
            >
              <FileSearch className={spin} aria-hidden="true" />
              Check files
            </Button>
          ) : lastScan ? (
            <>
              <Button
                variant="outline"
                onClick={() => start.mutate({ full: true })}
                disabled={off}
                title={
                  blocked ??
                  "Read every file again, ignoring what earlier scans read: for files changed in a way their size and date do not show"
                }
              >
                <ScanSearch className="size-4" aria-hidden="true" />
                Full scan
              </Button>
              <Button
                onClick={() => start.mutate({})}
                disabled={off}
                title={
                  blocked ??
                  "Read new and changed files; reuse what earlier scans read from the others"
                }
              >
                <RefreshCw className={spin} aria-hidden="true" />
                Quick scan
              </Button>
            </>
          ) : (
            <Button onClick={() => start.mutate({})} disabled={off} title={blocked}>
              <RefreshCw className={spin} aria-hidden="true" />
              Scan folder
            </Button>
          )}
        </>
      }
    >
      <div>{children}</div>
      <div className="text-muted-foreground">
        {scan && progress ? (
          `${runWords(scan).ing} since ${formatWhen(scan.started_at)}. ${progress.text}`
        ) : !shown ? (
          kind === "check" ? (
            "Not checked yet."
          ) : (
            "Not scanned yet."
          )
        ) : shown.status === "done" ? (
          kind === "check" ? (
            `${runWords(shown).past} ${formatWhen(shown.finished_at)}${
              shown.kind === "check" ? `: ${shown.message}` : ""
            }.`
          ) : (
            `Last scan ${formatWhen(shown.finished_at)}: ${shown.message}.`
          )
        ) : (
          <span className="text-status-bad">
            Last {runWords(shown).noun} failed ({formatWhen(shown.finished_at)}): {shown.message}
          </span>
        )}
      </div>
    </Box>
  );
}
