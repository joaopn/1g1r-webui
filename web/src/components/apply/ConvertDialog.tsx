import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowRight, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { ApiError, api, json } from "@/lib/api";
import { formatBytes, formatFiles } from "@/lib/format";
import { invalidateFolder } from "@/lib/queries";
import type { ConvertPreview, Meta } from "@/lib/types";

/**
 * Review, then convert: the server's plan for the folder (or some files). Deleting originals
 * cannot be undone, so that plan also needs the folder label typed (the guard, design §8).
 */
export function ConvertDialog({
  label,
  relPaths,
  title,
  meta,
  open,
  onOpenChange,
}: {
  label: string;
  relPaths: string[] | null;
  title: string;
  meta: Meta;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const scope = relPaths === null ? {} : { rel_paths: relPaths };
  const [confirm, setConfirm] = useState("");
  const preview = useQuery({
    queryKey: ["convert-preview", label, relPaths],
    queryFn: () => api<ConvertPreview>(`/folders/${label}/convert/preview`, json("POST", scope)),
    enabled: open,
    gcTime: 0,
    staleTime: 0,
  });
  const convert = useMutation({
    mutationFn: (token: string) =>
      api(
        `/folders/${label}/convert`,
        json("POST", { ...scope, token, ...(confirm ? { confirm } : {}) }),
      ),
    onSuccess: () => {
      onOpenChange(false);
      return invalidateFolder(label);
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.message : String(err));
      preview.refetch();
    },
  });
  const plan = preview.data;
  const formatSize = (value: number) =>
    formatBytes(value, meta.ui.byte_unit_base, meta.ui.byte_units);
  const guarded = !!plan && plan.irreversible > 0;
  const blocked =
    !plan ||
    plan.conversions.length === 0 ||
    plan.problems.length > 0 ||
    !!plan.busy ||
    (guarded && confirm !== label);
  const originalsDir = `${meta.discarded_root}/${label}/originals/`;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            Each output is checked (CRC32 and size) before it counts.{" "}
            {guarded ? (
              "The originals are then deleted."
            ) : (
              <>
                The originals then move to <code className="text-xs">{originalsDir}</code>, and
                restoring one from the Discarded page undoes its conversion.
              </>
            )}
          </DialogDescription>
        </DialogHeader>
        {preview.isLoading ? (
          <p className="text-muted-foreground text-sm">Planning…</p>
        ) : preview.error ? (
          <p className="text-sm text-status-bad">{String(preview.error)}</p>
        ) : plan ? (
          <div className="min-w-0 space-y-3 text-sm">
            {plan.busy ? <p className="text-status-warn">Not now: {plan.busy}.</p> : null}
            {plan.problems.length > 0 ? (
              <div className="space-y-1 rounded-md border border-status-bad px-3 py-2">
                <p className="flex items-center gap-2 font-medium text-status-bad">
                  <TriangleAlert className="size-4" aria-hidden="true" />
                  Nothing will be converted. Scan the folder again, then review.
                </p>
                <ul className="list-disc pl-5 text-muted-foreground" data-testid="convert-problems">
                  {plan.problems.map((p) => (
                    <li key={`${p.rel_path}:${p.problem}`}>{p.problem}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            {plan.conversions.length === 0 ? (
              <p className="text-muted-foreground">There is nothing to convert.</p>
            ) : (
              <>
                <p>
                  <span className="font-medium">{formatFiles(plan.conversions.length)}</span>,{" "}
                  {formatSize(plan.bytes)}
                </p>
                <ul
                  className="max-h-72 space-y-1 overflow-y-auto rounded-md border border-border px-3 py-2"
                  data-testid="convert-list"
                >
                  {plan.conversions.map((c) => (
                    <li key={c.rel_path} className="flex min-w-0 items-center gap-2">
                      <span className="truncate">{c.rel_path}</span>
                      <ArrowRight className="size-3 shrink-0 text-primary" aria-hidden="true" />
                      <span className="truncate">{c.output}</span>
                      {c.original_to ? null : (
                        <span className="shrink-0 text-status-bad text-xs">original deleted</span>
                      )}
                      <span className="ml-auto shrink-0 text-muted-foreground tabular-nums">
                        {formatSize(c.size)}
                      </span>
                    </li>
                  ))}
                </ul>
              </>
            )}
            {guarded ? (
              <div
                className="space-y-2 rounded-md border border-status-bad px-3 py-2"
                data-testid="convert-guard"
              >
                <p className="flex items-center gap-2 font-medium text-status-bad">
                  <TriangleAlert className="size-4" aria-hidden="true" />
                  {formatFiles(plan.irreversible)} will be deleted for good. This cannot be undone.
                </p>
                <label htmlFor="convert-confirm" className="block text-muted-foreground">
                  Type the folder label <code className="text-xs">{label}</code> to confirm
                </label>
                <Input
                  id="convert-confirm"
                  aria-label="Folder label"
                  value={confirm}
                  autoComplete="off"
                  onChange={(event) => setConfirm(event.target.value)}
                />
              </div>
            ) : null}
          </div>
        ) : null}
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant={guarded ? "destructive" : "default"}
            disabled={blocked || convert.isPending}
            onClick={() => plan && convert.mutate(plan.token)}
          >
            Convert {plan ? formatFiles(plan.conversions.length) : "files"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
