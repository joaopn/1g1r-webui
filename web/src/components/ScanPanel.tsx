import { ChevronRight, RefreshCw, ScanSearch } from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { Box } from "@/components/Box";
import { ProgressFill } from "@/components/ProgressFill";
import { Button } from "@/components/ui/button";
import { formatWhen } from "@/lib/format";
import { invalidateFolder } from "@/lib/queries";
import { runWords, scanProgress, useStartScan } from "@/lib/scan";
import type { Scan, TerminalLine } from "@/lib/types";

/**
 * A folder's run, in a titled box: `children` first, then how the last one went.
 *
 * `check` (Conversion page): no run button (Check files sits in the set's header); the status
 * line reports the last run of either kind. `identify` (Matching page): a Scan lists the folder
 * as Check files does, then identifies the files with nothing left to convert; a quick scan
 * reads only new and changed files, a full one every file.
 * `scan` is the latest run of either kind (one runs at a time); `lastScan` the latest Scan.
 * `quickOnly` (Updates & DLC) offers the quick scan alone: it picks up files added by hand.
 * Below the status line, the igir commands of the running Scan, else of the last one (until
 * the next Scan starts), each with what igir printed; the one igir is running now is marked.
 */
export function ScanPanel({
  label,
  kind,
  scan,
  lastScan,
  title,
  actions,
  blocked,
  quickOnly,
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
  quickOnly?: boolean;
  children: ReactNode;
}) {
  const start = useStartScan(label);
  const progress = scanProgress(scan);
  const running = scan?.status === "running";
  const busy = running || start.isPending;
  // A Scan waits for the conversion; Check files never does.
  const off = busy || (kind === "identify" && Boolean(blocked));
  // When a run ends, every table of the folder is stale.
  const wasRunning = useRef(running);
  useEffect(() => {
    if (wasRunning.current && !running) invalidateFolder(label);
    wasRunning.current = running;
  }, [running, label]);
  const spin = running ? "size-4 animate-spin" : "size-4";
  // Open until closed; stays closed for the next igir run while the page is open.
  const [commandOpen, setCommandOpen] = useState(true);
  const withCommands = kind === "identify" ? commandsOf(scan, lastScan ?? null) : null;
  const commands = withCommands?.commands ?? [];
  const current = withCommands?.status === "running" ? withCommands.command : null;
  const terminal = useRef<HTMLPreElement>(null);
  // Follows the bottom as igir draws, unless scrolled up to read.
  const following = useRef(true);
  useEffect(() => {
    const pre = terminal.current;
    if (pre && following.current) pre.scrollTop = pre.scrollHeight;
  });
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
          {kind === "check" ? null : lastScan ? (
            <>
              {quickOnly ? null : (
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
              )}
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
      {commands.length > 0 ? (
        <details
          className="group"
          open={commandOpen}
          onToggle={(e) => setCommandOpen(e.currentTarget.open)}
          data-testid="scan-command"
        >
          <summary className="flex cursor-pointer list-none items-center gap-1 text-muted-foreground">
            <ChevronRight
              className="size-4 shrink-0 transition-transform group-open:rotate-90"
              aria-hidden="true"
            />
            {current
              ? "igir is running"
              : withCommands?.status === "running"
                ? "igir commands of this scan"
                : "igir commands of the last scan"}
          </summary>
          <pre
            ref={terminal}
            onScroll={(e) => {
              const pre = e.currentTarget;
              following.current = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 1;
            }}
            className="mt-1 max-h-96 space-y-3 overflow-auto rounded-md bg-terminal px-3 py-2 font-mono text-terminal-foreground text-xs leading-relaxed"
          >
            {commands.map((run, index) => (
              // Each run writes its report to a new temporary folder: no two commands are alike.
              <div key={run.command}>
                <span className="select-none text-terminal-muted">$ </span>
                {run.command}
                {run.output.length > 0 ? <Screen lines={run.output} /> : null}
                {current && index === commands.length - 1 ? (
                  <div className="animate-pulse select-none text-terminal-muted">running…</div>
                ) : null}
              </div>
            ))}
          </pre>
        </details>
      ) : null}
    </Box>
  );
}

/** The Scan whose igir commands the panel shows: the running one, else the last finished. A
 * running Check files reads nothing with igir, so the last Scan's stay. */
function commandsOf(scan: Scan | null, lastScan: Scan | null): Scan | null {
  if (scan?.status === "running" && scan.kind === "identify") return scan;
  return lastScan;
}

/** Tailwind classes of igir's colour names (literal, so Tailwind sees them). */
const TERMINAL_STYLES: Record<string, string> = {
  red: "text-terminal-red",
  green: "text-terminal-green",
  yellow: "text-terminal-yellow",
  blue: "text-terminal-blue",
  magenta: "text-terminal-magenta",
  cyan: "text-terminal-cyan",
  gray: "text-terminal-gray",
  dark: "text-terminal-dark",
  faint: "opacity-60",
};

/** The screen igir drew: lines of [text, style] runs, a style being colour and/or "faint". */
function Screen({ lines }: { lines: TerminalLine[] }) {
  return (
    <div>
      {lines.map((line, row) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: rows of a screen, redrawn in place
        <div key={row} className="min-h-[1lh]">
          {line.map(([text, style], column) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: runs of one line, in order
            <span key={column} className={styleClasses(style)}>
              {text}
            </span>
          ))}
        </div>
      ))}
    </div>
  );
}

function styleClasses(style: string): string | undefined {
  if (!style) return undefined;
  return style
    .split(" ")
    .map((part) => TERMINAL_STYLES[part])
    .filter(Boolean)
    .join(" ");
}
