import { Square } from "lucide-react";
import { useEffect, useRef } from "react";
import { Button } from "@/components/ui/button";
import { useStopConversion, waitingText } from "@/lib/conversion";
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
  const stop = useStopConversion(label);
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
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <p>
            {waitingText(run.waiting_for) ?? (
              <>
                {verb} {run.stopping ? "stopping" : "running"}: {formatCount(run.done)} of{" "}
                {formatCount(run.total)} steps…
              </>
            )}
          </p>
          {run.kind === "apply" && run.scope === "convert" ? (
            <StopButton
              label={label}
              stopping={run.stopping || stop.isPending}
              onStop={() => stop.mutate()}
            />
          ) : null}
        </div>
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

/** Stops a running conversion: what is converted stays, the files under way are left as they
 * were. */
export function StopButton({
  label,
  stopping,
  onStop,
}: {
  label: string;
  stopping: boolean;
  onStop: () => void;
}) {
  return (
    <Button
      size="sm"
      variant="outline"
      aria-label={`Stop the conversion of ${label}`}
      title="Files already converted stay converted; the ones being converted are left as they were"
      disabled={stopping}
      onClick={onStop}
    >
      <Square className="size-3.5" aria-hidden="true" />
      {stopping ? "Stopping…" : "Stop"}
    </Button>
  );
}
