import { useMutation } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import type { ReactNode } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { ApiError, api } from "@/lib/api";
import { formatWhen } from "@/lib/format";
import { invalidateFolder } from "@/lib/queries";
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
  const start = useMutation({
    mutationFn: () => api(`/folders/${label}/scan`, { method: "POST" }),
    onSuccess: () => invalidateFolder(label),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : String(err)),
  });
  const running = scan?.status === "running";
  return (
    <section className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-card px-4 py-3">
      <div className="space-y-1 text-sm">
        <div>{children}</div>
        <div className="text-muted-foreground">
          {!scan ? (
            "Not scanned yet."
          ) : running ? (
            `Scanning since ${formatWhen(scan.started_at)}…`
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
