import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowRight, TriangleAlert } from "lucide-react";
import { type ReactNode, useState } from "react";
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
import { invalidateFolder, queryClient } from "@/lib/queries";
import type { GuardedPreview, Meta } from "@/lib/types";

/**
 * Review, then run a plan the server made from `body` (`<path>/preview`, then `<path>`). A
 * plan that deletes anything also needs the folder label typed (the guard), or the words the
 * plan asks for (`GuardedPreview.confirm`).
 */
export function GuardedDialog({
  label,
  path,
  every = false,
  body,
  title,
  description,
  action,
  meta,
  open,
  onOpenChange,
  renames = false,
  note,
}: {
  label: string;
  /** Relative to the folder: `unmatched`, `discarded/empty`; with `every`, to the API. */
  path: string;
  /** The plan spans every set (`label` only names it): `path` is not under a folder. */
  every?: boolean;
  body: Record<string, unknown>;
  title: string;
  description: ReactNode;
  /** The run button's text for this many files. */
  action: (files: number) => string;
  meta: Meta;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The files get new names in their folder: each shows its new name, not "discarded". */
  renames?: boolean;
  /** Said under the plan's size, once planned. */
  note?: ReactNode;
}) {
  const [confirm, setConfirm] = useState("");
  const base = every ? `/${path}` : `/folders/${label}/${path}`;
  const preview = useQuery({
    queryKey: ["guarded-preview", label, path, body],
    queryFn: () => api<GuardedPreview>(`${base}/preview`, json("POST", body)),
    enabled: open,
    gcTime: 0,
    staleTime: 0,
  });
  const run = useMutation({
    mutationFn: (token: string) =>
      api(base, json("POST", { ...body, token, ...(confirm ? { confirm } : {}) })),
    onSuccess: () => {
      onOpenChange(false);
      return every ? queryClient.invalidateQueries() : invalidateFolder(label);
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
  const word = plan?.confirm ?? label;
  const blocked =
    !plan ||
    plan.files.length === 0 ||
    plan.problems.length > 0 ||
    !!plan.busy ||
    (guarded && confirm !== word);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
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
                  Nothing will change: some files are not as listed. Look again, then review.
                </p>
                <ul className="list-disc pl-5 text-muted-foreground" data-testid="guarded-problems">
                  {plan.problems.map((p) => (
                    <li key={`${p.rel_path}:${p.problem}`}>{p.problem}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            {plan.skipped?.length ? (
              <div className="space-y-1 text-muted-foreground" data-testid="guarded-skipped">
                <p>Left alone, their folder cannot be found:</p>
                <ul className="list-disc pl-5">
                  {plan.skipped.map((s) => (
                    <li key={s.label}>
                      {s.label}: {s.reason}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            {plan.files.length === 0 ? (
              <p className="text-muted-foreground">There is nothing to do.</p>
            ) : (
              <>
                <p>
                  <span className="font-medium">{formatFiles(plan.files.length)}</span>,{" "}
                  {formatSize(plan.bytes)}
                </p>
                {note ? <p className="text-muted-foreground">{note}</p> : null}
                <ul
                  className="max-h-72 space-y-1 overflow-y-auto rounded-md border border-border px-3 py-2"
                  data-testid="guarded-files"
                >
                  {plan.files.map((f) => (
                    <li key={f.rel_path} className="flex min-w-0 items-center gap-2">
                      <span className="truncate">{f.rel_path}</span>
                      {f.destination && renames ? (
                        <>
                          <ArrowRight
                            className="size-3 shrink-0 text-status-info"
                            aria-hidden="true"
                          />
                          <span className="truncate" title={f.destination}>
                            {f.destination.split("/").pop()}
                          </span>
                        </>
                      ) : f.destination ? (
                        <>
                          <ArrowRight
                            className="size-3 shrink-0 text-status-warn"
                            aria-hidden="true"
                          />
                          <span className="shrink-0 text-muted-foreground" title={f.destination}>
                            discarded
                          </span>
                        </>
                      ) : (
                        <span className="shrink-0 text-status-bad text-xs">deleted</span>
                      )}
                      <span className="ml-auto shrink-0 text-muted-foreground tabular-nums">
                        {formatSize(f.size)}
                      </span>
                    </li>
                  ))}
                </ul>
              </>
            )}
            {guarded ? (
              <div
                className="space-y-2 rounded-md border border-status-bad px-3 py-2"
                data-testid="guarded-confirm"
              >
                <p className="flex items-center gap-2 font-medium text-status-bad">
                  <TriangleAlert className="size-4" aria-hidden="true" />
                  {formatFiles(plan.irreversible)} will be deleted for good. This cannot be undone.
                </p>
                <label htmlFor="guarded-label" className="block text-muted-foreground">
                  Type {plan.confirm ? "" : "the folder label "}
                  <code className="text-xs">{word}</code> to confirm
                </label>
                <Input
                  id="guarded-label"
                  aria-label={plan.confirm ? "Confirmation" : "Folder label"}
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
            disabled={blocked || run.isPending}
            onClick={() => plan && run.mutate(plan.token)}
          >
            {action(plan?.files.length ?? 0)}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
