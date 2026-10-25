import { useMutation } from "@tanstack/react-query";
import { Archive } from "lucide-react";
import { useState } from "react";
import { useParams } from "react-router-dom";
import { toast } from "sonner";
import { GuardedDialog } from "@/components/apply/GuardedDialog";
import { RunPanel } from "@/components/apply/RunPanel";
import { useRestore } from "@/components/apply/useRestore";
import { ScanPanel } from "@/components/ScanPanel";
import { StatCard } from "@/components/StatCard";
import { Button } from "@/components/ui/button";
import { SwitchKeys } from "@/components/updates/SwitchKeys";
import { UpdatesTable } from "@/components/updates/UpdatesTable";
import { ApiError, api, json } from "@/lib/api";
import { formatCount, formatFiles } from "@/lib/format";
import {
  invalidateFolder,
  useConsoleKeys,
  useFolder,
  useFolderCard,
  useMeta,
  useUpdates,
} from "@/lib/queries";
import type { Updates } from "@/lib/types";
import { FolderHeader } from "@/pages/FolderHeader";

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : String(err));

/** Updates & DLC (title-ID sets, Switch): 1G1R never acts on them and Matching lists base
 * files only; here the older updates of a game are proposed for discarded/updates/, unless
 * kept, and DLC are listed, always kept. */
export function FolderUpdatesPage() {
  const { label = "" } = useParams();
  const card = useFolderCard(label);
  const meta = useMeta();
  const folder = useFolder(label, meta.data?.ui.poll_interval_ms ?? false);
  const titleIds = folder.data?.title_ids ?? false;
  const updates = useUpdates(label, titleIds);
  const keys = useConsoleKeys();
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
  const waiting = f.summary.waiting ?? 0;

  const unreadable =
    data && data.counts.unreadable > 0 && keys.data && keys.data.prod_keys === null
      ? data.counts.unreadable
      : 0;

  return (
    <div className="space-y-6">
      <FolderHeader folder={f} meta={meta.data} section="updates" card={card} />
      {data && data.games.length > 0 ? (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          <StatCard value={formatCount(data.counts.total)} label="updates" />
          <StatCard value={formatCount(proposed)} label="older, to discard" />
          <StatCard value={formatCount(data.counts.unknown)} label="version unknown" />
          <StatCard
            value={formatCount(data.games.filter((g) => g.newer).length)}
            label="games with a newer update"
          />
          <StatCard value={formatCount(data.counts.dlc)} label="DLC" />
        </div>
      ) : null}
      <SwitchKeys label={label} />
      <ScanPanel
        label={label}
        kind="identify"
        scan={f.scan}
        lastScan={f.last_scan}
        title="Discard old updates"
        quickOnly
        blocked={
          waiting > 0
            ? `Convert or discard first: ${formatFiles(waiting)} not in the target format (Conversion tab)`
            : undefined
        }
        actions={
          <Button variant="outline" disabled={proposed === 0} onClick={() => setMoving(true)}>
            <Archive className="size-4" aria-hidden="true" />
            Discard{proposed > 0 ? ` (${formatFiles(proposed)})` : ""}
          </Button>
        }
      >
        <p className="text-muted-foreground">
          {proposed > 0
            ? `${formatFiles(proposed)} older than their game's newest update. They move to discarded/ and can be restored; keep any you need (e.g. for mods).`
            : "No old updates to discard."}{" "}
          Added an update? A quick scan reads only new files.
        </p>
        {unreadable > 0 ? (
          <p className="text-status-info" data-testid="unreadable-updates">
            {formatCount(unreadable)} {unreadable === 1 ? "update has" : "updates have"} no readable
            version: add prod.keys to read them.
          </p>
        ) : null}
      </ScanPanel>
      <RunPanel label={label} meta={meta.data} />
      {updates.error ? (
        <p className="text-status-bad">{errorText(updates.error)}</p>
      ) : !data ? (
        <p className="text-muted-foreground">Loading updates…</p>
      ) : data.games.length === 0 ? (
        <p className="text-muted-foreground">No game found in this set. Scan to look again.</p>
      ) : (
        <UpdatesTable
          updates={data.updates}
          games={data.games}
          meta={meta.data}
          busy={keep.isPending || restore.isPending}
          onKeep={(relPath, kept) => keep.mutate({ rel_paths: [relPath], keep: kept })}
          onRestore={(id) => restore.mutate({ operation_ids: [id] })}
        />
      )}
      {moving ? (
        <GuardedDialog
          label={label}
          path="updates/discard"
          body={{}}
          title={`Discard old updates of ${label}`}
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
