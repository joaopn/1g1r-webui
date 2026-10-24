import { useMutation } from "@tanstack/react-query";
import { Archive } from "lucide-react";
import { useState } from "react";
import { useParams } from "react-router-dom";
import { toast } from "sonner";
import { GuardedDialog } from "@/components/apply/GuardedDialog";
import { RunPanel } from "@/components/apply/RunPanel";
import { useRestore } from "@/components/apply/useRestore";
import { Box } from "@/components/Box";
import { StatCard } from "@/components/StatCard";
import { Button } from "@/components/ui/button";
import { SwitchKeys } from "@/components/updates/SwitchKeys";
import { UpdatesTable } from "@/components/updates/UpdatesTable";
import { ApiError, api, json } from "@/lib/api";
import { formatCount, formatFiles } from "@/lib/format";
import { invalidateFolder, useFolder, useFolderCard, useMeta, useUpdates } from "@/lib/queries";
import type { Updates } from "@/lib/types";
import { FolderHeader } from "@/pages/FolderHeader";

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : String(err));

/** Updates (title-ID sets, Switch): 1G1R keeps every update; here the older ones of a game
 * are proposed for discarded/updates/, unless kept. */
export function FolderUpdatesPage() {
  const { label = "" } = useParams();
  const card = useFolderCard(label);
  const meta = useMeta();
  const folder = useFolder(label, false);
  const titleIds = folder.data?.title_ids ?? false;
  const updates = useUpdates(label, titleIds);
  const restore = useRestore(label);
  const [moving, setMoving] = useState(false);
  const keep = useMutation({
    mutationFn: (body: { rel_paths: string[]; keep: boolean }) =>
      api<Updates>(`/folders/${label}/updates/keep`, json("PUT", body)),
    onSuccess: () => invalidateFolder(label),
    onError: (err) => toast.error(errorText(err)),
  });

  if (folder.error) return <p className="text-status-bad">{errorText(folder.error)}</p>;
  if (!meta.data || !folder.data) return <p className="text-muted-foreground">Loading…</p>;
  const f = folder.data;
  if (!titleIds)
    return (
      <div className="space-y-6">
        <FolderHeader folder={f} meta={meta.data} section="updates" card={card} />
        <p className="text-muted-foreground">This platform has no updates.</p>
      </div>
    );
  const data = updates.data;
  const proposed = data?.counts.proposed ?? 0;

  return (
    <div className="space-y-6">
      <FolderHeader folder={f} meta={meta.data} section="updates" card={card} />
      <Box
        title="Older updates"
        actions={
          <Button size="sm" disabled={proposed === 0} onClick={() => setMoving(true)}>
            <Archive className="size-3.5" aria-hidden="true" />
            Move {formatFiles(proposed)} to discarded/
          </Button>
        }
      >
        <p className="text-muted-foreground">
          1G1R keeps every update and DLC. Here, updates older than a game's newest are proposed for{" "}
          <code className="text-xs">{f.discarded_to}updates/</code>, restorable. Keep the ones you
          need (some mods need an older update).
        </p>
        <p className="text-muted-foreground">
          The version is read from the file's cnmt.xml, else with your prod.keys. When one of a
          game's updates has none, nothing of that game is proposed.
        </p>
        <p className="text-muted-foreground">
          Latest: the newest update released, from titledb (downloaded in Settings → Platform DATs).
          It is shown only; nothing is downloaded.
        </p>
      </Box>
      <SwitchKeys label={label} />
      <RunPanel label={label} meta={meta.data} />
      {updates.error ? (
        <p className="text-status-bad">{errorText(updates.error)}</p>
      ) : !data ? (
        <p className="text-muted-foreground">Loading updates…</p>
      ) : data.counts.total === 0 ? (
        <p className="text-muted-foreground">No update found in this set. Scan to look again.</p>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <StatCard value={formatCount(data.counts.total)} label="updates" />
            <StatCard value={formatCount(proposed)} label="older, to discard" />
            <StatCard value={formatCount(data.counts.unknown)} label="version unknown" />
            <StatCard value={formatCount(data.counts.newer)} label="games with a newer update" />
          </div>
          <UpdatesTable
            updates={data.updates}
            meta={meta.data}
            busy={keep.isPending || restore.isPending}
            onKeep={(relPath, kept) => keep.mutate({ rel_paths: [relPath], keep: kept })}
            onRestore={(id) => restore.mutate({ operation_ids: [id] })}
          />
        </>
      )}
      {moving ? (
        <GuardedDialog
          label={label}
          path="updates/discard"
          body={{}}
          title={`Move older updates of ${label}`}
          description={
            <>
              These updates move to <code className="text-xs">{f.discarded_to}updates/</code>.
              Nothing is deleted, and each move can be restored.
            </>
          }
          action={(n) => `Move ${formatFiles(n)}`}
          meta={meta.data}
          open
          onOpenChange={setMoving}
        />
      ) : null}
    </div>
  );
}
