import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowRight, TriangleAlert } from "lucide-react";
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
import { ApiError, api, json } from "@/lib/api";
import { formatBytes, formatFiles } from "@/lib/format";
import { invalidateFolder } from "@/lib/queries";
import type { ApplyPreview, Meta } from "@/lib/types";

/**
 * Review, then apply: the server's own plan for the folder (or one game), with every move
 * listed. Applying sends the plan's token back, so nothing runs unless it is the plan shown.
 */
export function ApplyDialog({
  label,
  groupKey,
  title,
  meta,
  open,
  onOpenChange,
}: {
  label: string;
  groupKey: string | null;
  title: string;
  meta: Meta;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const scope = groupKey === null ? {} : { group_key: groupKey };
  const preview = useQuery({
    queryKey: ["apply-preview", label, groupKey],
    queryFn: () => api<ApplyPreview>(`/folders/${label}/apply/preview`, json("POST", scope)),
    enabled: open,
    gcTime: 0,
    staleTime: 0,
  });
  const apply = useMutation({
    mutationFn: (token: string) =>
      api(`/folders/${label}/apply`, json("POST", { ...scope, token })),
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
  const blocked = !plan || plan.moves.length === 0 || plan.problems.length > 0 || !!plan.busy;
  const discardedDir = `${meta.discarded_root}/${label}/`;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            These files move to <code className="text-xs">{discardedDir}1g1r/</code>. Nothing is
            deleted, and each move can be restored from the table or the Discarded page.
          </DialogDescription>
        </DialogHeader>
        {preview.isLoading ? (
          <p className="text-muted-foreground text-sm">Planning…</p>
        ) : preview.error ? (
          <p className="text-sm text-status-bad">{String(preview.error)}</p>
        ) : plan ? (
          <div className="space-y-3 text-sm">
            {plan.busy ? <p className="text-status-warn">Not now: {plan.busy}.</p> : null}
            {plan.problems.length > 0 ? (
              <div className="space-y-1 rounded-md border border-status-bad px-3 py-2">
                <p className="flex items-center gap-2 font-medium text-status-bad">
                  <TriangleAlert className="size-4" aria-hidden="true" />
                  Nothing will move: {formatFiles(plan.problems.length)} are not as the last scan
                  saw them. Scan the folder again, then review.
                </p>
                <ul className="list-disc pl-5 text-muted-foreground" data-testid="apply-problems">
                  {plan.problems.map((p) => (
                    <li key={`${p.rel_path}:${p.problem}`}>{p.problem}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            {plan.moves.length === 0 ? (
              <p className="text-muted-foreground">There is nothing to apply.</p>
            ) : (
              <>
                <p>
                  <span className="font-medium">{formatFiles(plan.moves.length)}</span>,{" "}
                  {formatSize(plan.bytes)}
                </p>
                <ul
                  className="max-h-72 space-y-1 overflow-y-auto rounded-md border border-border px-3 py-2"
                  data-testid="apply-moves"
                >
                  {plan.moves.map((m) => (
                    <li key={m.rel_path} className="flex min-w-0 items-center gap-2">
                      <span className="truncate" title={m.source}>
                        {m.rel_path}
                      </span>
                      <ArrowRight className="size-3 shrink-0 text-status-warn" aria-hidden="true" />
                      <span className="shrink-0 text-muted-foreground" title={m.destination}>
                        discarded
                      </span>
                      <span className="ml-auto shrink-0 text-muted-foreground tabular-nums">
                        {formatSize(m.size)}
                      </span>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        ) : null}
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            disabled={blocked || apply.isPending}
            onClick={() => plan && apply.mutate(plan.token)}
          >
            Move {plan ? formatFiles(plan.moves.length) : "files"} to discarded/
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
