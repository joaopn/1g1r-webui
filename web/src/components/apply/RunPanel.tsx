import { Archive, Square } from "lucide-react";
import { useEffect, useRef } from "react";
import { Button } from "@/components/ui/button";
import { useStopConversion, waitingText } from "@/lib/conversion";
import { formatCount, formatFiles, formatWhen } from "@/lib/format";
import { invalidateFolder, useRun } from "@/lib/queries";
import type { Meta } from "@/lib/types";
import { cn } from "@/lib/utils";

const SCOPE_VERBS: Record<string, string> = {
  convert: "Conversion",
  unmatched: "Unmatched files",
  empty: "Emptying discarded/",
  updates: "Older updates",
};

/** The folder's latest apply or restore: progress while it runs, its outcome after. With
 * `onMove`, a finished conversion offers to move the files it could not convert to
 * discarded/. */
export function RunPanel({
  label,
  meta,
  onMove,
}: {
  label: string;
  meta: Meta;
  onMove?: (relPaths: string[]) => void;
}) {
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
  const verb =
    run.scope === "rename"
      ? run.kind === "restore"
        ? "Giving names back"
        : "Rename"
      : run.kind === "restore"
        ? "Restore"
        : (SCOPE_VERBS[run.scope] ?? "Apply");
  const unconverted =
    !running && run.kind === "apply" && run.scope === "convert"
      ? run.failed.filter((f) => f.action === "convert").map((f) => f.rel_path)
      : [];
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
      {run.warnings.length > 0 ? (
        <>
          <ul className="mt-1 list-disc pl-5 text-status-warn">
            {run.warnings.map((w) => (
              <li key={w.rel_path}>
                {w.rel_path}: {w.warning}
              </li>
            ))}
          </ul>
          <p className="mt-1 text-muted-foreground">
            The CHD gives these tracks back with the zero bytes at their end. If that is not
            acceptable, restore the original from Discarded or remove the file.
          </p>
        </>
      ) : null}
      {onMove && unconverted.length > 0 ? (
        <Button
          size="sm"
          variant="outline"
          className="mt-2"
          title="Review, then move the files that could not be converted to discarded/ (can be restored)"
          onClick={() => onMove(unconverted)}
        >
          <Archive className="size-3.5" aria-hidden="true" />
          Move failed to discarded/ ({formatFiles(unconverted.length)})
        </Button>
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
