import { useEffect, useRef } from "react";
import { formatCount, formatWhen } from "@/lib/format";
import { invalidateFolder, useRun } from "@/lib/queries";
import type { Meta } from "@/lib/types";
import { cn } from "@/lib/utils";

const SCOPE_VERBS: Record<string, string> = {
  convert: "Conversion",
  unmatched: "Unmatched files",
  empty: "Emptying discarded/",
};

/** The folder's latest apply or restore: progress while it runs, its outcome after. */
export function RunPanel({ label, meta }: { label: string; meta: Meta }) {
  const run = useRun(label, meta.ui.poll_interval_ms).data;
  const running = run?.status === "running";
  // When a run ends, every table of the folder is stale.
  const wasRunning = useRef(running);
  useEffect(() => {
    if (wasRunning.current && !running) invalidateFolder(label);
    wasRunning.current = running;
  }, [running, label]);
  if (!run) return null;
  const verb = run.kind === "restore" ? "Restore" : (SCOPE_VERBS[run.scope] ?? "Apply");
  return (
    <section
      data-testid="run-panel"
      className={cn(
        "rounded-lg border bg-card px-4 py-3 text-sm",
        run.status === "failed" ? "border-status-bad" : "border-border",
      )}
    >
      {running ? (
        <p>
          {verb} running: {formatCount(run.done)} of {formatCount(run.total)} steps…
        </p>
      ) : (
        <p className={run.status === "failed" ? "text-status-bad" : "text-muted-foreground"}>
          Last {verb.toLowerCase()} {formatWhen(run.finished_at)}: {run.message}.
        </p>
      )}
      {run.failed.length > 0 ? (
        <ul className="mt-1 list-disc pl-5 text-status-bad">
          {run.failed.map((f) => (
            <li key={f.rel_path}>
              {f.rel_path}: {f.error}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
