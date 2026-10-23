import { useMutation } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { GuardedDialog } from "@/components/apply/GuardedDialog";
import { RunPanel } from "@/components/apply/RunPanel";
import { useRestore } from "@/components/apply/useRestore";
import { DiscardedTable } from "@/components/discarded/DiscardedTable";
import { StatCard } from "@/components/StatCard";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { formatBytes, formatCount, formatFiles } from "@/lib/format";
import { keys, queryClient, useDiscarded, useFolder, useFolderCard, useMeta } from "@/lib/queries";
import { FolderHeader } from "@/pages/FolderHeader";

/** Discarded: what is in discarded/<label>/, by reason, with Restore for the app's own moves. */
export function FolderDiscardedPage() {
  const { label = "" } = useParams();
  const card = useFolderCard(label);
  const meta = useMeta();
  const folder = useFolder(label, false);
  const discarded = useDiscarded(label);
  const navigate = useNavigate();
  const restore = useRestore(label);
  const [emptying, setEmptying] = useState(false);
  const remove = useMutation({
    mutationFn: () => api(`/folders/${label}`, { method: "DELETE" }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: keys.folders });
      toast.success(`Removed ${label} from the app; its files are untouched`);
      navigate("/");
    },
  });
  if (!meta.data || !folder.data) return <p className="text-muted-foreground">Loading…</p>;
  const f = folder.data;
  const ui = meta.data.ui;
  const data = discarded.data;
  return (
    <div className="space-y-6">
      <FolderHeader folder={f} meta={meta.data} section="discarded" card={card} />
      <section className="space-y-1 rounded-lg border border-border bg-card px-4 py-3 text-sm">
        <p>
          Discarded files go to <code className="text-xs">{f.discarded_to}</code>, under the reason
          they were moved for, with the folder's own structure.
          {!f.on_main_mount ? (
            <span className="text-status-warn">
              {" "}
              This folder is on another disk: moves will be copy, verify, then remove.
            </span>
          ) : null}
        </p>
        <p className="text-muted-foreground">
          Restore moves a file back to its old place, if that place is still free and the file is as
          the app left it. Emptying deletes everything in this folder's discarded/ for good, and its
          discarded versions leave the 1G1R table.
        </p>
      </section>
      <RunPanel label={label} meta={meta.data} />
      {data ? (
        data.files === 0 ? (
          <p className="text-muted-foreground">Nothing has been discarded from this folder.</p>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <StatCard value={formatCount(data.files)} label="files" />
              <StatCard
                value={formatBytes(data.bytes, ui.byte_unit_base, ui.byte_units)}
                label="disk space used"
              />
            </div>
            <ul className="space-y-0.5 text-sm">
              {data.reasons.map((r) => (
                <li key={r.id}>
                  <span className="font-medium">{r.label}</span>{" "}
                  <span className="text-muted-foreground">
                    · {r.description} · {formatFiles(r.files.length)},{" "}
                    {formatBytes(r.bytes, ui.byte_unit_base, ui.byte_units)}
                  </span>
                </li>
              ))}
            </ul>
            <div className="flex justify-end">
              <Button variant="destructive" onClick={() => setEmptying(true)}>
                <Trash2 className="size-4" aria-hidden="true" />
                Empty discarded/ ({formatFiles(data.files)})
              </Button>
            </div>
            <DiscardedTable
              data={data}
              meta={meta.data}
              busy={restore.isPending}
              onRestore={(id) => restore.mutate({ operation_ids: [id] })}
            />
          </>
        )
      ) : (
        <p className="text-muted-foreground">Loading files…</p>
      )}
      {emptying ? (
        <GuardedDialog
          label={label}
          path="discarded/empty"
          body={{}}
          title={`Empty discarded/ of ${label}`}
          description={
            <>
              Every file in <code className="text-xs">{f.discarded_to}</code> is deleted for good,
              including files this app did not put there.
            </>
          }
          action={(n) => `Delete ${formatFiles(n)}`}
          meta={meta.data}
          open
          onOpenChange={setEmptying}
        />
      ) : null}
      <Button variant="ghost" className="text-muted-foreground" onClick={() => remove.mutate()}>
        Remove from the app (files are not touched)
      </Button>
    </div>
  );
}
