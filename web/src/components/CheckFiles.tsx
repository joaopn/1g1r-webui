import { CircleCheck, FileSearch } from "lucide-react";
import { type ComponentProps, useEffect, useRef } from "react";
import { Button } from "@/components/ui/button";
import { formatWhen } from "@/lib/format";
import { invalidateFolder } from "@/lib/queries";
import { useStartCheck } from "@/lib/scan";
import type { Scan } from "@/lib/types";

/** The last run was a check that found no ROM file new, changed or gone. */
export const foundNothing = (scan: Scan | null | undefined) =>
  scan?.kind === "check" && scan.status === "done" && scan.changes === 0;

/**
 * Check files: looks at the folder for new, changed and removed files (listing and what
 * conversion needs, nothing hashed). `scan` is the set's latest run; when it was a check that
 * found nothing, "Nothing new" follows the button. `blocked` says why it cannot run now.
 */
export function CheckFiles({
  label,
  scan,
  blocked,
  size,
  variant = "outline",
  ...rest
}: {
  label: string;
  scan: Scan | null | undefined;
  blocked?: string;
  size?: ComponentProps<typeof Button>["size"];
  variant?: ComponentProps<typeof Button>["variant"];
} & Omit<ComponentProps<typeof Button>, "onClick" | "disabled" | "size" | "variant">) {
  const check = useStartCheck(label);
  const running = scan?.status === "running";
  // When a run ends, every table of the folder is stale.
  const wasRunning = useRef(running);
  useEffect(() => {
    if (wasRunning.current && !running) invalidateFolder(label);
    wasRunning.current = running;
  }, [running, label]);
  const checking = running && scan?.kind === "check";
  return (
    <span className="inline-flex items-center gap-2">
      <Button
        size={size}
        variant={variant}
        aria-label={`Check files of ${label}`}
        title={
          blocked ??
          (running
            ? `${checking ? "Checking" : "Scanning"} the folder`
            : "Look for new, changed and removed files; nothing is hashed")
        }
        disabled={Boolean(blocked) || running || check.isPending}
        onClick={() => check.mutate()}
        {...rest}
      >
        <FileSearch className={checking ? "size-4 animate-spin" : "size-4"} aria-hidden="true" />
        Check files
      </Button>
      {scan && foundNothing(scan) ? (
        <span
          className="inline-flex items-center gap-1 text-muted-foreground text-xs"
          title={`Checked ${formatWhen(scan.finished_at)}: no ROM file new, changed or removed`}
          data-testid={`nothing-new-${label}`}
        >
          <CircleCheck className="size-3.5 text-status-good" aria-hidden="true" />
          Nothing new
        </span>
      ) : null}
    </span>
  );
}
