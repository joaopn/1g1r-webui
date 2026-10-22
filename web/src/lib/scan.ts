import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { ApiError, api } from "@/lib/api";
import { formatCount } from "@/lib/format";
import { invalidateFolder } from "@/lib/queries";
import type { Scan } from "@/lib/types";

/** Starts the folder's Scan: the check, then the identification of the files with nothing
 * left to convert. A quick scan reuses what earlier scans read from unchanged files; `full`
 * reads every file again. */
export function useStartScan(label: string) {
  return useMutation({
    mutationFn: ({ full = false }: { full?: boolean } = {}) =>
      api(`/folders/${label}/scan${full ? "?full=true" : ""}`, { method: "POST" }),
    onSuccess: () => invalidateFolder(label),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : String(err)),
  });
}

/** Starts Check files: the listing and what conversion needs, nothing hashed. */
export function useStartCheck(label: string) {
  return useMutation({
    mutationFn: () => api(`/folders/${label}/check`, { method: "POST" }),
    onSuccess: () => invalidateFolder(label),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : String(err)),
  });
}

/** How a run is named in a sentence: "check" or "scan", and its past form. */
export function runWords(scan: Scan): { noun: string; past: string; ing: string } {
  return scan.kind === "check"
    ? { noun: "check", past: "Checked", ing: "Checking" }
    : { noun: "scan", past: "Scanned", ing: "Scanning" };
}

/** How far a running scan is: the part of its step done (null when the step has no file
 * count), and a line saying so. Null when no scan is running. */
export function scanProgress(scan: Scan | null): { fraction: number | null; text: string } | null {
  if (scan?.status !== "running") return null;
  if (!scan.stage) return { fraction: null, text: "Waiting to start…" };
  if (scan.files_total === null || scan.files_done === null) {
    return { fraction: null, text: `${scan.stage}…` };
  }
  const fraction = scan.files_total > 0 ? scan.files_done / scan.files_total : 1;
  return {
    fraction,
    text: `${scan.stage}: ${formatCount(scan.files_done)} / ${formatCount(scan.files_total)} files`,
  };
}
